"""Nightly database backup — ``data/tasks.db`` → ``<mirror.backup_dir>/tasks-YYYYMMDD.db``.

:func:`run_backup` copies the live database with SQLite's online backup API
(``Connection.backup`` — consistent under WAL while the app keeps writing),
writes to a temp file first, then ``os.replace`` into place, and prunes the
folder to the newest :data:`KEEP` dated copies. Everything is logged.

:class:`BackupScheduler` is the in-app daily job — a plain thread started
from the webapp lifespan (same hook as the mirror): it runs once at startup
when today's file is missing, then every day at :data:`BACKUP_HOUR` local
time while the app is up (the loop wakes every 30 s and compares against
the next due time, so a sleeping PC just runs late rather than never).
``tasks backup`` is the same function from the CLI, for an external
scheduler (Task Scheduler / an app-launcher job) as an alternative — see
README "Backups".

Enabled only when ``mirror.backup_dir`` resolves to a path whose parent
exists (the leaf is created); otherwise the status carries the reason.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.db import db_path
from src.mirror import resolve_dir

logger = logging.getLogger(__name__)

KEEP = 30
BACKUP_HOUR = 3
FILE_RE = re.compile(r"^tasks-(\d{8})\.db$")


def backup_name(day: date | None = None) -> str:
    return f"tasks-{(day or date.today()).strftime('%Y%m%d')}.db"


def list_backups(dest_dir: Path) -> list[Path]:
    """Dated copies in ``dest_dir``, oldest first."""
    try:
        files = [p for p in dest_dir.iterdir() if p.is_file() and FILE_RE.match(p.name)]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.name)


def run_backup(source: Path, dest_dir: Path, *, keep: int = KEEP, day: date | None = None) -> Path:
    """Copy ``source`` to ``dest_dir/tasks-YYYYMMDD.db`` (consistent snapshot); prune to ``keep``."""
    if not source.exists():
        raise FileNotFoundError(f"database not found: {source}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / backup_name(day)
    tmp = dest_dir / (target.name + ".tmp")
    src = sqlite3.connect(source, timeout=30)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(tmp, target)
    pruned = 0
    for old in list_backups(dest_dir)[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            pruned += 1
        except OSError as exc:
            logger.warning("⚠️ backup: could not prune %s (%s)", old, exc)
    logger.info("✅ backup: %s → %s (%d bytes, %d pruned, keeping %d)", source, target, target.stat().st_size, pruned, keep)
    return target


def next_run_after(now: datetime, hour: int = BACKUP_HOUR) -> datetime:
    """The next ``hour:00`` local strictly after ``now``."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


class BackupScheduler:
    """Daily in-app backup thread; ``status()`` for ``/api/status``."""

    def __init__(self, config: AppConfig, *, source: Path | None = None, hour: int = BACKUP_HOUR, keep: int = KEEP) -> None:
        self.dir, self.reason = resolve_dir(config.mirror.backup_dir, config.placeholders, label="mirror.backup_dir")
        self.source = source
        self.hour = hour
        self.keep = keep
        self.last_run: str | None = None
        self.last_file: str | None = None
        self.last_error: str | None = None
        self.next_run: datetime | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if not self.enabled:
            logger.warning("⚠️ backup disabled — %s", self.reason)

    @property
    def enabled(self) -> bool:
        return self.dir is not None

    def status(self) -> dict[str, Any]:
        files = list_backups(self.dir) if self.dir else []
        latest = files[-1].name if files else None
        return {
            "enabled": self.enabled,
            "dir": str(self.dir) if self.dir else None,
            "reason": None if self.enabled else self.reason,
            "files": len(files) if self.dir else None,
            "last_file": self.last_file or latest,
            "last_run": self.last_run,
            "last_error": self.last_error,
            "next_run": self.next_run.isoformat(timespec="minutes") if self.next_run else None,
            "hour": self.hour,
            "keep": self.keep,
            "running": self._thread is not None and self._thread.is_alive(),
        }

    def run_now(self) -> Path | None:
        """One backup (also the scheduler's tick body); errors are recorded, never raised past here."""
        if self.dir is None:
            return None
        try:
            target = run_backup(self.source or db_path(), self.dir, keep=self.keep)
        except Exception as exc:  # noqa: BLE001 — a failed backup is a status, not a crash
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.error("❌ backup failed: %s", self.last_error)
            return None
        self.last_error = None
        self.last_run = datetime.now().astimezone().isoformat(timespec="seconds")
        self.last_file = target.name
        return target

    def due_now(self, now: datetime | None = None) -> bool:
        """Today's file is missing, or the scheduled time has passed since the last run."""
        if self.dir is None:
            return False
        now = now or datetime.now()
        if not (self.dir / backup_name(now.date())).exists():
            return True
        return self.next_run is not None and now >= self.next_run

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self.next_run = next_run_after(datetime.now(), self.hour)
        self._thread = threading.Thread(target=self._run, name="task-os-backup", daemon=True)
        self._thread.start()
        logger.info("ℹ️ backup: daily at %02d:00 → %s (next %s)", self.hour, self.dir, self.next_run.isoformat(timespec="minutes"))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        # startup: today's copy if missing (a PC that was off at 03:00 still gets one)
        if self.due_now():
            self.run_now()
        while not self._stop.wait(30):
            now = datetime.now()
            if self.due_now(now):
                self.run_now()
                self.next_run = next_run_after(now, self.hour)


__all__ = [
    "BACKUP_HOUR", "KEEP", "BackupScheduler", "backup_name", "list_backups", "next_run_after",
    "run_backup",
]
