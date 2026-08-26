"""``src/backup.py`` — dated copies, pruning, the daily scheduler's due logic."""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src import db as dbmod
from src import tasks_repo as repo
from src.backup import KEEP, BackupScheduler, backup_name, list_backups, next_run_after, run_backup
from src.config import load_config
from src.db import SCHEMA_VERSION
from tests.conftest import write_test_config


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db(path)
    conn = dbmod.connect(path)
    for i in range(5):
        repo.create_task(conn, f"task {i}")
    conn.close()
    return path


def test_run_backup_writes_a_consistent_dated_copy(db: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    target = run_backup(db, dest, day=date(2026, 8, 17))
    assert target == dest / "tasks-20260817.db" and target.exists()
    assert not (dest / "tasks-20260817.db.tmp").exists()
    copy = sqlite3.connect(target)
    try:
        assert copy.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 5
        assert copy.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
    finally:
        copy.close()
    # a second run the same day refreshes the same file (no duplicates)
    conn = dbmod.connect(db)
    repo.create_task(conn, "sixth")
    conn.close()
    run_backup(db, dest, day=date(2026, 8, 17))
    assert [p.name for p in list_backups(dest)] == ["tasks-20260817.db"]
    copy = sqlite3.connect(target)
    assert copy.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 6
    copy.close()


def test_run_backup_prunes_to_keep(db: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    dest.mkdir()
    for d in range(34):
        (dest / backup_name(date(2026, 7, 1) + timedelta(days=d))).write_bytes(b"x")
    (dest / "unrelated.db").write_bytes(b"x")
    assert len(list_backups(dest)) == 34
    run_backup(db, dest, day=date(2026, 8, 17))
    kept = list_backups(dest)
    assert len(kept) == KEEP and kept[-1].name == "tasks-20260817.db"
    assert (dest / "unrelated.db").exists()  # only dated copies are pruned


def test_run_backup_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_backup(tmp_path / "nope.db", tmp_path / "b")


def test_next_run_after() -> None:
    assert next_run_after(datetime(2026, 8, 17, 1, 0)) == datetime(2026, 8, 17, 3, 0)
    assert next_run_after(datetime(2026, 8, 17, 3, 0)) == datetime(2026, 8, 18, 3, 0)
    assert next_run_after(datetime(2026, 8, 17, 22, 30)) == datetime(2026, 8, 18, 3, 0)
    assert backup_name(date(2026, 1, 5)) == "tasks-20260105.db"


def test_scheduler_status_run_now_and_due_logic(db: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    cfg = write_test_config(tmp_path / "config.json", backup_dir=str(dest))
    s = BackupScheduler(load_config(cfg))
    assert s.enabled and s.dir == dest and dest.is_dir()
    st = s.status()
    assert st["enabled"] and st["files"] == 0 and st["last_file"] is None and st["next_run"] is None
    assert s.due_now(datetime(2026, 8, 17, 12, 0))  # today's copy missing
    target = s.run_now()
    assert target is not None and target.name == backup_name()
    st = s.status()
    assert st["last_file"] == target.name and st["last_run"] and st["last_error"] is None
    # today's file exists and no schedule yet → not due; past next_run → due
    assert not s.due_now(datetime.now())
    s.next_run = datetime.now().replace(microsecond=0)
    assert s.due_now(datetime.now())


def test_scheduler_disabled_reason_and_failed_run_is_a_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = BackupScheduler(load_config(write_test_config(tmp_path / "c.json")))
    assert not s.enabled and s.reason == "mirror.backup_dir not configured"
    assert s.status()["enabled"] is False and s.run_now() is None
    s.start()  # a no-op when disabled
    assert s.status()["running"] is False
    # enabled but the source DB is missing → recorded, not raised
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "missing.db"))
    s2 = BackupScheduler(load_config(write_test_config(tmp_path / "c2.json", backup_dir=str(tmp_path / "b"))))
    assert s2.run_now() is None and s2.last_error and "FileNotFoundError" in s2.last_error
    assert s2.status()["last_error"] == s2.last_error


def test_scheduler_thread_starts_and_stops(db: Path, tmp_path: Path) -> None:
    s = BackupScheduler(load_config(write_test_config(tmp_path / "c.json", backup_dir=str(tmp_path / "b"))))
    s.start()
    try:
        assert s.status()["running"] and s.next_run is not None
        # the startup pass writes today's copy
        deadline = datetime.now().timestamp() + 5
        while s.last_file is None and datetime.now().timestamp() < deadline:
            time.sleep(0.05)
        assert s.last_file == backup_name()
    finally:
        s.stop()
    assert s.status()["running"] is False
