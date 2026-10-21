"""The loopback HTTP server both model stand-ins (:mod:`.chat_fake`, :mod:`.whisper_fake`) share.

A fake endpoint is a real ``ThreadingHTTPServer`` on a loopback port, so the
code under test does its real build, its real pooled POST and its real parse —
only the model is imaginary. A subclass sets :attr:`PATH` and passes
:meth:`_start` the function that answers one POST.

**``stop()`` closes the connections it is still serving**, not just the
listening socket. ``src.pooled_http`` holds keep-alive sockets open between
posts (#185) and the handler speaks HTTP/1.1, so a bare ``shutdown()`` leaves a
handler thread happily answering the socket the pool kept — the endpoint would
look *up* to the code under test after the test had taken it away. A real
endpoint going away closes its connections; so does this one.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self


class LoopbackFake:
    """Base for a threaded loopback endpoint that records what it was sent."""

    #: The route :attr:`url` points at.
    PATH = "/"

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        #: The sockets currently being served, so stop() can close them.
        self._live: set[socket.socket] = set()

    def _start(self, post: Callable[[BaseHTTPRequestHandler], None]) -> None:
        """Bind a free loopback port and answer every POST with ``post(handler)``."""
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                fake._live.add(self.connection)

            def finish(self) -> None:
                fake._live.discard(self.connection)
                super().finish()

            def do_POST(self) -> None:            # noqa: N802 — BaseHTTPRequestHandler's name
                post(self)

            def log_message(self, *args: Any) -> None:
                """Silence: pytest's captured output is for the test, not this."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @staticmethod
    def read_body(handler: BaseHTTPRequestHandler) -> bytes:
        length = int(handler.headers.get("Content-Length", "0") or 0)
        return handler.rfile.read(length)

    @staticmethod
    def respond(
        handler: BaseHTTPRequestHandler, status: int, payload: bytes, headers: dict[str, str] | None = None,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(payload)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.PATH}"

    def stop(self) -> None:
        """Gone: the listener closed *and* every connection still open dropped."""
        self._server.shutdown()
        self._server.server_close()
        for sock in list(self._live):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:              # already dead — nothing left to close
                pass
            finally:
                sock.close()
        self._live.clear()
        self._thread.join(timeout=5)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
