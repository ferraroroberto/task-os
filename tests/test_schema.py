"""``src/schema.py`` — versioned migrations: fresh, upgrade from v1, idempotent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import db as dbmod
from src import schema

EXPECTED_TABLES = {
    "settings", "tasks", "links", "comments", "activity", "people", "issue_refs",
    "tasks_fts", "comments_fts", "mirror_state", "mirror_events",
}


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    return path


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_fresh_db_reaches_current_version(_temp_db: Path) -> None:
    assert dbmod.init_db() == schema.SCHEMA_VERSION == 10
    conn = dbmod.connect()
    try:
        assert schema.current_version(conn) == 10
        assert EXPECTED_TABLES <= schema.table_names(conn)
        idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"idx_tasks_parent", "idx_tasks_status", "idx_tasks_due"} <= idx
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_migrations_are_idempotent(_temp_db: Path) -> None:
    dbmod.init_db()
    conn = dbmod.connect()
    try:
        before = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        assert schema.migrate(conn) == 10
        assert schema.migrate(conn) == 10
        after = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        assert before == after
    finally:
        conn.close()
    assert dbmod.init_db() == 10


def test_upgrade_from_step1_v1_database(_temp_db: Path) -> None:
    """A Step-1 file (settings only, schema_version=1) is carried to the current version with the marker kept."""
    conn = _open(_temp_db)
    conn.executescript(
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO settings VALUES ('schema_version', '1');"
        "INSERT INTO settings VALUES ('theme', 'dark');"
    )
    conn.commit()
    conn.close()

    assert dbmod.init_db() == 10
    conn = dbmod.connect()
    try:
        assert schema.current_version(conn) == 10
        assert conn.execute("SELECT value FROM settings WHERE key='theme'").fetchone()[0] == "dark"
        assert "tasks" in schema.table_names(conn)
    finally:
        conn.close()


def test_v9_adds_the_recurrence_anchor_to_an_existing_database(_temp_db: Path) -> None:
    """A v8 file's recurring tasks survive and come out unanchored (#112)."""
    conn = _open(_temp_db)
    for target in range(1, 9):
        conn.executescript(schema.MIGRATIONS[target])
    conn.execute("INSERT INTO settings(key, value) VALUES ('schema_version', '8')")
    conn.execute(
        "INSERT INTO tasks(id, title, recurrence, due, created_at, updated_at)"
        " VALUES (1, 'Weekly review', 'weekly', '2026-08-21', 't', 't')"
    )
    conn.commit()
    conn.close()

    assert dbmod.init_db() == 10
    conn = dbmod.connect()
    try:
        row = conn.execute(
            "SELECT title, recurrence, recurrence_anchor FROM tasks WHERE id = 1"
        ).fetchone()
        assert tuple(row) == ("Weekly review", "weekly", None)
    finally:
        conn.close()


def test_failed_migration_leaves_previous_version(_temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dbmod.init_db()
    next_version = schema.SCHEMA_VERSION + 1
    monkeypatch.setitem(schema.MIGRATIONS, next_version, "CREATE TABLE ok(x); CREATE TABLE ok(x);")  # second stmt fails
    conn = dbmod.connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            schema.migrate(conn)
        assert schema.current_version(conn) == schema.SCHEMA_VERSION
        assert "ok" not in schema.table_names(conn)
        assert not conn.in_transaction
    finally:
        conn.close()


def test_v5_rebuild_keeps_links_and_accepts_ai_kind(_temp_db: Path) -> None:
    """A v4 database's links survive the #77 rebuild byte-for-byte (ids kept)
    and the widened CHECK accepts 'ai' while still rejecting an unknown kind."""
    conn = _open(_temp_db)
    for target in (1, 2, 3, 4):
        conn.executescript(schema.MIGRATIONS[target])
    conn.execute("INSERT INTO settings(key, value) VALUES ('schema_version', '4')")
    conn.execute(
        "INSERT INTO tasks(id, title, created_at, updated_at) VALUES (1, 'x', 't', 't')"
    )
    conn.execute(
        "INSERT INTO links(id, task_id, url, label, kind) VALUES (7, 1, 'https://example.com', 'a', 'web')"
    )
    conn.execute(
        "INSERT INTO links(id, task_id, url, label, kind) VALUES (9, 1, '{onedrive}/x', NULL, 'folder')"
    )
    conn.commit()
    conn.close()

    assert dbmod.init_db() == 10
    conn = dbmod.connect()
    try:
        rows = conn.execute("SELECT id, url, kind FROM links ORDER BY id").fetchall()
        assert [(r["id"], r["url"], r["kind"]) for r in rows] == [
            (7, "https://example.com", "web"), (9, "{onedrive}/x", "folder"),
        ]
        conn.execute(
            "INSERT INTO links(task_id, url, kind) VALUES (1, 'https://claude.ai/code/session_01A', 'ai')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO links(task_id, url, kind) VALUES (1, 'x', 'bogus')")
        idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_links_task" in idx
    finally:
        conn.close()


def test_check_constraints_reject_bad_enums(_temp_db: Path) -> None:
    dbmod.init_db()
    conn = dbmod.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks(title, status, created_at, updated_at) VALUES ('x', 'later', 't', 't')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks(title, type, created_at, updated_at) VALUES ('x', 'epic', 't', 't')"
            )
    finally:
        conn.close()


def test_v10_stamps_closed_at_on_cancelled_tasks(_temp_db: Path) -> None:
    """A v9 file's cancelled tasks gain ``done_at`` (#102): the time of their
    ``status → cancelled`` activity row when one was logged, ``updated_at``
    otherwise; done and open tasks are untouched."""
    conn = _open(_temp_db)
    for target in range(1, 10):
        conn.executescript(schema.MIGRATIONS[target])
    conn.execute("INSERT INTO settings(key, value) VALUES ('schema_version', '9')")
    rows = [
        (1, "Logged", "cancelled", "2026-08-20T10:00:00+02:00", None),
        (2, "Imported", "cancelled", "2026-08-01T08:00:00+02:00", None),
        (3, "Done", "done", "2026-07-02T08:00:00+02:00", "2026-07-01T08:00:00+02:00"),
        (4, "Open", "todo", "2026-07-02T08:00:00+02:00", None),
    ]
    conn.executemany(
        "INSERT INTO tasks(id, title, status, created_at, updated_at, done_at) VALUES (?, ?, ?, 'c', ?, ?)", rows
    )
    conn.execute(
        "INSERT INTO activity(task_id, ts, actor, field, old_value, new_value)"
        " VALUES (1, '2026-08-19T09:30:00+02:00', 'me', 'status', 'todo', 'cancelled')"
    )
    conn.commit()
    conn.close()

    assert dbmod.init_db() == 10
    conn = dbmod.connect()
    try:
        stamped = {r[0]: r[1] for r in conn.execute("SELECT id, done_at FROM tasks ORDER BY id").fetchall()}
        assert stamped == {
            1: "2026-08-19T09:30:00+02:00",   # the moment it was cancelled
            2: "2026-08-01T08:00:00+02:00",   # no log row → updated_at
            3: "2026-07-01T08:00:00+02:00",   # done: as it was
            4: None,
        }
    finally:
        conn.close()
