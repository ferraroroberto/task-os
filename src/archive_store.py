"""The archive run/item/correction rows — task-os's own record of what was filed.

Split out of ``src/archive_batch.py`` in #186: that module held three unrelated
concerns, and this is the one with no subprocess and no service state at all.
Every function here is a connection plus a few columns, so the router and the
tests read a run without importing the service that drives the archiver's CLI,
and ``ArchiveBatchService`` reaches its rows through the same public functions
they do.

These tables are this module's own, not task rules: nothing here touches a
task, so none of it belongs in ``src/tasks_repo.py``. Nothing here imports
``archive_batch``.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from src import archive_rank, clock
from src.archive_renumber import loads

logger = logging.getLogger(__name__)

#: The two states in which a mail is actually filed somewhere.
FILED_STATUSES = ("archived", "moved")
#: What a human may still act on.
REVIEWABLE_STATUSES = ("needs_review", "failed")

_ITEM_COLUMNS = (
    "id", "run_id", "message_id", "entry_id", "subject", "sender", "sent_at",
    "attachments", "candidates_json", "chosen_folder", "chosen_rank", "confidence",
    "reason", "date_prefix", "files_json", "sequence", "status", "error", "decided_at",
)
_RUN_COLUMNS = (
    "id", "started_at", "finished_at", "status", "planned", "archived",
    "needs_review", "failed", "error", "agreement",
)
_CORRECTION_COLUMNS = (
    "id", "item_id", "message_id", "subject", "sender", "suggested_folder",
    "chosen_folder", "hint", "created_at",
)
#: Bound on a hint a human types on the report screen (#159) before it becomes
#: a few-shot line in every later prompt.
MAX_HINT_CHARS = 500


def _row(row: sqlite3.Row | None, columns: tuple[str, ...]) -> dict[str, Any] | None:
    return {k: row[k] for k in columns} if row is not None else None


def _item_dict(row: sqlite3.Row) -> dict[str, Any]:
    """One item row as the API renders it: JSON columns parsed, flags real bools."""
    item = dict(_row(row, _ITEM_COLUMNS) or {})
    item["candidates"] = loads(item.pop("candidates_json"), [])
    item["files"] = loads(item.pop("files_json"), [])
    item["date_prefix"] = bool(item["date_prefix"])
    return item


def create_run(conn: sqlite3.Connection) -> dict[str, Any]:
    """Open a run row in ``running``; its id is what ``POST /api/archive/run`` returns."""
    cur = conn.execute(
        "INSERT INTO archive_runs (started_at, status) VALUES (?, 'running')",
        (clock.now_iso(),),
    )
    conn.commit()
    return get_run(conn, int(cur.lastrowid))  # type: ignore[return-value]


def finish_run(
    conn: sqlite3.Connection, run_id: int, *, status: str, error: str | None = None,
    agreement: float | None = None,
) -> dict[str, Any]:
    """Close a run, recomputing its counters from the rows it actually wrote.

    Derived rather than accumulated on purpose: the counters can then never
    disagree with the items, which are what the screen renders.
    """
    counts = {s: 0 for s in ("archived", "needs_review", "failed", "reverted", "moved")}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM archive_items WHERE run_id = ? GROUP BY status",
        (run_id,),
    ).fetchall():
        counts[str(row["status"])] = int(row["n"])
    planned = sum(counts.values())
    conn.execute(
        "UPDATE archive_runs SET finished_at = ?, status = ?, planned = ?, archived = ?, "
        "needs_review = ?, failed = ?, error = ?, agreement = ? WHERE id = ?",
        (
            clock.now_iso(), status, planned,
            counts["archived"] + counts["moved"], counts["needs_review"],
            counts["failed"], error, agreement, run_id,
        ),
    )
    conn.commit()
    return get_run(conn, run_id)  # type: ignore[return-value]


def insert_item(conn: sqlite3.Connection, run_id: int, **fields: Any) -> int:
    """Write one decided mail. Raises ``sqlite3.IntegrityError`` on a double filing."""
    payload = {"run_id": run_id, **fields}
    columns = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    cur = conn.execute(
        f"INSERT INTO archive_items ({columns}) VALUES ({marks})", tuple(payload.values())
    )
    conn.commit()
    return int(cur.lastrowid)


def update_item(conn: sqlite3.Connection, item_id: int, **fields: Any) -> dict[str, Any]:
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE archive_items SET {assignments} WHERE id = ?", (*fields.values(), item_id)
    )
    conn.commit()
    return get_item(conn, item_id)  # type: ignore[return-value]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM archive_runs WHERE id = ?", (run_id,)).fetchone()
    return _row(row, _RUN_COLUMNS)


def list_runs(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM archive_runs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [_row(r, _RUN_COLUMNS) for r in rows]  # type: ignore[misc]


def list_items(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM archive_items WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    return [_item_dict(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM archive_items WHERE id = ?", (item_id,)).fetchone()
    return _item_dict(row) if row is not None else None


def record_correction(
    conn: sqlite3.Connection, item: dict[str, Any], *, chosen_folder: str,
    hint: str | None = None,
) -> dict[str, Any]:
    """Remember that a human filed this mail here, not where the system said (#158).

    Everything the next prompt needs is **copied**, never joined: the run and
    its items may be deleted, the lesson stays. ``suggested_folder`` is what the
    system had settled on — the folder it chose, or, when it chose none, the
    archiver's own top candidate, which is the thing that was actually wrong.
    """
    candidates = item.get("candidates") or []
    top = next((c for c in candidates if isinstance(c, dict)), {})
    suggested = item.get("chosen_folder") or str(top.get("folder_path") or "") or None
    cleaned = (hint or "").strip()[:MAX_HINT_CHARS] or None
    cur = conn.execute(
        "INSERT INTO archive_corrections (item_id, message_id, subject, sender, "
        "suggested_folder, chosen_folder, hint, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            item.get("id"), str(item.get("message_id") or ""), item.get("subject"),
            item.get("sender"), suggested, chosen_folder, cleaned, clock.now_iso(),
        ),
    )
    conn.commit()
    logger.info(
        "ℹ️ archive: learned a correction — %s → %s%s",
        archive_rank.short_folder(str(suggested or "nothing")),
        archive_rank.short_folder(chosen_folder), " (with a hint)" if cleaned else "",
    )
    row = conn.execute(
        "SELECT * FROM archive_corrections WHERE id = ?", (int(cur.lastrowid),)
    ).fetchone()
    return _row(row, _CORRECTION_COLUMNS)  # type: ignore[return-value]


def recent_corrections(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    """The last ``limit`` corrections, **oldest first** — the prompt's few-shot block.

    Newest-first would reshuffle the whole example block every time one is
    added; oldest-first keeps the prompt stable apart from its tail.
    """
    if limit <= 0:
        return []
    rows = conn.execute(
        "SELECT * FROM archive_corrections ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [_row(r, _CORRECTION_COLUMNS) for r in reversed(rows)]  # type: ignore[misc]


def filed_message_ids(conn: sqlite3.Connection) -> set[str]:
    """Every ``message_id`` this database already has filed — the run's skip list."""
    marks = ", ".join("?" for _ in FILED_STATUSES)
    rows = conn.execute(
        f"SELECT DISTINCT message_id FROM archive_items WHERE status IN ({marks})",
        FILED_STATUSES,
    ).fetchall()
    return {str(r["message_id"]) for r in rows}


__all__ = [
    "FILED_STATUSES",
    "MAX_HINT_CHARS",
    "REVIEWABLE_STATUSES",
    "create_run",
    "filed_message_ids",
    "finish_run",
    "get_item",
    "get_run",
    "insert_item",
    "list_items",
    "list_runs",
    "recent_corrections",
    "record_correction",
    "update_item",
]
