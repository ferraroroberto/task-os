"""The mirror watcher lists the folder when it changed, not on a timer.

The schedule is proven with a fake clock; the real folder signal is proven on a
disposable folder (Windows only — elsewhere the watcher keeps its timer, which
the fake-clock cases cover).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

import pytest

from src import tasks_repo as repo
from src.config import load_config
from src.mirror import Mirror
from tests.test_mirror import _bathroom, _touch, env  # noqa: F401 — the `env` fixture

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the folder signal is Windows-only")


def _schedule_mirror(env, **kw) -> Mirror:  # noqa: F811
    return Mirror(load_config(), poll_s=2.0, sweep_s=60.0, debounce_s=1.0, **kw)


# ------------------------------------------------------------ the schedule


def test_idle_with_a_signal_never_scans_before_the_sweep(env) -> None:  # noqa: F811
    m = _schedule_mirror(env)
    for now in (2.0, 10.0, 30.0, 59.9):
        assert m.scan_due(now, 0.0, True, False) is False
    assert m.scan_due(60.0, 0.0, True, False) is True  # the safety sweep


def test_a_change_scans_within_one_poll_interval(env) -> None:  # noqa: F811
    m = _schedule_mirror(env)
    assert m.scan_due(0.5, 0.0, True, True) is False  # a burst is coalesced into one pass…
    assert m.scan_due(2.0, 0.0, True, True) is True   # …taken no later than the old 2 s cadence
    assert m.wait_s(0.5, 0.0, True, True, None) == pytest.approx(1.5)


def test_without_a_signal_it_polls_like_before(env) -> None:  # noqa: F811
    m = _schedule_mirror(env)
    assert m.scan_due(1.9, 0.0, False, False) is False
    assert m.scan_due(2.0, 0.0, False, False) is True
    assert m.wait_s(0.0, 0.0, False, False, None) == pytest.approx(2.0)


def test_idle_sleep_is_the_sweep_and_a_pending_export_wakes_it_for_the_debounce(env) -> None:  # noqa: F811
    m = _schedule_mirror(env)
    assert m.wait_s(5.0, 0.0, True, False, None) == pytest.approx(55.0)
    assert m.wait_s(5.0, 0.0, True, False, 5.0) == pytest.approx(1.0)
    assert m.wait_s(100.0, 0.0, True, False, None) == 0.0  # overdue, never negative


# ----------------------------------------------------- the real folder signal


def _wait_for(cond: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@windows_only
def test_an_idle_folder_is_not_listed_and_an_edit_is_still_imported(env) -> None:  # noqa: F811
    # poll_s 0.2 s: the old timer would list the folder five times a second of idleness.
    m = Mirror(load_config(), db_path=env["db"], poll_s=0.2, sweep_s=600.0)
    m.start()
    try:
        assert _wait_for(lambda: m.status(env["conn"])["files"], 10), "initial export never landed"
        time.sleep(0.8)  # let the start-up writes' own signal drain
        settled = m.scans
        time.sleep(1.5)
        assert m.scans == settled, "an unchanged folder was listed"

        tid, path = _bathroom(env)
        _touch(path, path.read_text(encoding="utf-8").replace("\ncode: null\n", "\ncode: BATH\n"))
        assert _wait_for(lambda: repo.get_task(env["conn"], tid)["code"] == "BATH", 5), "edit not imported"
        assert m.scans > settled
    finally:
        m.stop()


@windows_only
def test_the_safety_sweep_still_reads_an_edit_made_without_a_signal(env) -> None:  # noqa: F811
    m = Mirror(load_config(), db_path=env["db"], poll_s=0.2, sweep_s=0.5)
    m.start()
    try:
        assert _wait_for(lambda: m.status(env["conn"])["files"], 10)
        time.sleep(0.8)
        settled = m.scans
        assert _wait_for(lambda: m.scans > settled, 3), "the sweep never ran"
    finally:
        m.stop()
