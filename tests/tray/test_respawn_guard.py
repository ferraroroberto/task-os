"""The tray never stacks a second webapp copy on a slow boot.

A real long-lived child process stands in for the webapp, so liveness is the
guard's own process-identity check rather than a mock of it.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tray import tray as tray_mod
from app.tray.tray import TrayApp
from app.tray.watchdog import RespawnGuard
from src.no_window import NO_WINDOW

_SLEEPER = "import time; time.sleep(120)"


class FakeManager:
    """Stands in for ``WebappManager``: every start spawns one real child."""

    base_url = "http://127.0.0.1:1"
    public_url = base_url
    log_path = Path("webapp.log")

    def __init__(self) -> None:
        self.children: list[subprocess.Popen] = []

    def start(self, wait: bool = True) -> None:
        self.children.append(
            subprocess.Popen([sys.executable, "-c", _SLEEPER], creationflags=NO_WINDOW)
        )

    @property
    def child_pid(self) -> int | None:
        if self.children and self.children[-1].poll() is None:
            return self.children[-1].pid
        return None

    def is_port_in_use(self) -> bool:
        return False

    def is_reachable(self) -> bool:
        return True

    def alive(self) -> list[subprocess.Popen]:
        return [c for c in self.children if c.poll() is None]


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TrayApp]:
    monkeypatch.setattr(tray_mod, "WATCHDOG_LOG", tmp_path / "watchdog.log")
    monkeypatch.setattr(tray_mod, "_notify", lambda *_a, **_k: None)
    tray = TrayApp(SimpleNamespace(port=1, server="hypercorn"), instance=None)  # type: ignore[arg-type]
    tray.manager = FakeManager()  # type: ignore[assignment]
    tray._announce_ready = lambda: None  # type: ignore[method-assign]  # no toast loop in a unit test
    yield tray
    for child in tray.manager.children:  # type: ignore[attr-defined]
        child.kill()
        child.wait(timeout=10)


def test_a_failed_probe_while_the_boot_child_is_starting_does_not_spawn_a_second(app: TrayApp) -> None:
    app._start()
    assert len(app.manager.children) == 1  # type: ignore[attr-defined]

    app._on_wedge(3)  # the probe failed because the child is still importing

    assert len(app.manager.children) == 1  # type: ignore[attr-defined]


def test_a_respawn_past_the_startup_window_stops_the_old_child_first(app: TrayApp) -> None:
    app.guard = RespawnGuard(app.wd_log, startup_window_s=0.0)
    app._start()
    first = app.manager.children[0]  # type: ignore[attr-defined]

    app._on_wedge(3)

    assert first.poll() is not None  # the stuck child is gone ...
    assert len(app.manager.alive()) == 1  # type: ignore[attr-defined]  # ... and one copy remains


def test_a_child_that_already_exited_is_replaced_without_a_stop(app: TrayApp) -> None:
    app._start()
    first = app.manager.children[0]  # type: ignore[attr-defined]
    first.kill()
    first.wait(timeout=10)

    app._on_wedge(3)

    assert len(app.manager.children) == 2  # type: ignore[attr-defined]
    assert len(app.manager.alive()) == 1  # type: ignore[attr-defined]
