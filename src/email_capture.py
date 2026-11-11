"""Email capture — a flagged email in the archiver's index becomes an Inbox task.

The push half of cross-fleet capture: instead of remembering to search
for the mail that needs action, you flag it in Outlook, archive it as usual,
and the next pass lands it in Inbox with the ``.msg`` attached. The WhatsApp
half needs nothing here — whatsapp-radar POSTs ``/api/tasks`` with an
``external_id`` and the router's own idempotency (``tasks_repo.capture_task``)
does the deduping.

**task-os opens no folder-explorer database.** :class:`FlaggedEmailIndex` pages
folder-explorer's ``GET /api/v1/mail/flagged`` (oldest first, ``limit``/``offset``)
through :class:`~src.search.folder_explorer.FolderExplorerClient`, so the
flag's meaning (``flag_status`` 2, "follow up") and the on-disk schema stay
folder-explorer's. An index that records no flags answers ``not-configured``
with that as its reason — the Settings card, ``/api/status`` and ``tasks status``
show it, never an empty result.

A pass that cannot list raises :class:`~src.search.folder_explorer.Unavailable`
before anything is created, and ``last_result`` stays the last good pass:
"folder-explorer is down" can never read as "0 flagged". The service keeps the
source's own state (:class:`SourceHealth`): ``unreachable`` (nothing
answered), ``slow`` (no answer within the capture timeout), ``indexing``,
``not-configured`` or ``failed`` (answered, but not the contract — a
folder-explorer without the route included), with since when.

One pass (:func:`capture_once`) offers every flagged mail to
:func:`~src.tasks_repo.capture_task`, keyed on

    external_id = "email:" + <the .msg path folded onto the placeholders>

— the ref, not folder-explorer's row id: the id reshuffles if the index is ever
rebuilt, while the folded ref (``email:{onedrive}/…``) is stable across a
rebuild and portable to a second PC. A mail *moved* inside the archive changes
its ref and so captures once more; archiving is a one-time gesture, so that is
rare and visible rather than silent drift. A *renumber* is not that case: the
archiver renames a whole folder's files to keep its sequence contiguous, and
:func:`rename_ref` carries the link and the capture key onto the new name, so
nothing is captured twice.

Capture is one-way by construction. Clearing the flag later does not delete or
close the task, and nothing here ever writes back to the mail — see
:func:`~src.tasks_repo.capture_task`. The other direction holds too: deleting a
captured task *dismisses* that mail. Its archived ``.msg`` keeps the flag it was
saved with, so folder-explorer lists it on every pass; the capture key outlives
the task and the pass counts it ``dismissed`` instead of landing it.

:class:`EmailCaptureService` runs it in-app: a thread started from the webapp
lifespan like the issue sync — first pass shortly after startup, then every
``capture.email_poll_minutes`` — plus ``run_now()`` for ``POST
/api/capture/email/run`` and the Settings card's button. ``status()`` is what
``/api/status``'s ``capture`` key, that card and ``tasks status`` render.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Container, Mapping
from dataclasses import dataclass, field
from typing import Any

from src import tasks_repo as repo
from src.config import AppConfig
from src.placeholders import normalize_path, to_ref
from src.poller import Poller
from src.search.folder_explorer import FAILED, UNREACHABLE, FolderExplorerClient, Unavailable

logger = logging.getLogger(__name__)

#: ``created_by`` / activity actor on everything this module lands. Deliberately
#: not the issue sync's ``sync``: an activity row should say *which* channel
#: brought the task in, and whatsapp-radar already posts as ``whatsapp-radar``.
CAPTURE_ACTOR = "email-archiver"
EXTERNAL_ID_PREFIX = "email:"
INITIAL_DELAY_S = 15.0
#: Real-second override for `INITIAL_DELAY_S`. `TASKOS_CLOCK` pins every
#: timestamp this service *writes*, but the first automatic pass is scheduled
#: off a real `threading.Event.wait()`, not the pinned clock — a background
#: tick must not land mid-story on a disposable e2e instance, racing a
#: manual "Check now" step and rewriting `last_result`/`next_run` under a
#: shot the story never touched. Nothing in production sets this; the e2e
#: suite's `_boot()` sets it past any story's real runtime, the same way unit
#: tests already pass `initial_delay=999` directly.
DELAY_ENV = "TASKOS_CAPTURE_DELAY_S"
DESCRIPTION_MAX = 10_000
#: One pass never lands more than this, so a first run against a large archive
#: cannot flood Inbox in one go; the rest arrive on the following passes.
BATCH_LIMIT = 200
#: Mails asked per request — folder-explorer's own ceiling for the route.
PAGE_SIZE = 200
#: A background thread can wait longer than the Search tab's 1.8 s: a pass is
#: not holding anyone's screen, and a slow answer is still an answer.
CAPTURE_TIMEOUT_S = 10.0
#: Source states beyond the client's own: ``slow`` is "no answer in time" (the
#: process may be up), ``unknown`` is "no pass has run yet", never a guess.
SLOW, UNKNOWN, OK = "slow", "unknown", "ok"


def external_id_for(ref: str) -> str:
    """The capture key for an email ref — ``email:{onedrive}/house/mail.msg``."""
    return EXTERNAL_ID_PREFIX + ref


def rename_ref(
    conn: Any, old_ref: str, new_ref: str, *, dry_run: bool = False
) -> dict[str, int]:
    """An archived ``.msg`` was renamed — its link and its capture key follow it.

    The archiver renumbers a folder after a batch ``apply`` / ``revert`` so its
    ``NNN`` prefixes stay contiguous, which renames files
    task-os is holding the ref of in exactly the two places this module put
    them: the ``links(kind='email')`` row the drawer draws its chip from, and
    the ``external_id`` the capture is keyed on. Healing both from the
    archiver's map is what keeps the chip openable and keeps *capture lands
    once* true — an un-healed key means the next poll sees an unknown ref and
    lands the same mail a second time.

    One ref, both places, counted separately: ``{"links": n, "tasks": n}``.
    ``dry_run`` counts without writing.
    """
    return {
        "links": repo.rename_link_url(conn, old_ref, new_ref, kind="email", dry_run=dry_run),
        "tasks": repo.rename_external_id(
            conn, external_id_for(old_ref), external_id_for(new_ref), dry_run=dry_run,
        ),
    }


@dataclass
class CaptureResult:
    """Counts of one pass; ``errors`` lists per-email failures (the pass still completes)."""

    listed: int = 0
    created: int = 0
    unchanged: int = 0
    #: still flagged, but the task it once landed was deleted
    dismissed: int = 0
    errors: list[str] = field(default_factory=list)
    created_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listed": self.listed, "created": self.created, "unchanged": self.unchanged,
            "dismissed": self.dismissed, "errors": list(self.errors),
            "created_ids": list(self.created_ids),
        }

    def summary(self) -> str:
        bits = [f"{self.listed} flagged email(s)", f"{self.created} new"]
        if self.unchanged:
            bits.append(f"{self.unchanged} already captured")
        if self.dismissed:
            bits.append(f"{self.dismissed} dismissed")
        if self.errors:
            bits.append(f"{len(self.errors)} error(s)")
        return " · ".join(bits)


class FlaggedEmailIndex:
    """The flagged mails folder-explorer lists — read through its v1 API, never from its files."""

    def __init__(self, client: FolderExplorerClient, placeholders: Mapping[str, str] | None = None) -> None:
        self.client = client
        self.placeholders = dict(placeholders or {})

    # ------------------------------------------------------------- state
    def is_configured(self) -> tuple[bool, str | None]:
        """``(True, None)``, or ``False`` + why this install names no folder-explorer.

        Static on purpose: whether folder-explorer is up, still indexing or has no
        flag column is the live state of each pass (:class:`SourceHealth`), and a
        probe here would hold the app's boot on a hung service.
        """
        if self.client.configured:
            return True, None
        return False, "search.folder_explorer_url not configured"

    # ------------------------------------------------------------ reading
    def flagged(
        self, limit: int = BATCH_LIMIT, settled: Container[str] = ()
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Follow-up-flagged emails, oldest first → ``(new entries, settled keys)``.

        Oldest first so a backlog larger than ``limit`` drains in the order the
        mail arrived instead of the newest rows starving the older ones.

        ``settled`` holds the capture keys already captured or dismissed. The
        flag on an archived ``.msg`` never clears, so those rows come back on
        every pass: they are stepped over and returned apart (the second list),
        and only the rest count toward ``limit`` — otherwise the oldest
        ``limit`` mails would fill the window forever and the next one would
        never be reached.

        Raises :class:`Unavailable` when folder-explorer cannot list; nothing is
        returned from a half-read. A mail that shifts between two pages is
        caught by the next pass, which is idempotent.
        """
        entries: list[dict[str, Any]] = []
        skipped: list[str] = []
        offset = 0
        while len(entries) < int(limit):
            body = self.client.flagged(PAGE_SIZE, offset)
            mails = body.get("mails")
            if not isinstance(mails, list):
                raise Unavailable(FAILED, "folder-explorer's flagged-mail answer has no mails list")
            for mail in mails:
                entry = self._entry(mail)
                key = external_id_for(entry["ref"])
                if key in settled:
                    skipped.append(key)
                    continue
                entries.append(entry)
                if len(entries) >= int(limit):
                    break
            offset += len(mails)
            total = body.get("total")
            if not mails or (isinstance(total, int) and offset >= total):
                break
        return entries, skipped

    def _entry(self, m: Mapping[str, Any]) -> dict[str, Any]:
        path = normalize_path(str(m.get("path") or ""))
        ref = to_ref(path, self.placeholders)
        filename = str(m.get("filename") or "") or path.rsplit("/", 1)[-1]
        return {
            "ref": ref,
            "path": path,
            "filename": filename,
            "subject": str(m.get("subject") or "").strip() or filename,
            "sender": str(m.get("sender") or "").strip(),
            "date": str(m.get("date") or "")[:10],
            "body_preview": str(m.get("preview") or "").strip(),
        }


