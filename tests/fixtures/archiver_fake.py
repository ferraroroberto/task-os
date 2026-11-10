"""A fake folder-explorer archive service — the HTTP boundary, without Outlook.

``src/archive_batch.py`` never imports the archiver: it calls folder-explorer's
v1 archive API (``POST /api/v1/archive/{plan,apply,revert,index}``,
``docs/service-api.md`` in that repo) and reads one envelope back. So the honest
fake is not a monkeypatched client but a **real server**: :class:`FakeArchiver`
is a ``ThreadingHTTPServer`` on a loopback port that answers those four routes
in the documented envelope, classified from the canned archiver document the
same way folder-explorer classifies a child's output. Everything the service
actually has to get right then runs for real — the request body it builds, the
JSON parse, the outcome handling, the client timeout, a server that is gone.

The canned documents come from ``build_fake_archiver``'s per-verb lists, one per
call in order (the last one repeats). Every call is recorded (``fake.calls``:
``{verb, body, payload}``, ``payload`` being the ``decisions`` / ``items`` of a
write verb) and every re-index (``fake.index_calls``: its body), which is what
lets a test assert the one thing the archiver's author asked for: that a
candidate's ``date_prefix`` is handed back **unchanged** on the ``apply``
decision.

``mode`` picks a failure the client has to tell apart:

``ok``        answer from the canned documents
``garbled``   ``200`` with a page that is not JSON
``bare422``   ``422`` with FastAPI's validation body (no envelope)
``v2``        an envelope claiming ``schema_version`` 2
``busy``      the ``busy`` refusal folder-explorer answers while another call runs
``not_this_pc``  the ``403`` refusal for a caller that is not on its PC

It also answers ``GET /api/v1/search/status`` as all-ok, so an instance whose one
folder-explorer address is this fake does not show Search as down.

``stop()`` closes the connections it still serves, so a stopped fake reads as
folder-explorer *down*.

Synthetic throughout, as everything on screen and in a fixture here must be
(public repo): the subjects, senders and folders below are invented.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SCHEMA_VERSION = 1

#: A folder the fake ranks first, with the archiver's own per-folder naming
#: inference already applied — the value that must come back untouched.
FOLDER_HOUSE = "E:\\archive\\house\\heating"
FOLDER_BILLS = "E:\\archive\\admin\\bills"


def candidate(folder: str, score: float, *, date_prefix: bool = False, name: str = "") -> dict[str, Any]:
    return {
        "folder_path": folder,
        "display_name": name or folder.rsplit("\\", 1)[-1],
        "score": score,
        "match_count": 3,
        "sample_subjects": ["a previous thread"],
        "date_prefix": date_prefix,
    }


def mail(
    message_id: str,
    *,
    subject: str = "A synthetic subject",
    sender: str = "someone@example.invalid",
    candidates: list[dict[str, Any]] | None = None,
    already_archived: str | None = None,
    attachments: int = 0,
    in_inbox: bool | None = True,
) -> dict[str, Any]:
    """One ``plan`` mail.

    ``in_inbox`` is what today's archiver states on every mail it reports
    (email-archiver#59): always ``True``, because ``plan`` enumerates the Inbox,
    and the fact that separates an ``already_archived`` mail *still sitting in
    the Inbox* from one that is properly filed and gone. ``None`` omits the key
    altogether — the document an **older** archiver produces, which is the case
    a defensive reader has to keep the old no-op for.
    """
    doc = {
        "message_id": message_id,
        "entry_id": f"ENTRY-{message_id}",
        "subject": subject,
        "sender": sender,
        "recipients": ["me@example.invalid"],
        "date_sent": "2026-09-01T09:15:00+02:00",
        "body_preview": "Synthetic preview text.",
        "attachment_count": attachments,
        "flag_status": 0,
        "already_archived": already_archived,
        "candidates": list(candidates or []),
    }
    if in_inbox is not None:
        doc["in_inbox"] = in_inbox
    return doc


def plan_doc(mails: list[dict[str, Any]], *, skipped: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    already = sum(1 for m in mails if m.get("already_archived"))
    return {
        "verb": "plan",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:00:00+02:00",
        "archive_folder": "Archive",
        "category": "Archived by task-os",
        "counts": {
            "inbox": len(mails) + len(skipped or []),
            "planned": len(mails) - already,
            "already_archived": already,
            "skipped": len(skipped or []),
        },
        "mails": mails,
        "skipped": list(skipped or []),
    }


def apply_result(
    message_id: str,
    folder: str,
    *,
    ok: bool = True,
    files: list[str] | None = None,
    error: dict[str, str] | None = None,
    sequence: str = "0042",
    reused: bool = False,
    move_via: str = "original",
) -> dict[str, Any]:
    """One ``apply`` result.

    ``reused`` and ``move_via`` arrived with email-archiver#59 and are what a
    *finish* looks like from the outside: ``reused: true`` with the existing
    file listed and an **empty** ``sequence_number`` (none was allocated),
    because nothing was written. ``move_via`` names which of the three move
    paths finished it — ``refetched`` · ``saved_retry`` · ``original``.
    """
    return {
        "message_id": message_id,
        "folder_path": folder,
        "ok": ok,
        "sequence_number": sequence,
        "files": list(files or []),
        "entry_id": f"MOVED-{message_id}" if ok else "",
        "moved": ok,
        "categorized": ok,
        "reused": reused,
        "move_via": move_via if ok else None,
        "error": error,
    }


def renumbered(
    folder: str,
    *,
    old: str | None = None,
    new: str | None = None,
    message_id: str = "renumbered@example.invalid",
    attachments: list[list[str]] | None = None,
) -> dict[str, Any]:
    """One folder's ``renumbered`` map with a single changed bundle in it.

    The archiver's shape verbatim (email-archiver#61): ``from``/``to`` are the
    ``.msg``'s old and new names and are ``None`` for a bundle that has none,
    ``attachments`` pairs each attachment's old name with its new one, and only
    bundles that actually moved appear at all.
    """
    return {
        folder: [{
            "from": old, "to": new, "message_id": message_id,
            "attachments": [list(a) for a in attachments or []],
        }],
    }


def apply_doc(
    results: list[dict[str, Any]],
    *,
    renumbered_map: dict[str, Any] | None = None,
    refused: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """One ``apply`` document; ``renumbered_map`` is what ``--renumber`` adds to it.

    Additive on the archiver's side — no ``schema_version`` bump — so a
    document without either key is exactly what a build predating the flag
    prints, which is the case the reader has to keep quiet about.
    """
    applied = sum(1 for r in results if r["ok"])
    doc = {
        "verb": "apply",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:01:00+02:00",
        "archive_folder": "Archive",
        "category": "Archived by task-os",
        "counts": {"requested": len(results), "applied": applied, "failed": len(results) - applied},
        "results": results,
    }
    if renumbered_map is not None:
        doc["renumbered"] = renumbered_map
    if refused is not None:
        doc["renumber_refused"] = refused
    return doc


def revert_result(
    message_id: str, *, ok: bool = True, deleted: list[str] | None = None,
    error: dict[str, str] | None = None, refused: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "ok": ok,
        "deleted": list(deleted or []),
        "missing": [],
        "refused": list(refused or []),
        "file_errors": [],
        "moved_back": ok,
        "category_removed": ok,
        "entry_id": f"BACK-{message_id}" if ok else "",
        "error": error,
    }


def revert_doc(
    results: list[dict[str, Any]],
    *,
    renumbered_map: dict[str, Any] | None = None,
    refused: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """One ``revert`` document — ``--renumber`` closes the hole the undo left."""
    reverted = sum(1 for r in results if r["ok"])
    doc = {
        "verb": "revert",
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:02:00+02:00",
        "archive_folder": "Archive",
        "category": "Archived by task-os",
        "counts": {"requested": len(results), "reverted": reverted, "failed": len(results) - reverted},
        "results": results,
    }
    if renumbered_map is not None:
        doc["renumbered"] = renumbered_map
    if refused is not None:
        doc["renumber_refused"] = refused
    return doc


def error_doc(verb: str, code: str, message: str) -> dict[str, Any]:
    return {
        "verb": verb,
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-09-01T10:00:00+02:00",
        "error": {"code": code, "message": message},
    }


_NOT_FOUND_CODES = {"mailbox_unknown": 404, "mailbox_not_in_outlook": 404}
_REFUSED_CODES = {"bad_input": 422, "config_missing": 503, "mailbox_registry_invalid": 503,
                  "outlook_unavailable": 503, "com_unavailable": 503}
_NOT_THERE = {"not_in_inbox", "not_in_sent", "not_in_archive_folder"}
_INDEX_REFUSED = {2: ("busy", 409, "another email run held the index past the wait"),
                  3: ("not_in_email_folder", 422, "the folder is not inside the email folders"),
                  4: ("email_index_not_set_up", 503, "the email index is not set up on this PC")}


def _envelope(verb: str, outcome: str, status: int, **fields: Any) -> tuple[dict[str, Any], int]:
    body = {"schema_version": SCHEMA_VERSION, "verb": verb, "outcome": outcome, "code": None, "reason": None,
            "acknowledged": True, "confirmed": [], "failed": [], "result": None}
    body.update(fields)
    return body, status


def classify(verb: str, doc: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """The envelope folder-explorer's ``src/archive_api.py`` makes of a child's document."""
    if doc.get("schema_version") != SCHEMA_VERSION:
        return _envelope(verb, "error", 502, code="schema_mismatch", acknowledged=False,
                         reason=f"the archiver's document is schema_version {doc.get('schema_version')!r}")
    error = doc.get("error")
    if isinstance(error, dict):
        code, reason = str(error.get("code") or "unknown"), str(error.get("message") or "")
        if code in _NOT_FOUND_CODES:
            return _envelope(verb, "not-found", _NOT_FOUND_CODES[code], code=code, reason=reason, result=doc)
        if code in _REFUSED_CODES:
            return _envelope(verb, "refused", _REFUSED_CODES[code], code=code, reason=reason, result=doc)
        return _envelope(verb, "error", 500, code=code, reason=reason, result=doc)
    if verb == "plan":
        return _envelope("plan", "done", 200, result=doc)
    results = [r for r in doc.get("results") or [] if isinstance(r, dict)]
    confirmed = [str(r.get("message_id")) for r in results if r.get("ok")]
    failed = [{"message_id": str(r.get("message_id")),
               "code": str((r.get("error") or {}).get("code") or "failed")} for r in results if not r.get("ok")]
    if not failed:
        return _envelope(verb, "done", 200, result=doc, confirmed=confirmed)
    if not confirmed and all(f["code"] in _NOT_THERE for f in failed):
        return _envelope(verb, "not-found", 404, code=failed[0]["code"], reason="none of the mails is where the verb looks",
                         result=doc, failed=failed)
    reason = f"{len(failed)} of {len(results)} mail(s) not confirmed"
    if confirmed:
        return _envelope(verb, "error", 207, code="partial", reason=reason, result=doc, confirmed=confirmed, failed=failed)
    return _envelope(verb, "error", 502, code="failed", reason=reason, result=doc, failed=failed)


class FakeArchiver:
    """The four archive routes over canned documents; see the module docstring."""

    def __init__(
        self,
        *,
        plan: list[dict[str, Any]] | None = None,
        apply: list[dict[str, Any]] | None = None,
        revert: list[dict[str, Any]] | None = None,
        scan_exit_code: int = 0,
        sleep: float = 0.0,
        sleep_verbs: tuple[str, ...] = ("plan", "apply", "revert"),
    ) -> None:
        self.documents = {"plan": list(plan or []), "apply": list(apply or []), "revert": list(revert or [])}
        self.scan_exit_code = scan_exit_code
        self.sleep = sleep
        self.sleep_verbs = sleep_verbs
        self.mode = "ok"
        self.calls: list[dict[str, Any]] = []
        self.index_calls: list[dict[str, Any]] = []
        self._seen = {"plan": 0, "apply": 0, "revert": 0}
        self._lock = threading.Lock()
        self._live: set[socket.socket] = set()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                fake._live.add(self.connection)

            def finish(self) -> None:
                fake._live.discard(self.connection)
                super().finish()

            def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
                """Only the search status, so an app wired to this one address does not read as "search down"."""
                ok = {"state": "ok", "reason": None}
                answer = {"schema_version": SCHEMA_VERSION, **ok, "folders": {**ok, "roots": 1, "scanned": 1, "scanning": False},
                          "emails": {**ok, "count": 0}} if self.path.split("?")[0].endswith("/search/status") else {"detail": "Not Found"}
                payload = json.dumps(answer).encode("utf-8")
                self.send_response(200 if "state" in answer else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                status, answer = fake._answer(self.path, body)
                payload = answer if isinstance(answer, bytes) else json.dumps(answer).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html" if isinstance(answer, bytes) else "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                """Silence: pytest's captured output is for the test, not this."""

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request: Any, client_address: Any) -> None:
                """A client that went away (or was cut off by stop()) is not worth a traceback in the test log."""

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        for conn in list(self._live):
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # ------------------------------------------------------------ answers

    def _answer(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        verb = path.rstrip("/").rsplit("/", 1)[-1]
        if verb not in ("plan", "apply", "revert", "index"):
            return 404, {"detail": "Not Found"}
        payload = body.get("decisions") if verb == "apply" else body.get("items") if verb == "revert" else None
        with self._lock:
            (self.index_calls if verb == "index" else self.calls).append(
                body if verb == "index" else {"verb": verb, "body": body, "payload": payload}
            )
        if self.mode == "garbled":
            return 200, b"<html>sign in</html>"
        if self.mode == "bare422":
            return 422, {"detail": [{"loc": ["body", "candidates"], "msg": "out of range"}]}
        if self.mode == "busy":
            return self._flip(*_envelope(verb, "refused", 409, code="busy", acknowledged=False,
                                         reason="an archive call is already running: one Outlook, one call at a time"))
        if self.mode == "not_this_pc":
            return self._flip(*_envelope(verb, "refused", 403, code="not_this_pc", acknowledged=False,
                                         reason="archiving works on the PC only"))
        if verb in self.sleep_verbs:
            time.sleep(self.sleep)
        if verb == "index":
            return self._flip(*self._index())
        with self._lock:
            answers = self.documents[verb]
            index = min(self._seen[verb], len(answers) - 1) if answers else 0
            self._seen[verb] += 1
        return self._flip(*classify(verb, answers[index] if answers else {}))

    def _flip(self, envelope: dict[str, Any], status: int) -> tuple[int, Any]:
        if self.mode == "v2":
            envelope = {**envelope, "schema_version": 2}
        return status, envelope

    def _index(self) -> tuple[dict[str, Any], int]:
        if self.scan_exit_code == 0:
            return _envelope("index", "done", 200)
        if self.scan_exit_code in _INDEX_REFUSED:
            code, status, reason = _INDEX_REFUSED[self.scan_exit_code]
            return _envelope("index", "refused", status, code=code, reason=reason)
        return _envelope("index", "error", 500, code="failed", reason=f"the re-index failed (exit {self.scan_exit_code})")


_RUNNING: list[FakeArchiver] = []


def build_fake_archiver(
    *,
    plan: list[dict[str, Any]] | None = None,
    apply: list[dict[str, Any]] | None = None,
    revert: list[dict[str, Any]] | None = None,
    scan_exit_code: int = 0,
    sleep: float = 0.0,
    sleep_verbs: tuple[str, ...] = ("plan", "apply", "revert"),
) -> FakeArchiver:
    """Start a fake archive service; returns it (``.url``, ``.calls``, ``.index_calls``).

    Each verb takes a **list** of documents, one per call in order (the last one
    repeats), so a test can drive a move — revert, then apply — through one fake.
    That is also how a **retry** is driven: an ``apply`` list whose first
    document answers ``move_failed`` with the files already written and whose
    next one answers ``ok`` with ``reused: true``, which is exactly the pair the
    archiver produces when the same decision is sent a second time.

    Every fake started here is stopped by :func:`stop_all` (the archive tests'
    autouse fixture and the e2e fixture's teardown call it).
    """
    fake = FakeArchiver(
        plan=plan, apply=apply, revert=revert, scan_exit_code=scan_exit_code,
        sleep=sleep, sleep_verbs=sleep_verbs,
    )
    _RUNNING.append(fake)
    return fake


def stop_all() -> None:
    """Stop every fake :func:`build_fake_archiver` started."""
    while _RUNNING:
        _RUNNING.pop().stop()


__all__ = [
    "FOLDER_BILLS", "FOLDER_HOUSE", "FakeArchiver", "apply_doc", "apply_result", "build_fake_archiver",
    "candidate", "classify", "error_doc", "mail", "plan_doc", "renumbered", "revert_doc", "revert_result",
    "stop_all",
]
