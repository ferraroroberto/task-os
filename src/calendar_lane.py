"""The Today calendar lane (#96) — today's events from a private ICS URL.

Read-only, one direction: calendar → eyes. :class:`CalendarService` fetches
``calendar.ics_url`` with a bounded request, keeps the last good copy, and
answers the ``calendar`` group of ``GET /api/today`` and the ``calendar`` key
of ``GET /api/status``::

    {"configured": true, "reason": null, "source": "calendar.example.com",
     "state": "ok", "error": null, "date": "2026-09-07",
     "all_day": [{"summary"}], "events": [{"summary", "start", "end",
     "starts_before", "ends_after"}], "skipped_recurring": 0, "unreadable": 0,
     "fetched_at": "…", "failing_since": null, "stale": false, "refreshing": false}

The rules the lane relies on — the federated search's discipline for an
external read (:mod:`src.search.federated`):

- ``state`` is one of :data:`STATES` and every failure is its own one:
  ``off`` (blank address — ``configured: false`` + ``reason``), ``bad_url``
  (not an http(s) address, or the server refused it with a 4xx),
  ``unreachable`` (no connection, a dropped one, a 5xx), ``timeout`` (no
  complete answer within ``timeout_seconds``) and ``parse_error`` (an answer
  that is not a calendar). An empty ``events`` list means a free day **only**
  when ``state`` is ``ok``.
- A failure after a good fetch keeps the good copy on screen, marked
  ``stale`` with the failure beside it and ``failing_since`` — "unreachable
  since 09:12", never a lane emptied by a hiccup.
- A request never waits longer than ``timeout_seconds``: with a copy in hand
  an expired one is served at once (``stale`` + ``refreshing``) while one
  background fetch replaces it; only with nothing to show does a request wait
  for that fetch, and then no longer than the bound.
- The URL is a secret. It never leaves this module: statuses, errors and log
  lines carry :func:`source_host` only, and no exception text from the HTTP
  stack (which quotes the path) is ever passed on.

:meth:`CalendarService.refresh` is the one way to fetch before the copy
expires — the Settings card's *Refresh now*.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from src import clock, ics
from src.config import AppConfig
from src.pooled_http import pooled_request

logger = logging.getLogger(__name__)

__all__ = ["STATES", "CalendarFetchError", "CalendarService", "fetch_ics", "source_host"]

STATES = ("ok", "off", "bad_url", "unreachable", "timeout", "parse_error")
#: How soon a failed fetch is tried again by a Today request.
RETRY_AFTER_FAILURE_S = 60.0
#: A private calendar is kilobytes; anything past this is not one.
MAX_BYTES = 20 * 1024 * 1024
#: Scheduling slack on top of the fetch's own bound before a waiting request
#: gives up and reports the fetch as timed out.
WAIT_GRACE_S = 0.25


class CalendarFetchError(Exception):
    """A fetch that failed, as one of :data:`STATES` plus a URL-free sentence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def source_host(url: str) -> str | None:
    """The part of the address that is safe to show: its host."""
    try:
        return urlsplit(url.strip()).hostname
    except ValueError:
        return None