def _description(entry: Mapping[str, Any]) -> str:
    """``From email: <sender> · <date>`` then the preview."""
    head = " · ".join(b for b in (entry.get("sender"), entry.get("date")) if b)
    lines = [f"From email: {head}" if head else "From email"]
    if entry.get("body_preview"):
        lines.extend(["", str(entry["body_preview"])])
    return "\n".join(lines)[:DESCRIPTION_MAX]


def capture_once(
    conn: Any, index: FlaggedEmailIndex, *, actor: str = CAPTURE_ACTOR, limit: int = BATCH_LIMIT
) -> CaptureResult:
    """One pass: every flagged email becomes (or already is) an Inbox task.

    Raises :class:`~src.search.folder_explorer.Unavailable` (folder-explorer cannot
    list) or :class:`sqlite3.Error` (the tasks database cannot be read) only when
    the *listing* fails — nothing is created from a bad read, the same rule the
    issue sync follows. A single email that cannot be landed becomes a
    ``result.errors`` entry and the pass carries on.
    """
    result = CaptureResult()
    # Keys already settled (captured, or captured and since deleted) are stepped
    # over *before* the limit applies and counted from this map, so they cost the
    # window nothing while the pass still reports them as before.
    settled = repo.captured_keys(conn, EXTERNAL_ID_PREFIX)
    entries, skipped = index.flagged(limit, settled)
    for key in skipped:
        if settled[key]:
            result.unchanged += 1
        else:
            result.dismissed += 1
    result.listed = len(entries) + len(skipped)
    for entry in entries:
        # The task and its link are one landing: a row folder-explorer can hand over
        # with an empty subject or path fails somewhere in here, and the whole
        # attempt has to become an error entry rather than ending the pass —
        # one unusable email must not cost the other 199 their capture.
        try:
            task, outcome = repo.capture_task(
                conn,
                external_id=external_id_for(entry["ref"]),
                title=entry["subject"],
                actor=actor,
                status="inbox",
                description=_description(entry),
            )
            if outcome == "dismissed":
                result.dismissed += 1
                continue
            if outcome != "created":
                result.unchanged += 1
                continue
            # The link stores the **ref**, not a built `taskos://` URL: the
            # drawer's chip (`format.js::chipFor` → `folderChip`) keys on a
            # leading `{` and derives the opener href itself. Storing the URL
            # renders a plain, hrefless web chip instead — so the ref is what
            # makes the .msg openable through the existing chip, with no UI
            # change of its own.
            repo.add_link(conn, task["id"], entry["ref"], label=entry["filename"], kind="email")
        except (repo.RepoError, sqlite3.Error) as exc:
            result.errors.append(f"{entry['filename']}: {exc}")
            logger.warning("⚠️ capture: could not land %s (%s)", entry["path"], exc)
            continue
        result.created += 1
        result.created_ids.append(task["id"])
        logger.info("ℹ️ capture: new task #%d from a flagged email — %s", task["id"], entry["subject"])
    return result


