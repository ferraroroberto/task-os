"""Batch archiving of the Outlook Inbox through email-archiver (#157, Step 1/3).

One gesture files the whole Inbox: every mail is written into the archive
folder the archiver ranks best, moved to Outlook's *Archive* folder and tagged,
and the run is recorded here so a human can review it and undo any single mail.
This module is the backend half — the schema (v14), the service that drives the
archiver, and the state machine the API in ``app/webapp/routers/archive.py``
exposes. The LLM re-ranking (#158) and the screen (#159) build on it.

**task-os never imports the archiver.** Everything crosses a subprocess
boundary as JSON: ``<archive.python> main_batch.py {plan|apply|revert}`` run in
the archiver's own checkout, bounded by ``archive.timeout_seconds`` and spawned
with ``CREATE_NO_WINDOW``. That is not fastidiousness — every verb drives
Outlook over COM, and a COM modal (the address-book prompt, a profile chooser)
blocks whatever thread it is raised on. A hung Outlook is therefore a child
this process kills, never a wedged webapp. The archiver keeps sole ownership of
Outlook, of the filenames and of its index; task-os only decides *which folder*.

The child's contract (email-archiver#53, ``email_archiver/batch.py``):

- exit **0** — the run completed and stdout carries one JSON document.
  Individual mails may still have failed, each with its own ``error.code``
  (``bad_decision`` · ``not_in_inbox`` · ``not_in_archive_folder`` ·
  ``archive_failed`` · ``move_failed`` · ``category_failed``).
- exit **2** — the run could not start; stdout is ``{"error": {code, message}}``
  with ``config_missing`` · ``bad_input`` · ``outlook_unavailable`` ·
  ``com_unavailable``.
- every document carries ``schema_version`` (1 today). A version this build
  does not understand is refused by name rather than read field by field.

Four failures that a caller has to be able to tell apart, so four distinct
messages and codes: the archiver is **not configured** here (409), Outlook is
**unreachable** (502), the child **timed out** (504), and a run is **already in
flight** (409). A fifth — the index rescan afterwards — is deliberately *not*
fatal: the mails are filed either way, so the run finishes ``done`` and carries
the rescan's failure in its ``error`` column. "Filed, but the index has not
confirmed it" is its own state, never folded into a clean run.

State machine, one ``archive_items`` row per mail:

    archived      filed on disk and moved in Outlook (or already filed, per the
                  archiver's index, and recorded with the existing file)
    needs_review  left in the Inbox: the best candidate scored below
                  ``archive.confidence_threshold``, or there was none
    failed        the archiver refused or broke on this mail; ``error`` says
                  which of its codes. Revertible when files were still written
                  (``apply`` fills ``files`` *before* the move on purpose)
    reverted      the files are gone and the mail is back in the Inbox
    moved         re-filed into a folder a human picked

``archived`` and ``moved`` are the two "filed" states, and the partial unique
index on ``message_id`` covers exactly those — a mail cannot be filed twice,
whatever the archiver's index believes, and a reverted mail is free to be
archived again.

Idempotency is the Internet Message-ID throughout (never an Outlook EntryID,
which the ``apply`` move itself rewrites). A second run over a mail this
database has already filed writes **nothing**: no row, no child call for it.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from src import clock, placeholders
from src.config import AppConfig
from src.db import connect
from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

#: The only batch-document schema this build understands (email-archiver's
#: ``batch.SCHEMA_VERSION``). A newer archiver is refused by name — reading a
#: field that silently moved is how a mail gets filed into the wrong folder.
SUPPORTED_SCHEMA_VERSION = 1

#: Seconds the child waits for a freshly started Outlook to answer over COM
#: (its own ``--start-timeout``). Well inside ``archive.timeout_seconds``, so a
#: closed Outlook fails as *unreachable* rather than as *timed out*.
OUTLOOK_START_TIMEOUT_S = 60.0

#: Bound on the index rescan that follows a run. Its own budget: a rescan walks
#: the archive tree, and it must never eat the run's timeout.
SCAN_TIMEOUT_S = 900.0

#: The two states in which a mail is actually filed somewhere.
FILED_STATUSES = ("archived", "moved")
#: What a human may still act on.
REVIEWABLE_STATUSES = ("needs_review", "failed")

_ITEM_COLUMNS = (
    "id", "run_id", "message_id", "entry_id", "subject", "sender", "sent_at",
    "attachments", "candidates_json", "chosen_folder", "chosen_rank", "confidence",
    "reason", "date_prefix", "files_json", "sequence", "status", "error", "decided_at",
)
_RUN_COLUMNS = (
    "id", "started_at", "finished_at", "status", "planned", "archived",
    "needs_review", "failed", "error",
)


class ArchiveError(RuntimeError):
    """A classified archiving failure, ready for the one JSON error envelope."""

    def __init__(self, code: str, message: str, *, http_status: int, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.detail = detail


# --------------------------------------------------------------- persistence
# The archive run/item tables are this module's own, not task rules: nothing
# here touches a task, so none of it belongs in ``src/tasks_repo.py``.


def _row(row: sqlite3.Row | None, columns: tuple[str, ...]) -> dict[str, Any] | None:
    return {k: row[k] for k in columns} if row is not None else None


def _item_dict(row: sqlite3.Row) -> dict[str, Any]:
    """One item row as the API renders it: JSON columns parsed, flags real bools."""
    item = dict(_row(row, _ITEM_COLUMNS) or {})
    item["candidates"] = _loads(item.pop("candidates_json"), [])
    item["files"] = _loads(item.pop("files_json"), [])
    item["date_prefix"] = bool(item["date_prefix"])
    return item


def _same_folder(a: str | None, b: str | None) -> bool:
    """Two folder paths naming the same place, separators and case aside.

    The archiver reports Windows paths with backslashes; ``placeholders.resolve``
    returns forward slashes. Comparing them raw would call every move a move
    into a new folder.
    """
    if not a or not b:
        return False
    return placeholders.normalize_path(a).casefold() == placeholders.normalize_path(b).casefold()


def _loads(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("⚠️ archive: unreadable JSON column — falling back to %r", default)
        return default


def create_run(conn: sqlite3.Connection) -> dict[str, Any]:
    """Open a run row in ``running``; its id is what ``POST /api/archive/run`` returns."""
    cur = conn.execute(
        "INSERT INTO archive_runs (started_at, status) VALUES (?, 'running')",
        (clock.now_iso(),),
    )
    conn.commit()
    return get_run(conn, int(cur.lastrowid))  # type: ignore[return-value]


def finish_run(
    conn: sqlite3.Connection, run_id: int, *, status: str, error: str | None = None
) -> dict[str, Any]:
    """Close a run, recomputing its counters from the rows it actually wrote.

    Derived rather than accumulated on purpose: the counters can then never
    disagree with the items, which are what the screen renders.
    """
    counts = {s: 0 for s in ("archived", "needs_review", "failed", "reverted", "moved")}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM archive_items WHERE run_id = ? GROUP BY status",
        (run_id,),
    ).fetchall():
        counts[str(row["status"])] = int(row["n"])
    planned = sum(counts.values())
    conn.execute(
        "UPDATE archive_runs SET finished_at = ?, status = ?, planned = ?, archived = ?, "
        "needs_review = ?, failed = ?, error = ? WHERE id = ?",
        (
            clock.now_iso(), status, planned,
            counts["archived"] + counts["moved"], counts["needs_review"],
            counts["failed"], error, run_id,
        ),
    )
    conn.commit()
    return get_run(conn, run_id)  # type: ignore[return-value]


def insert_item(conn: sqlite3.Connection, run_id: int, **fields: Any) -> int:
    """Write one decided mail. Raises ``sqlite3.IntegrityError`` on a double filing."""
    payload = {"run_id": run_id, **fields}
    columns = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    cur = conn.execute(
        f"INSERT INTO archive_items ({columns}) VALUES ({marks})", tuple(payload.values())
    )
    conn.commit()
    return int(cur.lastrowid)


def update_item(conn: sqlite3.Connection, item_id: int, **fields: Any) -> dict[str, Any]:
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE archive_items SET {assignments} WHERE id = ?", (*fields.values(), item_id)
    )
    conn.commit()
    return get_item(conn, item_id)  # type: ignore[return-value]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM archive_runs WHERE id = ?", (run_id,)).fetchone()
    return _row(row, _RUN_COLUMNS)


def list_runs(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM archive_runs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [_row(r, _RUN_COLUMNS) for r in rows]  # type: ignore[misc]


def list_items(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM archive_items WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    return [_item_dict(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM archive_items WHERE id = ?", (item_id,)).fetchone()
    return _item_dict(row) if row is not None else None


def filed_message_ids(conn: sqlite3.Connection) -> set[str]:
    """Every ``message_id`` this database already has filed — the run's skip list."""
    marks = ", ".join("?" for _ in FILED_STATUSES)
    rows = conn.execute(
        f"SELECT DISTINCT message_id FROM archive_items WHERE status IN ({marks})",
        FILED_STATUSES,
    ).fetchall()
    return {str(r["message_id"]) for r in rows}


