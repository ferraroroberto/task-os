"""The one background poller the in-app schedulers share (#262).

:class:`~src.issue_sync.IssueSyncService` and
:class:`~src.email_capture.EmailCaptureService` are the same machine — a daemon
thread that waits an initial delay, runs one pass, waits the interval, repeats
— with a locked ``run_now`` that opens (or borrows) a connection and records
the outcome as status instead of raising. That machine lives here once; each
service supplies only its pass (:meth:`Poller._run_pass`), how a pass's
outcome lands in its own status fields (:meth:`Poller._record_success` /
:meth:`Poller._record_failure`) and its status extras.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any

from src import clock
from src.db import connect

logger = logging.getLogger(__name__)


def initial_delay_from_env(env_name: str, default: float) -> float:
    """`default`, unless the environment variable `env_name` overrides it."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name}={raw!r} is not a number") from exc


class Poller[ResultT]:
    """Thread + lock + status skeleton; subclasses set the class attributes below.

    A subclass's ``__init__`` sets ``enabled`` / ``reason`` / ``interval_minutes``
    and calls :meth:`_init_poller`.
    """

    #: Seconds before the first automatic pass (unless `DELAY_ENV` overrides it).
    INITIAL_DELAY_S: float
    #: Real-second override for `INITIAL_DELAY_S` (see the subclass's module).
    DELAY_ENV: str
    #: Name of the daemon thread.
    THREAD_NAME: str

    enabled: bool
    interval_minutes: int
    last_error: str | None
    next_run: datetime | None

    def _init_poller(self, initial_delay: float | None) -> None:
        self.initial_delay = (
            initial_delay_from_env(self.DELAY_ENV, self.INITIAL_DELAY_S)
            if initial_delay is None else initial_delay
        )
        self.last_error = None
        self.next_run = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ----------------------------------------------------- subclass contract
    def _run_pass(self, conn: Any) -> ResultT:
        raise NotImplementedError

    def _record_success(self, result: ResultT) -> None:
        """Clear the error, stamp the run, keep `result`, log the outcome."""
        raise NotImplementedError

    def _record_failure(self, exc: Exception) -> None:
        """A pass failed: set `last_error` (and any extra), log it."""
        raise NotImplementedError

    def _start_message(self) -> str:
        """The info line logged when the thread starts."""
        raise NotImplementedError

    # -------------------------------------------------------------- status
    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _next_run_text(self) -> str | None:
        return self.next_run.isoformat(timespec="minutes") if self.next_run else None

    # ----------------------------------------------------------------- run
    def run_now(self, conn: Any | None = None) -> ResultT | None:
        """One pass now (also the thread's tick). Errors are recorded, never raised past here."""
        if not self.enabled:
            return None
        with self._lock:
            own = conn is None
            c = conn or connect()
            try:
                result = self._run_pass(c)
            except Exception as exc:  # noqa: BLE001 — a bad pass is a status, not a dead app
                self._record_failure(exc)
                return None
            finally:
                if own:
                    c.close()
            self._record_success(result)
            return result

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        # The clock, not `datetime.now()`: this value is displayed on the
        # Settings card (and so on a story screenshot), never waited on —
        # the loop's own `_stop.wait()` does the scheduling (#134).
        self.next_run = clock.now() + timedelta(seconds=self.initial_delay)
        self._thread = threading.Thread(target=self._run, name=self.THREAD_NAME, daemon=True)
        self._thread.start()
        logger.info(self._start_message())

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        if self._stop.wait(self.initial_delay):
            return
        while not self._stop.is_set():
            self.run_now()
            self.next_run = clock.now() + timedelta(minutes=self.interval_minutes)
            if self._stop.wait(self.interval_minutes * 60):
                return


__all__ = ["Poller", "initial_delay_from_env"]