@dataclass
class SourceHealth:
    """What the last pass learned about folder-explorer, as ``/api/status`` shows it.

    ``state`` is ``unknown`` until the first pass has run, never a guess;
    ``since`` is when the current state began, ``last_ok`` the last pass that
    listed, ``failures`` the consecutive passes that could not.
    """

    state: str = UNKNOWN
    reason: str | None = None
    since: str | None = None
    last_ok: str | None = None
    failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "since": self.since,
                "last_ok": self.last_ok, "failures": self.failures}


def source_state(exc: Unavailable) -> str:
    """The client's state, with "no answer in time" told apart from "nothing answered"."""
    return SLOW if exc.state == UNREACHABLE and exc.timed_out else exc.state


class EmailCaptureService(Poller[CaptureResult]):
    """The in-app poller + status holder (one per process, on ``app.state.capture``)."""

    INITIAL_DELAY_S = INITIAL_DELAY_S
    DELAY_ENV = DELAY_ENV
    THREAD_NAME = "task-os-capture"

    def __init__(self, config: AppConfig, index: FlaggedEmailIndex | None = None, *,
                 interval_minutes: int | None = None, initial_delay: float | None = None) -> None:
        self.index = index if index is not None else FlaggedEmailIndex(
            FolderExplorerClient(config.search.folder_explorer_url, timeout_s=CAPTURE_TIMEOUT_S),
            config.placeholders,
        )
        minutes = config.capture.email_poll_minutes if interval_minutes is None else interval_minutes
        self.interval_minutes = int(minutes)
        self._init_poller(initial_delay)
        if self.interval_minutes <= 0:
            self.enabled, self.reason = False, "capture.email_poll_minutes is 0 — the poller is off"
        else:
            self.enabled, self.reason = self.index.is_configured()
        self.last_run: str | None = None
        self.last_result: CaptureResult | None = None
        self.source = SourceHealth()
        if not self.enabled:
            logger.warning("⚠️ capture: flagged-email capture off — %s", self.reason)

    # ------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        client = self.index.client
        return {
            "enabled": self.enabled,
            "reason": None if self.enabled else self.reason,
            "source": {"url": client.host if client.configured else None, **self.source.to_dict()},
            "poll_minutes": self.interval_minutes,
            "last_run": self.last_run,
            "last_result": self.last_result.to_dict() if self.last_result else None,
            "last_error": self.last_error,
            "next_run": self._next_run_text(),
            "running": self._running(),
        }

    # ---------------------------------------------------------------- run
    def _run_pass(self, conn: Any) -> CaptureResult:
        return capture_once(conn, self.index)

    def _record_success(self, result: CaptureResult) -> None:
        was, now = self.source, repo.now_iso()
        self.last_error = None
        self.last_run = now
        self.last_result = result
        self.source = SourceHealth(state=OK, since=was.since if was.state == OK else now, last_ok=now)
        if was.state not in (OK, UNKNOWN):
            logger.info("✅ capture: folder-explorer lists again (was %s since %s)", was.state, was.since)
        logger.info("✅ capture: %s", result.summary())

    def _record_failure(self, exc: Exception) -> None:
        if not isinstance(exc, Unavailable):
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("❌ capture: pass failed")
            return
        state, was = source_state(exc), self.source
        since = was.since if was.state == state else repo.now_iso()
        self.source = SourceHealth(state=state, reason=exc.reason, since=since,
                                   last_ok=was.last_ok, failures=was.failures + 1)
        # The state leads the message and says since when, so the card and `tasks status`
        # read "unreachable since 14:02" instead of looking merely idle.
        self.last_error = f"{state} since {since}: {exc.reason}"
        if was.state != state:
            logger.warning("⚠️ capture: flagged mail unavailable — %s (%s)", state, exc.reason)

    def _start_message(self) -> str:
        return (f"ℹ️ capture: flagged emails every {self.interval_minutes} min "
                f"(first pass in {self.initial_delay:.0f} s)")


__all__ = [
    "BATCH_LIMIT", "CAPTURE_ACTOR", "CAPTURE_TIMEOUT_S", "EXTERNAL_ID_PREFIX", "INITIAL_DELAY_S", "SLOW",
    "CaptureResult", "EmailCaptureService", "FlaggedEmailIndex", "SourceHealth",
    "capture_once", "external_id_for", "rename_ref", "source_state",
]