def _normalise(url: str) -> tuple[str | None, str | None]:
    """``(fetchable url, None)`` or ``(None, why it is not one)``."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None, "calendar.ics_url is not a URL"
    scheme = parts.scheme.lower()
    if scheme == "webcal":
        parts = parts._replace(scheme="https")
    elif scheme not in ("http", "https"):
        return None, "calendar.ics_url must be an http(s) or webcal address"
    if not parts.hostname:
        return None, "calendar.ics_url has no host"
    return urlunsplit(parts), None


def _timed_out(exc: BaseException) -> bool:
    """``requests`` reports a stalled body as ``ConnectionError(ReadTimeoutError)``."""
    return isinstance(exc, requests.exceptions.Timeout) or "timed out" in repr(exc).lower()


def fetch_ics(url: str, timeout_s: float) -> str:
    """The feed's text, or :class:`CalendarFetchError` — bounded to ``timeout_s``
    for the whole download, not per socket read."""
    host = source_host(url) or "the calendar server"
    deadline = time.monotonic() + timeout_s
    try:
        res = pooled_request(
            "GET", url, timeout=timeout_s, stream=True,
            headers={"Accept": "text/calendar, text/plain;q=0.5, */*;q=0.1", "User-Agent": "task-os"},
        )
    except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema):
        raise CalendarFetchError("bad_url", "calendar.ics_url is not a fetchable address") from None
    except requests.exceptions.RequestException as exc:
        if _timed_out(exc):
            raise CalendarFetchError("timeout", f"{host} did not answer within {timeout_s:g} s") from None
        raise CalendarFetchError("unreachable", f"could not reach {host} ({type(exc).__name__})") from None
    with res:
        if 400 <= res.status_code < 500:
            raise CalendarFetchError(
                "bad_url",
                f"{host} answered HTTP {res.status_code} — the address is wrong or no longer shared",
            )
        if res.status_code != 200:
            raise CalendarFetchError("unreachable", f"{host} answered HTTP {res.status_code}")
        body, size = [], 0
        try:
            for chunk in res.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise CalendarFetchError("parse_error", f"the feed from {host} is larger than 20 MB")
                body.append(chunk)
                if time.monotonic() > deadline:
                    raise CalendarFetchError(
                        "timeout", f"{host} did not finish sending within {timeout_s:g} s")
        except requests.exceptions.RequestException as exc:
            if _timed_out(exc):
                raise CalendarFetchError(
                    "timeout", f"{host} did not finish sending within {timeout_s:g} s") from None
            raise CalendarFetchError(
                "unreachable", f"the connection to {host} dropped ({type(exc).__name__})") from None
    return b"".join(body).decode("utf-8", errors="replace")


class CalendarService:
    """The lane's one source of truth; see the module docstring for the rules."""

    def __init__(
        self,
        config: AppConfig,
        *,
        fetcher: Callable[[str, float], str] = fetch_ics,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        cal = config.calendar
        self._raw = cal.ics_url.strip()
        self.source = source_host(self._raw) if self._raw else None
        self._url, self._problem = _normalise(self._raw) if self._raw else (None, None)
        self.refresh_minutes = max(1, cal.refresh_minutes)
        self.timeout_s = cal.timeout_seconds if cal.timeout_seconds > 0 else 2.0
        self._fetcher = fetcher
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._calendar: ics.Calendar | None = None
        self._fetched_at: str | None = None
        self._fetched_mono: float | None = None
        self._attempt_mono: float | None = None
        self._error: tuple[str, str] | None = None
        self._failing_since: str | None = None
        self._inflight: threading.Event | None = None
        self._agenda_key: tuple[Any, ...] | None = None
        self._agenda: ics.Agenda | None = None
        if not self._raw:
            logger.info("ℹ️ calendar: lane off — calendar.ics_url is blank")
        elif self._problem:
            logger.warning("⚠️ calendar: %s", self._problem)
        else:
            logger.info("📅 calendar: lane on — %s, refreshed every %d min", self.source, self.refresh_minutes)

    @property
    def configured(self) -> bool:
        return bool(self._raw)

    # ------------------------------------------------------------ the API
    def today(self) -> dict[str, Any]:
        """``GET /api/today``'s ``calendar`` group."""
        return self._group(force=False)

    def refresh(self) -> dict[str, Any]:
        """Fetch now (joining a fetch already under way) and answer the group."""
        return self._group(force=True)

    def status(self) -> dict[str, Any]:
        """``GET /api/status``'s ``calendar`` key — the group without the rows."""
        group = self._group(force=False)
        events_today = len(group.pop("events")) + len(group.pop("all_day"))
        return {
            **group,
            "events_today": events_today if group["state"] == "ok" or group["stale"] else None,
            "refresh_minutes": self.refresh_minutes,
            "timeout_seconds": self.timeout_s,
        }

    # ------------------------------------------------------------ internals
    def _group(self, *, force: bool) -> dict[str, Any]:
        day = clock.today()
        group: dict[str, Any] = {
            "configured": self.configured, "reason": None, "source": self.source,
            "state": "ok", "error": None, "date": day.isoformat(),
            "all_day": [], "events": [], "skipped_recurring": 0, "unreadable": 0,
            "fetched_at": None, "failing_since": None, "stale": False, "refreshing": False,
        }
        if not self.configured:
            return {**group, "state": "off", "reason": "calendar.ics_url is blank — no calendar connected"}
        if self._problem:
            return {**group, "state": "bad_url", "error": self._problem}

        with self._lock:
            pending = self._inflight
            if pending is None and (force or self._due()):
                pending = self._start()
            must_wait = pending is not None and (force or self._calendar is None)
        if must_wait and pending is not None:
            pending.wait(self.timeout_s + WAIT_GRACE_S)

        with self._lock:
            cal, error = self._calendar, self._error
            group.update(
                fetched_at=self._fetched_at, failing_since=self._failing_since,
                refreshing=self._inflight is not None,
            )
            expired = self._fetched_mono is not None and self._age() >= self.refresh_minutes * 60
        if error is not None:
            group["state"], group["error"] = error
        elif cal is None:
            # Waited the full bound and the first fetch is still out.
            group["state"] = "timeout"
            group["error"] = f"{self.source} did not answer within {self.timeout_s:g} s"
        if cal is not None:
            group["stale"] = error is not None or expired
            agenda = self._agenda_for(cal, day)
            group.update(all_day=agenda.all_day, events=agenda.timed,
                         skipped_recurring=agenda.skipped_recurring, unreadable=agenda.unreadable)
        return group

    def _age(self) -> float:
        return self._monotonic() - (self._fetched_mono or 0.0)

    def _due(self) -> bool:
        if self._attempt_mono is None:
            return True
        if self._error is not None:
            return self._monotonic() - self._attempt_mono >= RETRY_AFTER_FAILURE_S
        return self._age() >= self.refresh_minutes * 60

    def _start(self) -> threading.Event:
        done = threading.Event()
        self._attempt_mono = self._monotonic()
        self._inflight = done
        threading.Thread(target=self._run, args=(done,), name="task-os-calendar", daemon=True).start()
        return done

    def _run(self, done: threading.Event) -> None:
        error: tuple[str, str] | None = None
        cal: ics.Calendar | None = None
        try:
            text = self._fetcher(self._url or "", self.timeout_s)
        except CalendarFetchError as exc:
            error = (exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 — never a traceback: the HTTP stack quotes the URL
            error = ("unreachable", f"could not fetch from {self.source} ({type(exc).__name__})")
        else:
            try:
                cal = ics.parse_calendar(text)
            except ics.ICSParseError as exc:
                error = ("parse_error", f"what {self.source} sent is not a calendar — {exc}")
            except Exception as exc:  # noqa: BLE001 — a parser bug is a visible state, not a dead lane
                logger.exception("❌ calendar: parsing the feed from %s failed", self.source)
                error = ("parse_error", f"the feed from {self.source} could not be read ({type(exc).__name__})")
        with self._lock:
            if error is not None:
                if self._error is None or self._error[0] != error[0]:
                    logger.warning("⚠️ calendar: %s — %s", error[0], error[1])
                if self._failing_since is None:
                    self._failing_since = clock.now_iso()
                self._error = error
            else:
                if self._error is not None:
                    logger.info("✅ calendar: %s answering again", self.source)
                self._calendar = cal
                self._fetched_at = clock.now_iso()
                self._fetched_mono = self._monotonic()
                self._error = None
                self._failing_since = None
            self._inflight = None
        done.set()

    def _agenda_for(self, cal: ics.Calendar, day: Any) -> ics.Agenda:
        key = (id(cal), day)
        if self._agenda_key != key or self._agenda is None:
            self._agenda, self._agenda_key = ics.day_agenda(cal, day), key
        return self._agenda
