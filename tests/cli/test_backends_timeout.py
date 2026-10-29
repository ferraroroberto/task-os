"""The CLI-over-HTTP transport's read bound: named, verb-dependent, and a
read timeout is reported distinct from an unreachable server."""

from __future__ import annotations

from typing import Any

import pytest

from src.cli_support import backends


class _FakeHTTPResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def test_default_timeout_for_an_ordinary_route(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float | None = None, context: Any = None) -> _FakeHTTPResponse:
        seen["timeout"] = timeout
        return _FakeHTTPResponse(200, b"{}")

    monkeypatch.setattr(backends.urllib.request, "urlopen", fake_urlopen)
    send = backends._urllib_transport("http://127.0.0.1:8448", None)
    send("GET", "/api/tasks", None)
    assert seen["timeout"] == backends._DEFAULT_TIMEOUT_SECONDS


@pytest.mark.parametrize("path", sorted(backends._LONG_TIMEOUT_PATHS))
def test_long_timeout_for_slow_verbs(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float | None = None, context: Any = None) -> _FakeHTTPResponse:
        seen["timeout"] = timeout
        return _FakeHTTPResponse(200, b"{}")

    monkeypatch.setattr(backends.urllib.request, "urlopen", fake_urlopen)
    send = backends._urllib_transport("http://127.0.0.1:8448", None)
    send("POST", path, {})
    assert seen["timeout"] == backends._LONG_TIMEOUT_SECONDS


def test_a_read_timeout_is_reported_as_timeout_not_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float | None = None, context: Any = None) -> _FakeHTTPResponse:
        raise TimeoutError("timed out")

    monkeypatch.setattr(backends.urllib.request, "urlopen", fake_urlopen)
    send = backends._urllib_transport("http://127.0.0.1:8448", None)
    with pytest.raises(backends.CliError) as excinfo:
        send("POST", "/api/ai/triage", {})
    assert excinfo.value.code == "timeout"
    assert "still" in str(excinfo.value).lower()


def test_connection_refused_is_still_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float | None = None, context: Any = None) -> _FakeHTTPResponse:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(backends.urllib.request, "urlopen", fake_urlopen)
    send = backends._urllib_transport("http://127.0.0.1:8448", None)
    with pytest.raises(backends.CliError) as excinfo:
        send("GET", "/api/status", None)
    assert excinfo.value.code == "unreachable"
