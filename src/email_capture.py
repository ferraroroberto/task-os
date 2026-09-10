"""Email capture — a flagged email in the archiver's index becomes an Inbox task.

The push half of cross-fleet capture (#98): instead of remembering to search
for the mail that needs action, you flag it in Outlook, archive it as usual,
and the next pass lands it in Inbox with the ``.msg`` attached. The WhatsApp
half needs nothing here — whatsapp-radar POSTs ``/api/tasks`` with an
``external_id`` and the router's own idempotency (``tasks_repo.capture_task``)
does the deduping.

**The index is read-only from here, always.** :class:`FlaggedEmailIndex` opens
the archiver's ``emails.db`` with the ``file:…?mode=ro`` URI, a fresh
connection per query, exactly as ``src.search.emails_adapter`` does — the
archiver owns that file and this module never writes, migrates or copies it.
The flag is therefore something the *archiver* records while scanning: two
columns on ``emails``,

    flag_status   INTEGER   MAPI PidTagFlagStatus (0x1090):
                            0 / absent = none · 1 = complete · 2 = flagged
    flag_request  TEXT      the flag's own text ("Follow up"), nullable

An index without ``flag_status`` is **not configured, with that as its
reason** — not an empty result. That is the honest state on an archiver build
older than the flag release, and it is what the Settings card, ``/api/status``
and ``tasks status`` all show until the archiver ships it.

One pass (:func:`capture_once`) reads every ``flag_status = 2`` row and offers
it to :func:`~src.tasks_repo.capture_task`, keyed on

    external_id = "email:" + <the .msg path folded onto the placeholders>

— the ref, not ``emails.id``: the id is an autoincrement rowid that reshuffles
if the index is ever rebuilt, while the folded ref (``email:{onedrive}/…``) is
stable across a rebuild and portable to a second PC. A mail *moved* inside the
archive changes its ref and so captures once more; archiving is a one-time
gesture, so that is rare and visible rather than silent drift. A *renumber* is
not that case: the archiver renames a whole folder's files to keep its
sequence contiguous (email-archiver#61), and :func:`rename_ref` carries the
link and the capture key onto the new name, so nothing is captured twice.

Capture is one-way by construction. Clearing the flag later does not delete or
close the task, and nothing here ever writes back to the mail — see
:func:`~src.tasks_repo.capture_task`.

:class:`EmailCaptureService` runs it in-app: a thread started from the webapp
lifespan like the issue sync — first pass shortly after startup, then every
``capture.email_poll_minutes`` — plus ``run_now()`` for ``POST
/api/capture/email/run`` and the Settings card's button. ``status()`` is what
``/api/status``'s ``capture`` key, that card and ``tasks status`` render.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src import clock
from src import tasks_repo as repo
from src.config import AppConfig
from src.db import connect
from src.placeholders import normalize_path, to_ref
from src.search.emails_adapter import email_db_uri

logger = logging.getLogger(__name__)

#: ``created_by`` / activity actor on everything this module lands. Deliberately
#: not the issue sync's ``sync``: an activity row should say *which* channel
#: brought the task in, and whatsapp-radar already posts as ``whatsapp-radar``.
CAPTURE_ACTOR = "email-archiver"
#: ``PidTagFlagStatus`` — the one value meaning "flagged for follow-up".
FLAG_FOLLOWUP = 2
#: The column the archiver must expose before any of this can run.
FLAG_COLUMN = "flag_status"
EXTERNAL_ID_PREFIX = "email:"
INITIAL_DELAY_S = 15.0
#: Real-second override for `INITIAL_DELAY_S`. `TASKOS_CLOCK` pins every
#: timestamp this service *writes*, but the first automatic pass is scheduled
#: off a real `threading.Event.wait()`, not the pinned clock — so a disposable
#: e2e instance that enables capture (story 24's archive fixture) could have
#: its own background tick land mid-story, racing the manual "Check now" step
#: and rewriting `last_result`/`next_run` under a shot the story never touched
#: (#170: story-24-archive-9-desktop.png moved between two runs of one commit
#: for exactly this reason). Nothing in production sets this; the e2e suite's
#: `_boot()` sets it past any story's real runtime, the same way unit tests
#: already pass `initial_delay=999` directly.
DELAY_ENV = "TASKOS_CAPTURE_DELAY_S"
DESCRIPTION_MAX = 10_000
#: One pass never lands more than this, so a first run against a large archive
#: cannot flood Inbox in one go; the rest arrive on the following passes.
BATCH_LIMIT = 200


def _default_initial_delay() -> float:
    """`INITIAL_DELAY_S`, unless `DELAY_ENV` overrides it (see its docstring)."""
    raw = os.environ.get(DELAY_ENV, "").strip()
    if not raw:
        return INITIAL_DELAY_S
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{DELAY_ENV}={raw!r} is not a number") from exc


def external_id_for(ref: str) -> str:
    """The capture key for an email ref — ``email:{onedrive}/house/mail.msg``."""
    return EXTERNAL_ID_PREFIX + ref


def rename_ref(
    conn: Any, old_ref: str, new_ref: str, *, dry_run: bool = False
) -> dict[str, int]:
    """An archived ``.msg`` was renamed — its link and its capture key follow it.

    The archiver renumbers a folder after a batch ``apply`` / ``revert`` so its
    ``NNN`` prefixes stay contiguous (email-archiver#61), which renames files
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
    errors: list[str] = field(default_factory=list)
    created_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listed": self.listed, "created": self.created, "unchanged": self.unchanged,
            "errors": list(self.errors), "created_ids": list(self.created_ids),
        }

    def summary(self) -> str:
        bits = [f"{self.listed} flagged email(s)", f"{self.created} new"]
        if self.unchanged:
            bits.append(f"{self.unchanged} already captured")
        if self.errors:
            bits.append(f"{len(self.errors)} error(s)")
        return " · ".join(bits)


