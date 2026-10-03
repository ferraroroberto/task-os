"""The e2e suite's work-root lock (#244), proven without a browser.

``tests/e2e/_work_root_lock.py`` keeps two checkouts' e2e runs from sharing
the one fixed work root at the same time. These tests take the lock in a
temp directory, never the real ``taskos-e2e`` root, so they cannot collide
with an e2e run in progress on this machine. The holders are real child
processes, because the promise is about *other* processes: a live one blocks
and is named, and a killed one blocks nothing.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e._work_root_lock import LOCK_NAME, WorkRootBusy, acquire, read_holder

REPO_ROOT = Path(__file__).resolve().parents[1]

_HOLDER = (
    "import os, sys, time\n"
    "from pathlib import Path\n"
    "from tests.e2e._work_root_lock import acquire\n"
    "acquire(Path(sys.argv[1]), Path(sys.argv[2]))\n"
    "print('held', os.getpid(), flush=True)\n"
    "time.sleep(120)\n"
)


class Holder:
    """A child process holding the lock. ``pid`` is the interpreter that took it
    — on Windows the venv's ``python.exe`` is a redirector that runs the real
    interpreter as *its* child, so ``Popen.pid`` is not that process."""

    def __init__(self, proc: subprocess.Popen, pid: int) -> None:
        self.proc = proc
        self.pid = pid

    def kill(self) -> None:
        """Die the way a killed run dies: no release, no cleanup, no finally."""
        os.kill(self.pid, getattr(signal, "SIGKILL", signal.SIGTERM))  # TerminateProcess on Windows
        self.proc.wait(timeout=10)


def _hold(root: Path, checkout: str) -> Holder:
    """A child process that takes the lock, says so, and keeps it."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(root), checkout],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    said = (proc.stdout.readline() if proc.stdout else "").split()
    if len(said) != 2 or said[0] != "held":
        proc.kill()
        pytest.fail(f"holder process never took the lock (said {said!r}, exit {proc.poll()})")
    return Holder(proc, int(said[1]))


@pytest.fixture
def holders() -> Iterator[list[Holder]]:
    held: list[Holder] = []
    yield held
    for holder in held:
        if holder.proc.poll() is None:
            holder.kill()
        if holder.proc.stdout:
            holder.proc.stdout.close()


def test_a_live_run_in_another_checkout_refuses_the_second_and_is_named(
        tmp_path: Path, holders: list[Holder]) -> None:
    holders.append(_hold(tmp_path, "E:/checkouts/task-os-wt-1"))
    other = str(Path("E:/checkouts/task-os-wt-1"))

    with pytest.raises(WorkRootBusy) as refused:
        acquire(tmp_path, Path("E:/checkouts/task-os"))

    assert refused.value.holder is not None
    assert refused.value.holder["pid"] == holders[0].pid
    assert refused.value.holder["checkout"] == other
    message = str(refused.value)
    assert f"checkout {other}" in message
    assert f"pid {holders[0].pid}" in message
    assert "nothing was booted" in message


def test_a_killed_run_leaves_no_lock_behind(tmp_path: Path, holders: list[Holder]) -> None:
    holder = _hold(tmp_path, "E:/checkouts/task-os-wt-1")
    holders.append(holder)
    holder.kill()
    # Its record is still on disk — only the OS lock is gone.
    assert read_holder(tmp_path / LOCK_NAME)["pid"] == holder.pid

    lock = acquire(tmp_path, Path("E:/checkouts/task-os"))
    try:
        record = json.loads((tmp_path / LOCK_NAME).read_text(encoding="utf-8"))
        assert record["pid"] == os.getpid()
        assert record["checkout"] == str(Path("E:/checkouts/task-os"))
    finally:
        lock.release()


def test_release_frees_the_root_and_clears_the_record(tmp_path: Path) -> None:
    first = acquire(tmp_path, Path("E:/checkouts/task-os"))
    first.release()
    first.release()                    # idempotent: the fixture's finally may run after a failure
    assert read_holder(tmp_path / LOCK_NAME) is None

    second = acquire(tmp_path, Path("E:/checkouts/task-os-wt-2"))
    second.release()


# ------------------------------------------------ under pytest-xdist (#288)

_BOOT_HOLDER = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "from tests.e2e._work_root_lock import boot_lock\n"
    "with boot_lock(Path(sys.argv[1])):\n"
    "    print('booting', flush=True)\n"
    "    time.sleep(1.5)\n"
)


def test_a_second_worker_waits_for_the_boot_slot(tmp_path: Path) -> None:
    """Two workers never pick-and-bind a port at once: the second waits its turn."""
    import time

    from tests.e2e._work_root_lock import boot_lock

    proc = subprocess.Popen(
        [sys.executable, "-c", _BOOT_HOLDER, str(tmp_path)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        assert proc.stdout and proc.stdout.readline().strip() == "booting"
        started = time.monotonic()
        with boot_lock(tmp_path, timeout=30):
            waited = time.monotonic() - started
        assert waited >= 0.5, f"the second boot did not wait for the first ({waited:.2f}s)"
        # …and once the holder is gone the slot is free at once
        proc.wait(timeout=10)
        started = time.monotonic()
        with boot_lock(tmp_path, timeout=5):
            pass
        assert time.monotonic() - started < 1.0
    finally:
        if proc.poll() is None:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()


def test_a_boot_slot_that_never_frees_times_out_loudly(tmp_path: Path) -> None:
    from tests.e2e._work_root_lock import boot_lock

    proc = subprocess.Popen(
        [sys.executable, "-c", _BOOT_HOLDER, str(tmp_path)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        assert proc.stdout and proc.stdout.readline().strip() == "booting"
        with pytest.raises(TimeoutError, match="no instance boot slot"):
            with boot_lock(tmp_path, timeout=0.3):
                pass
    finally:
        proc.kill()
        if proc.stdout:
            proc.stdout.close()


def test_only_the_session_controller_holds_the_work_root() -> None:
    """The controller takes the root; an xdist worker (``workerinput``) and a
    collect-only run (nothing boots) never do."""
    from types import SimpleNamespace

    from tests.e2e.conftest import holds_work_root

    plain = SimpleNamespace(option=SimpleNamespace(collectonly=False))
    assert holds_work_root(plain) is True
    worker = SimpleNamespace(option=SimpleNamespace(collectonly=False), workerinput={"workerid": "gw0"})
    assert holds_work_root(worker) is False
    collecting = SimpleNamespace(option=SimpleNamespace(collectonly=True))
    assert holds_work_root(collecting) is False


def test_worker_names_only_exist_under_xdist(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.e2e.conftest import worker_suffix

    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert worker_suffix() == ""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    assert worker_suffix() == "-gw3"
