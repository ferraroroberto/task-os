"""The one process clock, and the one place it can be pinned.

Every timestamp the app stores or paints comes from here: :func:`now_iso` for
the domain rows (`src.tasks_repo` re-exports it, so the routers, the CLI's
local backend, the mirror and the seed all read the same clock) and
:func:`now` for the build identity in the page footer.

Two ways to pin it:

- :func:`use_clock` — a context manager, for an in-process seed or test
  (``with use_clock(lambda: dt): ...``);
- ``TASKOS_CLOCK`` — an ISO 8601 datetime, for a whole process a test does not
  run in-line. The e2e suite's disposable instances set it (#134): the story
  gallery in ``docs/screenshots/`` is only proof if a change in it means a
  change in the app, and an unpinned instance writes the run's own minute onto
  every activity row, comment and build footer, so two runs of one commit
  disagree. The one exception is the mirror instance, whose import-conflict
  rule is *defined* by a clock that advances — see ``tests/e2e/conftest.py``.

Nothing in production sets ``TASKOS_CLOCK``; an unparseable value is a hard
failure rather than a silent fall back to the wall clock, which would be a
process that believes it is pinned and is not.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime

logger = logging.getLogger(__name__)

CLOCK_ENV = "TASKOS_CLOCK"


def _initial_clock() -> Callable[[], datetime]:
    """The wall clock, unless ``TASKOS_CLOCK`` pins this process to one instant."""
    pinned = os.environ.get(CLOCK_ENV, "").strip()
    if not pinned:
        return lambda: datetime.now().astimezone()
    try:
        fixed = datetime.fromisoformat(pinned).astimezone()
    except ValueError as exc:
        raise ValueError(f"{CLOCK_ENV}={pinned!r} is not an ISO 8601 datetime") from exc
    logger.info("ℹ️ clock pinned to %s by %s", fixed.isoformat(timespec="seconds"), CLOCK_ENV)
    return lambda: fixed


_clock: Callable[[], datetime] = _initial_clock()


def now() -> datetime:
    """Current local time, timezone-aware."""
    return _clock()


def now_iso() -> str:
    """Current local timestamp, ISO 8601, second precision, with offset."""
    return _clock().isoformat(timespec="seconds")


def today() -> date:
    return _clock().date()


@contextmanager
def use_clock(fn: Callable[[], datetime]) -> Iterator[None]:
    """Pin the clock (seed / tests): ``with use_clock(lambda: dt): ...``."""
    global _clock
    previous = _clock
    _clock = fn
    try:
        yield
    finally:
        _clock = previous
