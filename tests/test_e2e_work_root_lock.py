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
