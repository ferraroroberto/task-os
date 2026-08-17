"""``src/schema.py`` — versioned migrations: fresh, upgrade from v1, idempotent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import db as dbmod
from src import schema

EXPECTED_TABLES = {
    "settings", "tasks", "links", "comments", "activity", "people", "issue_refs",
    "tasks_fts", "comments_fts",
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
    assert dbmod.init_db() == schema.SCHEMA_VERSION == 3
    conn = dbmod.connect()
    try:
        assert schema.current_version(conn) == 3
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
        assert schema.migrate(conn) == 3
        assert schema.migrate(conn) == 3
        after = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        assert before == after
    finally:
        conn.close()
    assert dbmod.init_db() == 3


def test_upgrade_from_step1_v1_database(_temp_db: Path) -> None:
    """A Step-1 file (settings only, schema_version=1) is carried to v2 with the marker kept."""
    conn = _open(_temp_db)
    conn.executescript(
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO settings VALUES ('schema_version', '1');"
        "INSERT INTO settings VALUES ('theme', 'dark');"
    )
    conn.commit()
    conn.close()

    assert dbmod.init_db() == 3
    conn = dbmod.connect()
    try:
        assert schema.current_version(conn) == 3
        assert conn.execute("SELECT value FROM settings WHERE key='theme'").fetchone()[0] == "dark"
        assert "tasks" in schema.table_names(conn)
    finally:
        conn.close()


def test_failed_migration_leaves_previous_version(_temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dbmod.init_db()
    monkeypatch.setitem(schema.MIGRATIONS, 4, "CREATE TABLE ok(x); CREATE TABLE ok(x);")  # second stmt fails
    conn = dbmod.connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            schema.migrate(conn)
        assert schema.current_version(conn) == 3
        assert "ok" not in schema.table_names(conn)
        assert not conn.in_transaction
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
