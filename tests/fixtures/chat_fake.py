"""A chat-endpoint stand-in — the route and the shapes, none of the model (#147).

Speaks the OpenAI chat-completions shape the hub exposes on ``:8000``, so
:class:`src.enrich.EnrichClient` does its real JSON build, its real pooled
POST and its real answer parse against a loopback port — only the model is
imaginary. Same isolation, and the same reason, as
``tests.fixtures.whisper_fake.FakeWhisper``: the suite must never depend on
whether the fleet's hub happens to be running on the machine executing it
(``tests/conftest`` blanks ``enrich.url`` for exactly that), and it must never
send a line of anybody's text anywhere real.

    with FakeChat(content='{"title": "Call the plumber", "description": ""}') as chat:
        client = EnrichClient(config_with(chat.url))
        assert client.fields("…", today=date(2026, 9, 7))["title"] == "Call the plumber"
        assert chat.requests[-1]["model"] == "agentic_light_nothink"

``content`` is what the assistant message says, verbatim — the point of most
of these tests is what happens to a reply that is *not* clean JSON, so it is
never wrapped or tidied on the way out. ``status`` / ``body`` / ``content``
are settable between calls so one test can walk the endpoint answering,
refusing and going away.

**``stop()`` closes the connections it is still serving**, for the same reason
``FakeWhisper.stop()`` does: ``src.enrich`` posts through
``src.pooled_http``'s keep-alive session (#185), so closing only the listening
socket would leave a handler thread answering the socket the pool kept — the
endpoint would look *up* after the test had taken it away.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CHAT_PATH = "/v1/chat/completions"


class FakeChat:
    """A threaded loopback HTTP server speaking the chat-completions shape."""

    def __init__(
        self, *, content: str = "{}", status: int = 200, body: bytes | None = None,
        served_model: str | None = None,
    ) -> None:
        self.content = content
        self.status = status
        #: Overrides the whole JSON answer (a gateway's HTML error page, say).
        self.body = body
        #: What the hub's ``x-hub-served-model`` header says, when it says
        #: anything — the breadcrumb that answers "which model actually ran".
        self.served_model = served_model
        self.requests: list[dict[str, Any]] = []
        #: The sockets currently being served, so stop() can close them.
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

            def do_POST(self) -> None:            # noqa: N802 — BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length)
                try:
                    sent = json.loads(raw)
                except ValueError:
                    sent = {"_unparseable": raw.decode("utf-8", errors="replace")}
                fake.requests.append({"path": self.path, **sent})
                if fake.body is not None:
                    payload = fake.body
                else:
                    payload = json.dumps({
                        "choices": [{"message": {"role": "assistant", "content": fake.content}}],
                    }).encode("utf-8")
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                if fake.served_model:
                    self.send_header("x-hub-served-model", fake.served_model)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                """Silence: pytest's captured output is for the test, not this."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def says(self, **fields: Any) -> None:
        """Set the reply to one clean JSON object — the ordinary happy path."""
        self.content = json.dumps(fields)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{CHAT_PATH}"

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

    def __enter__(self) -> FakeChat:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
