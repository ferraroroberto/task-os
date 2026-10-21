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

``stop()`` closes the connections it is still serving (see
:class:`tests.fixtures.loopback_fake.LoopbackFake`): ``src.enrich`` posts
through ``src.pooled_http``'s keep-alive session (#185).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from tests.fixtures.loopback_fake import LoopbackFake

CHAT_PATH = "/v1/chat/completions"


class FakeChat(LoopbackFake):
    """A threaded loopback HTTP server speaking the chat-completions shape."""

    PATH = CHAT_PATH

    def __init__(
        self, *, content: str = "{}", status: int = 200, body: bytes | None = None,
        served_model: str | None = None,
    ) -> None:
        super().__init__()
        self.content = content
        self.status = status
        #: Overrides the whole JSON answer (a gateway's HTML error page, say).
        self.body = body
        #: What the hub's ``x-hub-served-model`` header says, when it says
        #: anything — the breadcrumb that answers "which model actually ran".
        self.served_model = served_model
        self._start(self._answer)

    def _answer(self, handler: BaseHTTPRequestHandler) -> None:
        raw = self.read_body(handler)
        try:
            sent = json.loads(raw)
        except ValueError:
            sent = {"_unparseable": raw.decode("utf-8", errors="replace")}
        self.requests.append({"path": handler.path, **sent})
        if self.body is not None:
            payload = self.body
        else:
            payload = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": self.content}}],
            }).encode("utf-8")
        extra = {"x-hub-served-model": self.served_model} if self.served_model else None
        self.respond(handler, self.status, payload, extra)

    def says(self, **fields: Any) -> None:
        """Set the reply to one clean JSON object — the ordinary happy path."""
        self.content = json.dumps(fields)
