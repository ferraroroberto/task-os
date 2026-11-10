"""A stand-in for folder-explorer's v1 search API — never a real mailbox or folder index.

:class:`FakeFolderExplorer` is a real ``ThreadingHTTPServer`` on a loopback port
answering ``/api/v1/search/{status,folders,emails}`` in the documented shapes
(``docs/service-api.md`` in folder-explorer), so the client under test does its
real GET and its real parse; only the data is imaginary. Each part has its own
state (``ok`` · ``not-configured`` · ``indexing`` · ``error``) and ``mode``
picks a failure the client has to tell apart:

``ok``        answer from the state and the data
``garbled``   ``200`` with a page that is not JSON
``bare422``   ``422`` with FastAPI's validation body (no envelope)
``v2``        an envelope claiming ``schema_version`` 2
``mystery``   an envelope with a state the contract does not name

``stop()`` closes the connections it still serves (like :mod:`.loopback_fake`),
so a stopped fake reads as folder-explorer *down* to a pooled client.

Used in-process by ``tests/search`` and, from the pytest process, by the e2e
stories' disposable instances.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from tests.fixtures.emails_fixture import EMAILS

MARK_START, MARK_END = "", ""
_HTTP = {"ok": 200, "not-configured": 503, "indexing": 503, "error": 500, "failed": 500}


def fixture_mails(root: Path) -> list[dict[str, Any]]:
    """The six synthetic mails of ``emails_fixture`` as v1 hits; their ``.msg`` paths sit under ``root``."""
    out: list[dict[str, Any]] = []
    for i, (rel_folder, filename, subject, sender, recipients, date_sent, body) in enumerate(EMAILS, start=1):
        name, _, addr = sender.partition(" <")
        folder = str(Path(root) / rel_folder)
        out.append({
            "id": i, "subject": subject, "from_name": name if addr else "", "from_addr": addr.rstrip(">") if addr else sender,
            "recipients": recipients, "date": date_sent + "+02:00", "folder": folder,
            "path": str(Path(folder) / filename), "filename": filename, "snippet": body,
            "flagged": False, "attachments": 0, "size": 1000 + i,
        })
    return out


def folders_under(root: Path) -> list[str]:
    """Every directory under ``root`` (and ``root``), as the paths a scan would list."""
    root = Path(root)
    return [str(root)] + [str(p) for p in sorted(root.rglob("*")) if p.is_dir()]


class FakeFolderExplorer:
    def __init__(self, *, folders: list[str] | None = None, emails: list[dict[str, Any]] | None = None) -> None:
        self.folders = list(folders or [])
        self.emails = list(emails or [])
        self.state = {"folders": ("ok", None), "emails": ("ok", None)}
        self.mode = "ok"
        self.requests: list[str] = []
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
                fake.requests.append(self.path)
                status, body = fake._answer(self.path)
                payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if not isinstance(body, bytes) else "text/html")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                """Silence: pytest's captured output is for the test, not this."""

        class Server(ThreadingHTTPServer):
            def handle_error(self, request: Any, client_address: Any) -> None:
                """A client that went away (or was cut off by stop()) is not worth a traceback in the test log."""

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def set_state(self, part: str, state: str, reason: str | None = None) -> None:
        self.state[part] = (state, reason)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        for conn in list(self._live):
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # ------------------------------------------------------------ answers

    def _answer(self, raw: str) -> tuple[int, Any]:
        if self.mode == "garbled":
            return 200, b"<html>sign in</html>"
        if self.mode == "bare422":
            return 422, {"detail": [{"loc": ["query", "limit"], "msg": "out of range"}]}
        parts = urlsplit(raw)
        q = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        route = parts.path.rsplit("/", 1)[-1]
        if route == "status":
            return 200, self._envelope("ok", None, folders=self._part("folders"), emails=self._part("emails"))
        if route not in ("folders", "emails"):
            return 404, {"detail": "Not Found"}
        state, reason = self.state[route]
        empty = {"results": [], "total": 0} if route == "folders" else {"hits": [], "total": 0}
        if state != "ok":
            return _HTTP[state], self._envelope(state, reason, query=q.get("q", ""), **empty)
        words = [w.lower() for w in q.get("q", "").replace(";", " ").split()]
        limit = int(q.get("limit", "30"))
        if route == "folders":
            hits = [self._folder(p) for p in self.folders if words and all(w in p.lower() for w in words)][:limit]
            return 200, self._envelope("ok", None, query=q.get("q", ""), results=hits, total=len(hits), truncated=False,
                                       needs_rescan=[], missing=[], page="/#search?mode=folders")
        hits = [self._mark(m, words) for m in self.emails if words and all(w in self._text(m) for w in words)]
        hits.sort(key=lambda h: 0 if any(w in h["subject"].replace(MARK_START, "").lower() for w in words) else 1)
        return 200, self._envelope("ok", None, query=q.get("q", ""), hits=hits[:limit], total=len(hits), notes=[],
                                   facets=None, marks={"start": MARK_START, "end": MARK_END}, page="/#search?mode=emails")

    def _envelope(self, state: str, reason: str | None, **fields: Any) -> dict[str, Any]:
        if self.mode == "mystery":
            state = "melting"
        return {"schema_version": 2 if self.mode == "v2" else 1, "state": state, "reason": reason, **fields}

    def _part(self, part: str) -> dict[str, Any]:
        state, reason = self.state[part]
        extra = ({"roots": 1, "scanned": 1, "scanning": False} if part == "folders" else {"count": len(self.emails)}) \
            if state == "ok" else {}
        return {"state": state, "reason": reason, **extra}

    @staticmethod
    def _text(m: dict[str, Any]) -> str:
        return " ".join(str(m.get(k) or "") for k in ("subject", "from_name", "from_addr", "recipients", "snippet")).lower()

    @staticmethod
    def _folder(path: str) -> dict[str, Any]:
        name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        return {"root": "d", "root_name": "D:", "kind": "local", "id": 1, "name": name, "path": path,
                "depth": path.replace("\\", "/").rstrip("/").count("/"), "score": 1.0, "size": 0, "files": 0, "people": 0}

    @staticmethod
    def _mark(m: dict[str, Any], words: list[str]) -> dict[str, Any]:
        def mark(text: str) -> str:
            low = text.lower()
            out, i = "", 0
            while i < len(text):
                hit = next((w for w in sorted(words, key=len, reverse=True) if low.startswith(w, i)), None)
                if hit:
                    out += MARK_START + text[i:i + len(hit)] + MARK_END
                    i += len(hit)
                else:
                    out += text[i]
                    i += 1
            return out
        return {**m, "subject": mark(m["subject"]), "snippet": mark(m["snippet"])}
