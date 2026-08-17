"""SQLite lifecycle — one ``get_db()`` dependency, WAL, ``sqlite3.Row``.

Step 1 opens ``data/tasks.db`` and owns only the ``settings`` table with a
``schema_version`` marker; the task schema (tasks / links / comments /
activity / people / issue_refs / tasks_fts) arrives in Step 2 as migrations
keyed on that version. Every handler takes ``db: sqlite3.Connection =
Depends(get_db)`` — never a per-handler ``sqlite3.connect`` (the fleet's
one-dependency rule, project-scaffolding#96).

``TASKOS_DB_PATH`` overrides the file location — the e2e harness and unit
tests point at a temp file so no test ever touches the real database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "tasks.db"
DB_PATH_ENV = "TASKOS_DB_PATH"

#: Bumped by every migration; Step 1 ships the settings table only.
SCHEMA_VERSION = 1

_SETTINGS_DDL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


def db_path() -> Path:
    """The database file this process uses: env override → ``data/tasks.db``."""
    override = os.environ.get(DB_PATH_ENV, "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open ``path`` (default :func:`db_path`) with the fleet pragmas applied."""
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(path: Path | None = None) -> int:
    """Create the settings table + stamp ``schema_version``; return the version.

    Idempotent — safe to call at every startup. Later migrations key on the
    stored version and advance it in the same transaction.
    """
    conn = connect(path)
    try:
        conn.execute(_SETTINGS_DDL)
        row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        if current < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
            logger.info(
                "ℹ️ db: schema_version %d → %d at %s", current, SCHEMA_VERSION, path or db_path()
            )
        return SCHEMA_VERSION
    finally:
        conn.close()


def schema_version(conn: sqlite3.Connection) -> int | None:
    """The stored ``schema_version``, or ``None`` when the table is missing."""
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row["value"]) if row else None


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, closed in ``finally``."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
