"""SQLite lifecycle — one ``get_db()`` dependency, WAL, ``sqlite3.Row``.

Opens the task database — ``<fleet runtime-data root>/task-os/tasks.db``, resolved
by ``src/runtime_data.py`` — and brings it to the current schema through the
versioned migrations in ``src/schema.py`` (``settings.schema_version`` is the
marker). Every handler takes ``db: sqlite3.Connection = Depends(get_db)`` —
never a per-handler ``sqlite3.connect`` (the fleet's one-dependency rule,
project-scaffolding#96).

``TASKOS_DB_PATH`` overrides the file location — the e2e harness and unit
tests point at a temp file so no test ever touches the real database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from src.runtime_data import runtime_db_path
from src.schema import SCHEMA_VERSION, migrate

logger = logging.getLogger(__name__)

# Default DB location: the fleet runtime-data root (``C:\sqlite\task-os\`` on
# Windows), not this repo's ``data/`` — an always-on service's fsync-backed
# writes should not land on whichever drive the repo was cloned onto, which here
# is a spinning HDD (project-scaffolding#243). This replaced the module's only
# use of ``PROJECT_ROOT``/``DATA_DIR``, so both are gone rather than left as
# dead module state; nothing imported them.
DEFAULT_DB_PATH = runtime_db_path("task-os", "tasks.db")
DB_PATH_ENV = "TASKOS_DB_PATH"

__all__ = ["SCHEMA_VERSION", "connect", "db_path", "get_db", "init_db", "schema_version"]


def db_path() -> Path:
    """The database file this process uses: env override → the fleet runtime-data root."""
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
    """Bring the database at ``path`` to :data:`SCHEMA_VERSION`; return the version.

    Idempotent — safe to call at every startup: :func:`src.schema.migrate`
    applies only the steps above the stored marker, each in its own
    transaction with its stamp.
    """
    conn = connect(path)
    try:
        version = migrate(conn)
        logger.debug("db: %s at schema v%d", path or db_path(), version)
        return version
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
