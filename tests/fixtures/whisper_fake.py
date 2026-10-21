"""A transcription-endpoint stand-in — the route and the shapes, none of the model (#92).

Speaks the OpenAI audio shape the hub (:8000) and whisper-server (:8090) share,
so it stands in for either. The suite must never depend on whether the fleet's
real ones happen to be running on the machine executing it (``tests/conftest`` blanks
both ``voice`` endpoints for exactly that reason), and it must never post audio
anywhere real. This is the isolation the issue provider's ``src/issues/fake.py``
gives the sync: a genuine HTTP endpoint on a loopback port, so the code under
test does its real multipart build, its real pooled POST and its real
response parse — only the model is imaginary.

    with FakeWhisper(text="buy a filter next week") as whisper:
        client = VoiceClient(config_with(whisper.url))
        assert client.transcribe(WAV) == "buy a filter next week"
        assert whisper.requests[-1]["filename"] == "clip.wav"

``status`` / ``text`` / ``body`` are settable between calls so one test can
walk the endpoint answering, refusing and going away.

``stop()`` closes the connections it is still serving (see
:class:`tests.fixtures.loopback_fake.LoopbackFake`): ``src.pooled_http`` holds
keep-alive sockets open between posts (#185).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from tests.fixtures.loopback_fake import LoopbackFake

INFERENCE_PATH = "/v1/audio/transcriptions"


def parse_multipart(body: bytes, content_type: str) -> dict[str, Any]:
    """The bits of a ``multipart/form-data`` body these tests assert on.

    Deliberately small — ``{fields, filename, file_content_type, file}`` — and
    deliberately hand-rolled: the point is to read back exactly what
    ``src.voice.build_multipart`` produced, not to be a general parser.
    """
    marker = "boundary="
    boundary = content_type.split(marker, 1)[1].strip() if marker in content_type else ""
    out: dict[str, Any] = {"fields": {}, "filename": None, "file_content_type": None, "file": b""}
    if not boundary:
        return out
    for part in body.split(f"--{boundary}".encode()):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, payload = part.partition(b"\r\n\r\n")
        headers = head.decode("latin-1")
        name = _quoted(headers, 'name="')
        if not name:
            continue
        if 'filename="' in headers:
            out["filename"] = _quoted(headers, 'filename="')
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-type:"):
                    out["file_content_type"] = line.split(":", 1)[1].strip()
            out["file"] = payload
        else:
            out["fields"][name] = payload.decode("utf-8", errors="replace")
    return out


def _quoted(headers: str, prefix: str) -> str | None:
    if prefix not in headers:
        return None
    return headers.split(prefix, 1)[1].split('"', 1)[0]


class FakeWhisper(LoopbackFake):
    """A threaded loopback HTTP server speaking whisper-server's answer shape."""

    PATH = INFERENCE_PATH

    def __init__(self, *, text: str = "", status: int = 200, body: bytes | None = None) -> None:
        super().__init__()
        self.text = text
        self.status = status
        #: Overrides the JSON answer entirely (whisper's own refusal is the
        #: plain-text ``Invalid request``, not JSON — see src/voice.py).
        self.body = body
        self._start(self._answer)

    def _answer(self, handler: BaseHTTPRequestHandler) -> None:
        raw = self.read_body(handler)
        content_type = handler.headers.get("Content-Type", "")
        record = {
            "path": handler.path, "content_type": content_type, "length": len(raw),
            #: The client's (host, port) — two posts over one keep-alive
            #: connection share it, two fresh connections do not (#185).
            "peer": handler.client_address,
        }
        record.update(parse_multipart(raw, content_type))
        self.requests.append(record)
        payload = self.body if self.body is not None else json.dumps({"text": self.text}).encode("utf-8")
        self.respond(handler, self.status, payload)
