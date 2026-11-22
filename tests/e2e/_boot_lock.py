"""The one-instance-boot-at-a-time lock the e2e suite takes across processes.

A free port is found by binding port 0 and letting go of it, and the child
process binds it a moment later. In that window another process's ``bind(0)``
can be handed the very same number, whether it is a second pytest-xdist worker
of this run or another checkout's run on the same machine. So every boot, in
every run, takes this one OS lock around "pick a free port, start the child
that binds it, wait until it answers".

The lock is an OS lock on an open handle, not a "does the file exist" marker:
the kernel drops it the moment the holding process dies, however it died, so a
killed run never leaves a lock behind that blocks the next one.

Stdlib only; ``msvcrt`` on Windows, ``fcntl`` elsewhere.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BOOT_LOCK_NAME = ".boot.lock"

#: Where the Windows byte-range lock sits. A Windows lock is mandatory, so it is
#: taken far past the start of the file, leaving the file readable. Locking
#: beyond end-of-file is allowed there.
_WIN_LOCK_OFFSET = 1 << 20


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


@contextmanager
def boot_lock(root: Path, timeout: float = 120.0) -> Iterator[None]:
    """Serialise instance boots across every e2e process on the machine.

    Boots take about a second, so holding an OS lock over the whole
    pick-start-wait costs a few seconds in total and removes the race outright,
    where a retry would only paper over a ``healthz`` answered by the *other*
    process's instance. Waits up to ``timeout``.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / BOOT_LOCK_NAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(fd):
            if time.monotonic() > deadline:
                raise TimeoutError(f"no instance boot slot after {timeout:.0f}s ({path})")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