# ------------------------------------------------------------------- service


class ArchiveBatchService:
    """Drives the archiver's batch CLI and records what it did (``app.state.archive``).

    One run at a time, and one archiver child at a time: ``revert`` and ``move``
    take the same lock a run does, because they all reach the same single-
    threaded Outlook COM apartment. A second caller gets 409 with that as the
    reason, never a queue that quietly reorders someone's Inbox.
    """

    def __init__(self, config: AppConfig) -> None:
        cfg = config.archive
        self.configured_enabled = bool(cfg.enabled)
        self.repo = Path(cfg.repo.strip()) if cfg.repo.strip() else None
        self.python = Path(cfg.python.strip()) if cfg.python.strip() else self._default_python(self.repo)
        self.candidates = max(1, int(cfg.candidates))
        self.threshold = float(cfg.confidence_threshold)
        self.timeout = float(cfg.timeout_seconds)
        self.placeholders = dict(config.placeholders)
        self.enabled, self.reason = self._configured()
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        if not self.enabled:
            logger.warning("⚠️ archive: batch archiving off — %s", self.reason)

    # ----------------------------------------------------------- readiness
    @staticmethod
    def _default_python(repo: Path | None) -> Path | None:
        """The archiver's own venv interpreter — never task-os's."""
        if repo is None:
            return None
        return repo / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")

    @property
    def script(self) -> Path | None:
        return self.repo / "main_batch.py" if self.repo else None

    @property
    def scan_script(self) -> Path | None:
        return self.repo / "main_scan.py" if self.repo else None

    def _configured(self) -> tuple[bool, str | None]:
        """``(True, None)``, or ``False`` + the one reason that actually applies.

        Five distinct failures, five distinct messages: "you turned it off",
        "you never said where the archiver is", "that folder is not there",
        "its venv is not built" and "that checkout has no batch mode" each need
        a different fix, and a single "not configured" would hide which.
        """
        if not self.configured_enabled:
            return False, "disabled in config (archive.enabled)"
        if self.repo is None:
            return False, "archive.repo not configured — point it at the email-archiver checkout"
        if not self.repo.is_dir():
            return False, f"email-archiver checkout not found at {self.repo}"
        if self.python is None or not self.python.is_file():
            return False, (
                f"the archiver's Python is not at {self.python} — build its venv, or set "
                "archive.python"
            )
        if self.script is None or not self.script.is_file():
            return False, (
                f"no main_batch.py in {self.repo} — this needs an email-archiver build with "
                "batch mode"
            )
        return True, None

    def status(self, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        """What ``/api/status``'s ``archive`` key, Settings (#159) and the CLI render."""
        last_run: dict[str, Any] | None = None
        own = conn is None
        c = conn or connect()
        try:
            runs = list_runs(c, limit=1)
            last_run = runs[0] if runs else None
        except sqlite3.Error as exc:  # a status must never be the thing that 500s
            logger.warning("⚠️ archive: could not read the last run — %s", exc)
        finally:
            if own:
                c.close()
        return {
            "configured": self.enabled,
            "reason": None if self.enabled else self.reason,
            "running": self.running,
            "repo": str(self.repo) if self.repo else None,
            "candidates": self.candidates,
            "confidence_threshold": self.threshold,
            "timeout_seconds": self.timeout,
            "last_run": last_run,
            "last_error": self.last_error,
        }

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def stop(self, timeout: float = 5.0) -> None:
        """Let an in-flight run finish (lifespan shutdown, and the tests' join)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if not thread.is_alive():
                self._thread = None

    # ------------------------------------------------------------ children
    def _spawn_batch(self, args: list[str], *, verb: str) -> dict[str, Any]:
        """One ``main_batch.py`` call → its one JSON document, or ``ArchiveError``."""
        assert self.python is not None and self.script is not None and self.repo is not None
        cmd = [
            str(self.python), str(self.script),
            "--start-timeout", str(OUTLOOK_START_TIMEOUT_S), *args,
        ]
        logger.info("ℹ️ archive: %s — spawning the archiver's %s", verb, self.script.name)
        try:
            proc = subprocess.run(  # noqa: S603 — a configured local interpreter and script
                cmd, cwd=str(self.repo), capture_output=True, timeout=self.timeout,
                creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise ArchiveError(
                "archive_timeout",
                f"the archiver did not finish {verb} within {self.timeout:.0f} s — Outlook may be "
                "showing a dialog nobody can see",
                http_status=504,
            ) from exc
        except OSError as exc:
            raise ArchiveError(
                "archive_spawn_failed",
                f"could not run the archiver's {self.script.name}: {type(exc).__name__}: {exc}",
                http_status=502,
            ) from exc

        # The child reconfigures its stdout to UTF-8 before printing, so this is
        # UTF-8 whatever the console code page is — decoded explicitly rather
        # than through ``text=True``'s ambient locale.
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        try:
            doc = json.loads(stdout)
        except ValueError as exc:
            raise ArchiveError(
                "archive_bad_output",
                f"the archiver's {verb} printed no readable JSON (exit {proc.returncode})",
                http_status=502, detail=(stderr or stdout)[-800:] or None,
            ) from exc
        if not isinstance(doc, dict):
            raise ArchiveError(
                "archive_bad_output", f"the archiver's {verb} printed a {type(doc).__name__}, "
                "not a document", http_status=502,
            )

        version = doc.get("schema_version")
        if version != SUPPORTED_SCHEMA_VERSION:
            raise ArchiveError(
                "archive_schema_mismatch",
                f"the archiver's batch output is schema_version {version!r}; this build "
                f"understands {SUPPORTED_SCHEMA_VERSION}",
                http_status=502,
            )
        if "error" in doc:
            raise self._child_error(doc["error"], verb=verb, returncode=proc.returncode)
        if proc.returncode != 0:
            raise ArchiveError(
                "archive_child_failed",
                f"the archiver exited with code {proc.returncode} on {verb}",
                http_status=502, detail=stderr[-800:] or None,
            )
        return doc

    @staticmethod
    def _child_error(error: Any, *, verb: str, returncode: int) -> ArchiveError:
        """The child's own ``{"error": {code, message}}``, classified for the API."""
        code = str((error or {}).get("code", "")) if isinstance(error, dict) else ""
        message = str((error or {}).get("message", "")) if isinstance(error, dict) else str(error)
        if code in ("outlook_unavailable", "com_unavailable"):
            return ArchiveError(
                "archive_outlook_unavailable",
                f"Outlook could not be reached, so no mail was touched by {verb}: {message}",
                http_status=502, detail=code,
            )
        if code == "config_missing":
            return ArchiveError(
                "archive_child_unconfigured",
                f"the email archiver's own config could not be loaded: {message}",
                http_status=502, detail=code,
            )
        return ArchiveError(
            "archive_child_failed",
            f"the archiver refused {verb} ({code or 'no code'}): {message}",
            http_status=502, detail=f"exit {returncode}",
        )

    def _spawn_with_payload(self, verb: str, flag: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        """``apply`` / ``revert``: the payload through a temp file, deleted afterwards.

        The file carries archive paths, and an archive path carries the mail's
        subject — so it lives for exactly one child call and is removed in a
        ``finally``, never left in the temp folder for something else to read.
        """
        handle, path = tempfile.mkstemp(prefix=f"taskos-archive-{verb}-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            return self._spawn_batch([verb, flag, path], verb=verb)
        finally:
            try:
                os.unlink(path)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("⚠️ archive: could not remove %s — %s", path, exc)

    def _rescan_index(self) -> str | None:
        """Let the archiver re-index what this run wrote; the reason it did not, or ``None``."""
        if self.scan_script is None or not self.scan_script.is_file():
            return f"no main_scan.py in {self.repo} — the archiver's index was not refreshed"
        assert self.python is not None and self.repo is not None
        try:
            proc = subprocess.run(  # noqa: S603 — same configured interpreter
                [str(self.python), str(self.scan_script), "--no-ui"], cwd=str(self.repo),
                capture_output=True, timeout=SCAN_TIMEOUT_S, creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return f"the archiver's index rescan did not finish within {SCAN_TIMEOUT_S:.0f} s"
        except OSError as exc:
            return f"the archiver's index rescan could not start: {type(exc).__name__}: {exc}"
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", errors="replace").strip()[-300:]
            return f"the archiver's index rescan exited with code {proc.returncode}: {tail}"
        logger.info("ℹ️ archive: the archiver re-indexed what this run filed")
        return None

    # ---------------------------------------------------------------- runs
    def _begin(self) -> int:
        """Claim the archiver and open a run row, or refuse with the reason."""
        if not self.enabled:
            raise ArchiveError("archive_disabled", self.reason or "batch archiving is off", http_status=409)
        if not self._lock.acquire(blocking=False):
            raise ArchiveError(
                "archive_in_flight",
                "an archiving run is already in progress — one Outlook, one run at a time",
                http_status=409,
            )
        try:
            conn = connect()
            try:
                return int(create_run(conn)["id"])
            finally:
                conn.close()
        except BaseException:
            self._lock.release()
            raise

    def start_run(self, *, limit: int | None = None) -> dict[str, Any]:
        """Open the run and drive it in a worker thread; returns the ``running`` row.

        The API answers 202 with this: a full-Inbox run walks every mail over
        COM and takes minutes, which is not a request to hold open.
        """
        run_id = self._begin()
        thread = threading.Thread(
            target=self._drive, args=(run_id, limit), name="task-os-archive", daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:  # pragma: no cover - the process is out of threads
            self._lock.release()
            raise
        self._thread = thread
        conn = connect()
        try:
            return get_run(conn, run_id)  # type: ignore[return-value]
        finally:
            conn.close()

    def run_now(self, *, limit: int | None = None) -> dict[str, Any]:
        """The same run, synchronously — the deterministic path for tests and the CLI."""
        return self._drive(self._begin(), limit)

    def _drive(self, run_id: int, limit: int | None) -> dict[str, Any]:
        """Plan → decide → apply → rescan, then close the run. Never raises."""
        conn = connect()
        try:
            try:
                run = self._execute(conn, run_id, limit)
            except ArchiveError as exc:
                self.last_error = f"{exc.code}: {exc}"
                logger.error("❌ archive: run %d failed — %s", run_id, exc)
                return finish_run(conn, run_id, status="failed", error=str(exc))
            except Exception as exc:  # noqa: BLE001 — a bad run is a recorded state, not a dead app
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("❌ archive: run %d failed unexpectedly", run_id)
                return finish_run(conn, run_id, status="failed", error=self.last_error)
            self.last_error = None
            return run
        finally:
            conn.close()
            self._lock.release()

    def _execute(self, conn: sqlite3.Connection, run_id: int, limit: int | None) -> dict[str, Any]:
        plan = self._spawn_batch(["plan", "--candidates", str(self.candidates)], verb="plan")
        mails = [m for m in plan.get("mails") or [] if isinstance(m, dict)]
        already_filed = filed_message_ids(conn)
        decisions: list[dict[str, Any]] = []
        item_by_message: dict[str, int] = {}
        skipped = 0

        for mail in mails:
            message_id = str(mail.get("message_id") or "").strip()
            if not message_id or message_id in already_filed:
                skipped += 1
                continue
            if limit is not None and len(item_by_message) >= limit:
                break
            decision = self._decide(mail)
            try:
                item_id = insert_item(conn, run_id, **self._item_fields(mail, decision))
            except sqlite3.IntegrityError:
                # The unique index is the last word on "a mail is filed once",
                # even against a plan this database disagrees with.
                logger.warning("⚠️ archive: %s is already filed — skipped", message_id)
                skipped += 1
                continue
            item_by_message[message_id] = item_id
            if decision["status"] == "archived":
                already_filed.add(message_id)
            if decision["apply"]:
                decisions.append({
                    "message_id": message_id,
                    "folder_path": decision["chosen_folder"],
                    # Handed straight back, unchanged: the archiver inferred the
                    # naming form this folder uses, and it owns that rule.
                    "date_prefix": decision["date_prefix"],
                })

        logger.info(
            "ℹ️ archive: run %d — %d mail(s) in the Inbox, %d decided, %d to file, %d skipped",
            run_id, len(mails), len(item_by_message), len(decisions), skipped,
        )
        if decisions:
            result = self._spawn_with_payload("apply", "--decisions", decisions)
            self._record_apply(conn, result, item_by_message)
        scan_error = self._rescan_index() if decisions else None
        if scan_error:
            logger.warning("⚠️ archive: %s", scan_error)
        return finish_run(conn, run_id, status="done", error=scan_error)

    def _decide(self, mail: dict[str, Any]) -> dict[str, Any]:
        """Pick this mail's destination — Step 1: the archiver's own top candidate.

        Step 2 (#158) replaces exactly this method's ranking with the local LLM's;
        everything around it, including ``candidates_json``, is already what that
        needs.
        """
        already = mail.get("already_archived")
        if already:
            return {
                "status": "archived", "apply": False, "chosen_folder": None, "chosen_rank": None,
                "confidence": None, "date_prefix": False, "files": [already],
                "reason": "the archiver's index already has this mail filed — nothing was written",
            }
        candidates = [c for c in mail.get("candidates") or [] if isinstance(c, dict)]
        if not candidates:
            return {
                "status": "needs_review", "apply": False, "chosen_folder": None,
                "chosen_rank": None, "confidence": None, "date_prefix": False, "files": [],
                "reason": "the archiver ranked no folder for this mail",
            }
        top = candidates[0]
        score = float(top.get("score") or 0.0)
        folder = str(top.get("folder_path") or "")
        if not folder:
            return {
                "status": "needs_review", "apply": False, "chosen_folder": None,
                "chosen_rank": None, "confidence": score, "date_prefix": False, "files": [],
                "reason": "the archiver's top candidate names no folder",
            }
        if score < self.threshold:
            return {
                "status": "needs_review", "apply": False, "chosen_folder": folder,
                "chosen_rank": 0, "confidence": score, "date_prefix": bool(top.get("date_prefix")),
                "files": [],
                "reason": f"the best folder scored {score:.2f}, below the "
                          f"{self.threshold:.2f} threshold — left in the Inbox for you",
            }
        return {
            "status": "archived", "apply": True, "chosen_folder": folder, "chosen_rank": 0,
            "confidence": score, "date_prefix": bool(top.get("date_prefix")), "files": [],
            "reason": f"the archiver's top folder at {score:.2f} ≥ the "
                      f"{self.threshold:.2f} threshold",
        }

    @staticmethod
    def _item_fields(mail: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_id": str(mail.get("message_id") or ""),
            "entry_id": str(mail.get("entry_id") or "") or None,
            "subject": str(mail.get("subject") or ""),
            "sender": str(mail.get("sender") or ""),
            "sent_at": str(mail.get("date_sent") or "") or None,
            "attachments": int(mail.get("attachment_count") or 0),
            "candidates_json": json.dumps(mail.get("candidates") or [], ensure_ascii=False),
            "chosen_folder": decision["chosen_folder"],
            "chosen_rank": decision["chosen_rank"],
            "confidence": decision["confidence"],
            "reason": decision["reason"],
            "date_prefix": int(bool(decision["date_prefix"])),
            "files_json": json.dumps(decision["files"], ensure_ascii=False),
            "status": decision["status"],
        }

    def _record_apply(
        self, conn: sqlite3.Connection, result: dict[str, Any], item_by_message: dict[str, int]
    ) -> None:
        """Fold one ``apply`` document back onto the rows it belongs to."""
        for entry in result.get("results") or []:
            if not isinstance(entry, dict):
                continue
            item_id = item_by_message.get(str(entry.get("message_id") or ""))
            if item_id is None:
                logger.warning("⚠️ archive: apply reported a mail this run never decided on")
                continue
            files = [str(f) for f in entry.get("files") or []]
            error = entry.get("error") or None
            if entry.get("ok"):
                update_item(
                    conn, item_id, status="archived", files_json=json.dumps(files, ensure_ascii=False),
                    sequence=str(entry.get("sequence_number") or "") or None,
                    entry_id=str(entry.get("entry_id") or "") or None, error=None,
                )
                continue
            # ``files`` is filled in before the move, so a failure here can still
            # have written to disk — recorded as such, because that is exactly
            # what makes it revertible.
            message = self._apply_error_message(error, files)
            update_item(
                conn, item_id, status="failed",
                files_json=json.dumps(files, ensure_ascii=False),
                sequence=str(entry.get("sequence_number") or "") or None,
                entry_id=str(entry.get("entry_id") or "") or None, error=message,
            )
            logger.warning("⚠️ archive: a mail did not file — %s", message)

    @staticmethod
    def _apply_error_message(error: Any, files: list[str]) -> str:
        code = str((error or {}).get("code", "")) if isinstance(error, dict) else ""
        message = str((error or {}).get("message", "")) if isinstance(error, dict) else ""
        base = f"{code or 'unknown'}: {message}" if message else (code or "the archiver gave no reason")
        if code == "move_failed":
            return f"{base} — the files are on disk and the mail is still in the Inbox"
        if code == "category_failed":
            return f"{base} — the mail is filed and moved, only the Outlook category is missing"
        if files:
            return f"{base} — {len(files)} file(s) were already written"
        return base

    # ------------------------------------------------------- per-mail undo
    def _claim(self) -> None:
        """Take the archiver for one short call (revert / move)."""
        if not self.enabled:
            raise ArchiveError("archive_disabled", self.reason or "batch archiving is off", http_status=409)
        if not self._lock.acquire(blocking=False):
            raise ArchiveError(
                "archive_in_flight",
                "an archiving run is already in progress — one Outlook, one run at a time",
                http_status=409,
            )

    @staticmethod
    def _require(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
        item = get_item(conn, item_id)
        if item is None:
            raise ArchiveError("not_found", f"no archive item {item_id}", http_status=404)
        return item

    @staticmethod
    def _require_revertible(item: dict[str, Any]) -> None:
        """Filed, or failed with files already on disk — the two undoable shapes."""
        if item["status"] in FILED_STATUSES:
            return
        if item["status"] == "failed" and item["files"]:
            return
        raise ArchiveError(
            "archive_bad_state",
            f"archive item {item['id']} is {item['status']} and has no archived file — there is "
            "nothing to undo",
            http_status=409,
        )

    def revert(self, conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
        """Delete this mail's archive files and put it back in the Inbox."""
        item = self._require(conn, item_id)
        self._require_revertible(item)
        self._claim()
        try:
            result = self._revert_once(item)
        finally:
            self._lock.release()
        if not result["ok"]:
            # The row keeps its state on purpose: a partial undo is not a
            # revert, and re-running it is safe (a file already gone comes back
            # as ``missing``, not as an error).
            update_item(conn, item_id, error=result["message"])
            raise ArchiveError("archive_revert_failed", result["message"], http_status=502)
        return update_item(
            conn, item_id, status="reverted", files_json="[]", error=None,
            decided_at=clock.now_iso(),
        )

    def _revert_once(self, item: dict[str, Any]) -> dict[str, Any]:
        """One ``revert`` child call for one item → ``{ok, message, entry}``."""
        doc = self._spawn_with_payload(
            "revert", "--items", [{"message_id": item["message_id"], "files": item["files"]}]
        )
        entry = next((r for r in doc.get("results") or [] if isinstance(r, dict)), None)
        if entry is None:
            return {"ok": False, "message": "the archiver reported no result for this mail", "entry": None}
        if entry.get("ok"):
            return {"ok": True, "message": "", "entry": entry}
        error = entry.get("error") or {}
        code = str(error.get("code", "")) if isinstance(error, dict) else ""
        message = str(error.get("message", "")) if isinstance(error, dict) else ""
        refused = entry.get("refused") or []
        file_errors = entry.get("file_errors") or []
        parts = [f"the archiver could not fully undo this mail ({code or 'no code'})"]
        if message:
            parts.append(message)
        if refused:
            parts.append(f"{len(refused)} file(s) refused as outside the archive roots")
        if file_errors:
            parts.append(f"{len(file_errors)} file(s) could not be deleted")
        return {"ok": False, "message": " — ".join(parts), "entry": entry}

    def move(self, conn: sqlite3.Connection, item_id: int, folder: str) -> dict[str, Any]:
        """Re-file this mail into ``folder``: undo the current filing, then apply again.

        ``folder`` takes a folder ref or an absolute path and is resolved
        through the same placeholders ``POST /api/resolve`` uses, so the phone
        and a second PC can name a folder the way they already do everywhere.
        """
        item = self._require(conn, item_id)
        self._require_revertible(item)
        target = placeholders.resolve(
            placeholders.to_ref(folder, self.placeholders), self.placeholders
        )
        if not target.resolved:
            raise ArchiveError(
                "archive_bad_folder",
                f"{folder!r} does not resolve on this install"
                + (f" (unknown {', '.join(target.unresolved)})" if target.unresolved else ""),
                http_status=422,
            )
        destination = target.path
        if _same_folder(destination, item["chosen_folder"]):
            raise ArchiveError(
                "archive_bad_folder", "this mail is already filed in that folder", http_status=409,
            )
        date_prefix = self._date_prefix_for(item, destination)

        self._claim()
        try:
            undo = self._revert_once(item)
            if not undo["ok"]:
                update_item(conn, item_id, error=undo["message"])
                raise ArchiveError(
                    "archive_revert_failed",
                    f"nothing was moved: {undo['message']}", http_status=502,
                )
            applied = self._spawn_with_payload("apply", "--decisions", [{
                "message_id": item["message_id"], "folder_path": destination,
                "date_prefix": date_prefix,
            }])
        finally:
            self._lock.release()

        entry = next((r for r in applied.get("results") or [] if isinstance(r, dict)), None)
        if entry is None:
            update_item(
                conn, item_id, status="reverted", files_json="[]",
                error="the archiver reported no result for the move; the mail is back in the Inbox",
                decided_at=clock.now_iso(),
            )
            raise ArchiveError(
                "archive_move_failed",
                "the archiver reported no result for the move — the mail is back in the Inbox",
                http_status=502,
            )
        files = [str(f) for f in entry.get("files") or []]
        common = {
            "chosen_folder": destination, "chosen_rank": None, "confidence": None,
            "date_prefix": int(bool(date_prefix)),
            "files_json": json.dumps(files, ensure_ascii=False),
            "sequence": str(entry.get("sequence_number") or "") or None,
            "entry_id": str(entry.get("entry_id") or "") or None,
            "decided_at": clock.now_iso(),
        }
        if entry.get("ok"):
            return update_item(
                conn, item_id, status="moved", error=None,
                reason=f"moved here by hand from {item['chosen_folder'] or 'the Inbox'}", **common,
            )
        message = self._apply_error_message(entry.get("error"), files)
        update_item(conn, item_id, status="failed", error=message, **common)
        raise ArchiveError("archive_move_failed", message, http_status=502)

    @staticmethod
    def _date_prefix_for(item: dict[str, Any], destination: str) -> bool:
        """The naming form the destination uses, per the archiver's own inference.

        ``plan`` reported one per candidate folder; when the destination is one
        of them that value is handed back unchanged. For a folder the plan never
        ranked there is nothing to infer from here — the archiver's rule is
        per-folder and it owns it — so the item's current form is kept, which is
        the closest thing to "what this mail already looked like".
        """
        for candidate in item.get("candidates") or []:
            if isinstance(candidate, dict) and _same_folder(
                str(candidate.get("folder_path") or ""), destination
            ):
                return bool(candidate.get("date_prefix"))
        return bool(item.get("date_prefix"))

    def accept(self, conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
        """Mark a row reviewed — no file moves, nothing written to Outlook.

        Only the two rows that ask for a human (``needs_review``, ``failed``)
        can be accepted: an ``archived`` row is finished, not reviewed, and
        answering 409 there keeps "I have seen this" from silently meaning two
        different things on the screen (#159).
        """
        item = self._require(conn, item_id)
        if item["status"] not in REVIEWABLE_STATUSES:
            raise ArchiveError(
                "archive_bad_state",
                f"archive item {item_id} is {item['status']}, which needs no review",
                http_status=409,
            )
        return update_item(conn, item_id, decided_at=clock.now_iso())


__all__ = [
    "FILED_STATUSES",
    "REVIEWABLE_STATUSES",
    "SUPPORTED_SCHEMA_VERSION",
    "ArchiveBatchService",
    "ArchiveError",
    "create_run",
    "filed_message_ids",
    "finish_run",
    "get_item",
    "get_run",
    "insert_item",
    "list_items",
    "list_runs",
    "update_item",
]