class FlaggedEmailIndex:
    """Read-only reader over the archiver's ``emails.db`` — the flagged rows only."""

    def __init__(self, db_path: str, placeholders: Mapping[str, str] | None = None) -> None:
        self.db_path = (db_path or "").strip()
        self.placeholders = dict(placeholders or {})

    # ------------------------------------------------------------- state
    def is_configured(self) -> tuple[bool, str | None]:
        """``(True, None)``, or ``False`` + the one reason that actually applies.

        Four distinct failures, four distinct messages — a caller must be able
        to tell "you never pointed me at an index" from "your archiver is too
        old to record flags", because the fix is different for each.
        """
        if not self.db_path:
            return False, "search.email_db not configured"
        if not Path(self.db_path).is_file():
            return False, f"email index not found at {self.db_path}"
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            return False, f"cannot open {self.db_path}: {exc}"
        try:
            has_emails = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'emails'"
            ).fetchone() is not None
            if not has_emails:
                return False, f"no emails table in {self.db_path} — not an email-archiver index"
            if FLAG_COLUMN not in self._columns(conn):
                return False, (
                    f"the email index has no {FLAG_COLUMN} column — this needs an email-archiver "
                    "build that records the Outlook follow-up flag while scanning"
                )
        except sqlite3.Error as exc:
            return False, f"cannot read {self.db_path}: {exc}"
        finally:
            conn.close()
        return True, None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(email_db_uri(self.db_path), uri=True, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _columns(conn: sqlite3.Connection) -> set[str]:
        return {str(r["name"]) for r in conn.execute("PRAGMA table_info(emails)").fetchall()}

    # ------------------------------------------------------------ reading
    def flagged(self, limit: int = BATCH_LIMIT) -> list[dict[str, Any]]:
        """Every follow-up-flagged email, oldest first, as capture-ready dicts.

        Oldest first so a backlog larger than ``limit`` drains in the order the
        mail arrived instead of the newest rows starving the older ones.
        """
        conn = self._connect()
        try:
            has_request = "flag_request" in self._columns(conn)
            request_col = "flag_request" if has_request else "NULL AS flag_request"
            rows = conn.execute(
                f"SELECT id, file_path, folder_path, filename, subject, sender, date_sent, "
                f"       body_preview, {request_col} "
                f"  FROM emails WHERE {FLAG_COLUMN} = ? ORDER BY date_sent, id LIMIT ?",
                (FLAG_FOLLOWUP, int(limit)),
            ).fetchall()
        finally:
            conn.close()
        return [self._entry(r) for r in rows]

    def _entry(self, e: sqlite3.Row) -> dict[str, Any]:
        path = normalize_path(e["file_path"] or "")
        ref = to_ref(path, self.placeholders)
        filename = e["filename"] or path.rsplit("/", 1)[-1]
        return {
            "ref": ref,
            "path": path,
            "filename": filename,
            "subject": (e["subject"] or "").strip() or filename,
            "sender": (e["sender"] or "").strip(),
            "date": (e["date_sent"] or "")[:10],
            "body_preview": (e["body_preview"] or "").strip(),
            "flag_request": (e["flag_request"] or "").strip() or None,
        }


def _description(entry: Mapping[str, Any]) -> str:
    """``From email: <sender> · <date>`` then the flag's own text and the preview."""
    head = " · ".join(b for b in (entry.get("sender"), entry.get("date")) if b)
    lines = [f"From email: {head}" if head else "From email"]
    if entry.get("flag_request"):
        lines.append(f"Flag: {entry['flag_request']}")
    if entry.get("body_preview"):
        lines.extend(["", str(entry["body_preview"])])
    return "\n".join(lines)[:DESCRIPTION_MAX]


def capture_once(
    conn: Any, index: FlaggedEmailIndex, *, actor: str = CAPTURE_ACTOR, limit: int = BATCH_LIMIT
) -> CaptureResult:
    """One pass: every flagged email becomes (or already is) an Inbox task.

    Raises :class:`sqlite3.Error` only when the *listing* fails — nothing is
    created from a bad read, the same rule the issue sync follows. A single
    email that cannot be landed becomes a ``result.errors`` entry and the pass
    carries on.
    """
    result = CaptureResult()
    entries = index.flagged(limit)
    result.listed = len(entries)
    for entry in entries:
        # The task and its link are one landing: a row the index can hand over
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


class EmailCaptureService:
    """The in-app poller + status holder (one per process, on ``app.state.capture``)."""

    def __init__(self, config: AppConfig, index: FlaggedEmailIndex | None = None, *,
                 interval_minutes: int | None = None, initial_delay: float | None = None) -> None:
        self.index = index if index is not None else FlaggedEmailIndex(
            config.search.email_db, config.placeholders
        )
        minutes = config.capture.email_poll_minutes if interval_minutes is None else interval_minutes
        self.interval_minutes = int(minutes)
        self.initial_delay = _default_initial_delay() if initial_delay is None else initial_delay
        if self.interval_minutes <= 0:
            self.enabled, self.reason = False, "capture.email_poll_minutes is 0 — the poller is off"
        else:
            self.enabled, self.reason = self.index.is_configured()
        self.last_run: str | None = None
        self.last_result: CaptureResult | None = None
        self.last_error: str | None = None
        self.next_run: datetime | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if not self.enabled:
            logger.warning("⚠️ capture: flagged-email capture off — %s", self.reason)

    # ------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "reason": None if self.enabled else self.reason,
            "source": self.index.db_path,
            "poll_minutes": self.interval_minutes,
            "last_run": self.last_run,
            "last_result": self.last_result.to_dict() if self.last_result else None,
            "last_error": self.last_error,
            "next_run": self.next_run.isoformat(timespec="minutes") if self.next_run else None,
            "running": self._thread is not None and self._thread.is_alive(),
        }

    # ---------------------------------------------------------------- run
    def run_now(self, conn: Any | None = None) -> CaptureResult | None:
        """One pass now (also the thread's tick). Errors are recorded, never raised past here."""
        if not self.enabled:
            return None
        with self._lock:
            own = conn is None
            c = conn or connect()
            try:
                result = capture_once(c, self.index)
            except Exception as exc:  # noqa: BLE001 — a bad pass is a status, not a dead app
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("❌ capture: pass failed")
                return None
            finally:
                if own:
                    c.close()
            self.last_error = None
            self.last_run = repo.now_iso()
            self.last_result = result
            logger.info("✅ capture: %s", result.summary())
            return result

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        # The clock, not `datetime.now()` — this value is rendered on the
        # Settings card, and so on a story screenshot (#134). The loop's own
        # `_stop.wait()` does the scheduling; this is display only.
        self.next_run = clock.now() + timedelta(seconds=self.initial_delay)
        self._thread = threading.Thread(target=self._run, name="task-os-capture", daemon=True)
        self._thread.start()
        logger.info("ℹ️ capture: flagged emails every %d min (first pass in %.0f s)",
                    self.interval_minutes, self.initial_delay)

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


__all__ = [
    "BATCH_LIMIT", "CAPTURE_ACTOR", "EXTERNAL_ID_PREFIX", "FLAG_COLUMN", "FLAG_FOLLOWUP",
    "INITIAL_DELAY_S", "CaptureResult", "EmailCaptureService", "FlaggedEmailIndex",
    "capture_once", "external_id_for", "rename_ref",
]
