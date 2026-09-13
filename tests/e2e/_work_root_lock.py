"""One e2e run at a time over the suite's shared work root (#244).

``E2E_WORK_ROOT`` is a fixed directory under the system temp dir (#134), so it
is per *machine*, not per checkout: the primary checkout and a
``task-os-wt-<N>`` worktree running ``pytest tests/e2e`` at the same time would
boot their instances in the same folders, and ``e2e_workdir()`` clears a
folder before every boot — the second run deleting the first one's files
mid-story. A per-checkout root would avoid that too, but it changes the paths
stories 09 and 10 put on screen. So instead a run holds this lock for its whole
session, and a second one stops before booting anything, naming the checkout
that holds it.

The lock is an OS lock on an open handle, not a "does the file exist" marker:
the kernel drops it the moment the holding process dies, however it died, so a
killed run never leaves a lock behind that blocks the next one — no PID
liveness check, no PID-reuse false positive, no two runs racing to delete the
same stale file. The file itself only carries the holder record (PID, checkout,
start time) for the refusal message. It is emptied on release and never
deleted: deleting a lock file another run has just opened would, on POSIX,
leave that run locking an unlinked file while a third locks a new one.

Stdlib only; ``msvcrt`` on Windows, ``fcntl`` elsewhere.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

LOCK_NAME = ".run.lock"

#: Where the Windows byte-range lock sits. A Windows lock is mandatory — reading
#: a locked byte fails — so it is taken far past anything the holder record
#: will ever grow to, leaving the record readable by the run it refuses.
#: Locking beyond end-of-file is allowed there.
_WIN_LOCK_OFFSET = 1 << 20


class WorkRootBusy(RuntimeError):
    """Another live run holds the work root."""

    def __init__(self, lock_path: Path, holder: dict | None) -> None:
        self.lock_path = lock_path
        self.holder = holder
        if holder:
            who = (f"checkout {holder.get('checkout', '?')} "
                   f"(pid {holder.get('pid', '?')}, started {holder.get('started', '?')})")
        else:
            who = "a run that has not written its holder record yet"
        super().__init__(
            f"another e2e run is using the shared work root {lock_path.parent}: {who}. "
            "Its disposable instances live there and this run would delete them mid-story, "
            f"so nothing was booted. Wait for it to finish (#244; lock file {lock_path})."
        )


def _try_lock(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def read_holder(lock_path: Path) -> dict | None:
    """The holder record, or ``None`` when there is none or it is unreadable."""
    try:
        raw = lock_path.read_bytes()
        return json.loads(raw.decode("utf-8")) if raw.strip() else None
    except (OSError, ValueError):
        return None


class WorkRootLock:
    """A held lock; ``release()`` once the session's instances are gone."""

    def __init__(self, fd: int, path: Path) -> None:
        self._fd: int | None = fd
        self.path = path

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            os.ftruncate(fd, 0)
            _unlock(fd)
        finally:
            os.close(fd)


def acquire(root: Path, checkout: Path) -> WorkRootLock:
    """Take the work root for this process, or raise :class:`WorkRootBusy`."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_NAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    if not _try_lock(fd):
        os.close(fd)
        raise WorkRootBusy(path, read_holder(path))
    record = {
        "pid": os.getpid(),
        "checkout": str(checkout),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, json.dumps(record).encode("utf-8"))
    return WorkRootLock(fd, path)
