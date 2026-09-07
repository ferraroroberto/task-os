"""A transcription-endpoint stand-in — the route and the shapes, none of the model (#92).

Speaks the OpenAI audio shape the hub (:8000) and whisper-server (:8090) share,
so it stands in for either. The suite must never depend on whether the fleet's
real ones happen to be running on the machine executing it (``tests/conftest`` blanks
both ``voice`` endpoints for exactly that reason), and it must never post audio
anywhere real. This is the isolation the issue provider's ``src/issues/fake.py``
gives the sync: a genuine HTTP endpoint on a loopback port, so the code under
test does its real multipart build, its real ``urllib`` POST and its real
response parse — only the model is imaginary.

    with FakeWhisper(text="buy a filter next week") as whisper:
        client = VoiceClient(config_with(whisper.url))
        assert client.transcribe(WAV) == "buy a filter next week"
        assert whisper.requests[-1]["filename"] == "clip.wav"

``status`` / ``text`` / ``body`` are settable between calls so one test can
walk the endpoint answering, refusing and going away.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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


class FakeWhisper:
    """A threaded loopback HTTP server speaking whisper-server's answer shape."""

    def __init__(self, *, text: str = "", status: int = 200, body: bytes | None = None) -> None:
        self.text = text
        self.status = status
        #: Overrides the JSON answer entirely (whisper's own refusal is the
        #: plain-text ``Invalid request``, not JSON — see src/voice.py).
        self.body = body
        self.requests: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:            # noqa: N802 — BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length)
                content_type = self.headers.get("Content-Type", "")
                record = {"path": self.path, "content_type": content_type, "length": length}
                record.update(parse_multipart(raw, content_type))
                fake.requests.append(record)
                if fake.body is not None:
                    payload = fake.body
                else:
                    payload = json.dumps({"text": fake.text}).encode("utf-8")
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                """Silence: pytest's captured output is for the test, not this."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{INFERENCE_PATH}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> FakeWhisper:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
