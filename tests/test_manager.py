"""``app/webapp/manager.py`` — a webapp that dies at boot leaves its traceback in a file (#375)."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from app.webapp import manager as mgr
from app.webapp.manager import WebappManager, WebappManagerConfig, _open_child_log


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_a_child_that_dies_at_boot_leaves_its_traceback_and_the_error_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mgr, "ensure_cert_fresh", lambda _python: None)
    log = tmp_path / "webapp" / "webapp.log"
    m = WebappManager(
        WebappManagerConfig(port=_free_port(), startup_timeout_seconds=15.0, poll_interval_seconds=0.05),
        log_path=log,
    )
    boom = "import sys; print('boom to stdout'); sys.stderr.write('Traceback: boom to stderr\\n'); sys.exit(3)"
    monkeypatch.setattr(m, "_build_command", lambda: [sys.executable, "-c", boom])

    with pytest.raises(RuntimeError, match="exited before becoming ready") as exc_info:
        m.start()

    assert str(log) in str(exc_info.value)
    text = log.read_text(encoding="utf-8")
    assert "boom to stdout" in text and "Traceback: boom to stderr" in text


def test_the_child_log_rolls_once_past_its_cap_and_survives_an_unwritable_path(tmp_path: Path) -> None:
    log = tmp_path / "webapp.log"
    log.write_bytes(b"x" * 50)
    handle = _open_child_log(log, max_bytes=10)
    assert handle is not None
    handle.close()
    assert (tmp_path / "webapp.log.1").read_bytes() == b"x" * 50
    assert log.read_text(encoding="utf-8").startswith("\n--- webapp start ")

    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    assert _open_child_log(blocker / "webapp.log") is None   # discarded, not fatal
