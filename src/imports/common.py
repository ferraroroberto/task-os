"""What every one-shot importer shares: people by source id, the read-only plan connection, report formatting."""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src import tasks_repo as repo
from src.db import connect_read_only
from src.schema import SCHEMA_VERSION, current_version

logger = logging.getLogger("importers")


def ensure_person(conn: sqlite3.Connection, external_id: str, name: str, counts: Counter[str]) -> int:
    """The ``people`` id carrying ``external_id``; a same-named row with no source id adopts it, else one is created."""
    row = repo.find_by_external_id(conn, "people", external_id)
    if row:
        return int(row["id"])
    same = conn.execute(
        "SELECT id FROM people WHERE external_id IS NULL AND name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if same:
        repo.update_person(conn, int(same["id"]), external_id=external_id)
        counts["people_linked"] += 1
        return int(same["id"])
    counts["people_created"] += 1
    return int(repo.create_person(conn, name, external_id=external_id)["id"])


def open_for_plan(target_db: Path) -> sqlite3.Connection | None:
    """A read-only look at an existing database so a dry run can say what a write would create, update or leave alone.

    Plain SELECTs only: no migration, no pragma, no file created. ``None`` when
    there is no file yet, or it predates the current schema (nothing imported
    yet, as far as a plan can tell).
    """
    if not target_db.exists():
        return None
    conn = connect_read_only(target_db)
    conn.row_factory = sqlite3.Row
    if current_version(conn) < SCHEMA_VERSION:
        logger.info(
            "ℹ️ dry run: %s is at schema v%d (< %d) — plan assumes nothing imported yet",
            target_db, current_version(conn), SCHEMA_VERSION,
        )
        conn.close()
        return None
    return conn


def fmt_counts(counts: dict[Any, int]) -> str:
    """``key n · key n`` with the biggest count first; ``—`` when empty."""
    return " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))) or "—"


def plan_against(target_db: Path, plan_fn: Callable[[sqlite3.Connection | None, Any], Counter[str]], mapped: Any) -> Counter[str]:
    """``plan_fn(conn, mapped)`` over a read-only look at ``target_db`` (``None`` when there is nothing to look at)."""
    conn = open_for_plan(target_db)
    try:
        return plan_fn(conn, mapped)
    finally:
        if conn:
            conn.close()
