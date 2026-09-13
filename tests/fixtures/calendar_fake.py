"""A stand-in for a private ICS address (#96) — never a real calendar.

:class:`FakeCalendar` serves one of the synthetic feeds in
``tests/fixtures/calendar/`` on a loopback port, under a path shaped like a
real private address (``/calendar/ical/<secret>/basic.ics``) so the redaction
tests have a secret to look for. ``mode`` picks what the next request gets,
one per failure the lane has to tell apart:

``ok``      the feed (``feed`` names the file)
``404``     ``HTTP 404`` — an address that was revoked or mistyped
``500``     ``HTTP 500`` — a server that is there and failing
``html``    ``200`` with a sign-in page — an answer that is not a calendar
``slow``    the feed, after ``delay_s`` of silence — a server that hangs
``drop``    the connection closed before any response — a dead link

Used in-process by ``tests/test_calendar.py`` and, from the pytest process,
by story 28's disposable instance.
"""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "calendar"
#: The part of the address that must never reach a status, an error or a log.
SECRET = "s3cr3t-7f9d2c41b8e0a6"
PATH = f"/calendar/ical/{SECRET}/basic.ics"


class FakeCalendar:
    def __init__(self, *, mode: str = "ok", feed: str = "day.ics", delay_s: float = 3.0) -> None:
        self.mode = mode
        self.feed = feed
        self.delay_s = delay_s
        self.requests = 0
        self._live: set[socket.socket] = set()
        self._stopping = threading.Event()
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
                fake.requests += 1
                mode = fake.mode
                if mode == "drop":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                if mode == "slow":
                    fake._stopping.wait(fake.delay_s)
                if mode in ("404", "500"):
                    self._send(int(mode), b"not here", "text/plain")
                elif mode == "html":
                    self._send(200, (FIXTURES / "not_a_calendar.html").read_bytes(), "text/html")
                else:
                    self._send(200, (FIXTURES / fake.feed).read_bytes(), "text/calendar; charset=utf-8")

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass   # the client gave up first (the slow mode's whole point)

            def log_message(self, *args: Any) -> None:
                """Silence: pytest's captured output is for the test, not this."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}{PATH}"

    def stop(self) -> None:
        self._stopping.set()
        self._server.shutdown()
        self._server.server_close()
        for sock in list(self._live):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                sock.close()
        self._live.clear()
        self._thread.join(timeout=5)

    def __enter__(self) -> FakeCalendar:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def closed_port_url() -> str:
    """An address on a loopback port nothing listens on — refused at once."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    time.sleep(0.05)
    return f"http://127.0.0.1:{port}{PATH}"
