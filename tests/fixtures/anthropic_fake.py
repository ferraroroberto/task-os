"""Tiny Anthropic Messages server for hermetic task-os AI tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Responder = Callable[[dict[str, Any]], str]


class _Server(ThreadingHTTPServer):
    requests: list[dict[str, Any]]
    responder: Responder


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler contract
        if self.path.rstrip("/") != "/v1/messages":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.server.requests.append(body)  # type: ignore[attr-defined]
        text = self.server.responder(body)  # type: ignore[attr-defined]
        payload = json.dumps({
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": body.get("model", "fake"),
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class FakeAnthropic:
    def __init__(self, responder: Responder) -> None:
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.requests = []
        self.server.responder = responder
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.server.requests

    def __enter__(self) -> FakeAnthropic:
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
