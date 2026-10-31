"""One process, one log file.

The tray and the uvicorn child it spawns are two processes. On Windows a
``RotatingFileHandler`` rolls over by renaming its file, which fails while the
other process holds it open, so every record that hits a rollover is dropped.
"""

from __future__ import annotations

import sys
import types

import pytest

import launcher
from src import logger as logmod


@pytest.fixture
def logged(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The ``log_file`` each ``configure_logging`` call of ``launcher.main`` asked for."""
    seen: list[object] = []
    monkeypatch.setattr(logmod, "configure_logging", lambda level=0, log_file=None: seen.append(log_file))
    return seen


def test_the_tray_logs_to_its_own_file(monkeypatch: pytest.MonkeyPatch, logged: list[object]) -> None:
    tray = types.ModuleType("app.tray.tray")
    tray.run_tray = lambda config: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.tray.tray", tray)
    assert launcher.main(["launcher.py", "tray"]) == 0
    assert logged == [logmod.TRAY_LOG_FILE]
    assert logmod.TRAY_LOG_FILE != logmod.LOG_FILE


def test_the_webapp_keeps_the_default_file(monkeypatch: pytest.MonkeyPatch, logged: list[object]) -> None:
    uvicorn = types.ModuleType("uvicorn")
    uvicorn.run = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
    monkeypatch.setattr("src.certs.ensure_cert_fresh", lambda: None)
    monkeypatch.setattr("src.certs.uvicorn_ssl_kwargs", lambda: {})
    assert launcher.main(["launcher.py", "webapp"]) == 0
    assert logged == [None]   # → LOG_FILE, the file docs/access.md points a sign-in review at
