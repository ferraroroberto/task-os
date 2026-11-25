"""The History feed: one person's own changes, newest first, grouped by day and task.

A read over two tables that already record every change: ``activity`` (one row
per field a write changed, old → new) and ``comments`` (each with its own
timestamp). Nothing is written here and no table is added — the feed is a view.

The day of a change is the first ten characters of its timestamp, a local
ISO stamp (``src.clock.now_iso``), the same rule as the done journal — never
UTC arithmetic. Inside a day, consecutive changes to the same task fold into
one group, so a re-plan of five fields reads as one entry that expands.

Every change carries a *kind*, the one vocabulary the filter chips name:
``dates`` (due or start moved), ``closed`` (a move into or out of a closed
status, or a recurring task's completion), ``status`` (between open statuses),
``priority``, ``moved`` (a new parent), ``comment``, and ``other`` for the
fields no chip names (title, notes, folder, type …), which only "all" shows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from typing import Any

from src.clock import today
from src.tasks.schema import CLOSED_STATUSES, ValidationError

KINDS: tuple[str, ...] = ("dates", "closed", "status", "priority", "moved", "comment", "other")

# The widest window one read may ask for: a page is days, not the whole history.
MAX_WINDOW_DAYS = 31

# A comment is shown as a line in the feed, never as the whole thread.
COMMENT_PREVIEW_CHARS = 280

_DATE_FIELDS = frozenset({"due", "starts"})
# Fields whose values are task ids: the feed names the task, not the number.
_TASK_ID_FIELDS = frozenset({"parent", "blocked_by", "blocks"})


def classify(field: str, old: str | None, new: str | None) -> str:
    """The kind one change belongs to (see the module docstring)."""
    if field == "comment":
        return "comment"
    if field in _DATE_FIELDS:
        return "dates"
    if field == "done":
        return "closed"
    if field == "status":
        return "closed" if (old in CLOSED_STATUSES) != (new in CLOSED_STATUSES) else "status"
    if field == "priority":
        return "priority"
    if field == "parent":
        return "moved"
    return "other"


def _parse_day(value: str | date | None, name: str, default: date) -> date:
    if value is None or value == "":
        return default
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be a date (YYYY-MM-DD), got {value!r}") from exc


def _changes(
    conn: sqlite3.Connection, actors: Sequence[str], where: str, args: Sequence[Any]
) -> list[dict[str, Any]]:
    """Every activity row and comment by ``actors`` matching ``where`` (over ``day``), newest first."""
    marks = ",".join("?" for _ in actors)
    activity = conn.execute(
        f"""
        SELECT a.id, a.task_id, a.ts, a.actor, a.field, a.old_value, a.new_value,
               t.title, t.status, 1 AS rank
        FROM activity a JOIN tasks t ON t.id = a.task_id
        WHERE a.actor IN ({marks}) AND {where.format(ts="a.ts")}
        """,
        (*actors, *args),
    ).fetchall()
    comments = conn.execute(
        f"""
        SELECT c.id, c.task_id, c.ts, c.author AS actor, 'comment' AS field,
               NULL AS old_value, c.body AS new_value, t.title, t.status, 0 AS rank
        FROM comments c JOIN tasks t ON t.id = c.task_id
        WHERE c.author IN ({marks}) AND {where.format(ts="c.ts")}
        """,
        (*actors, *args),
    ).fetchall()
    rows = [dict(r) for r in (*activity, *comments)]
    # one write logs several fields at one ts: id keeps them in write order
    rows.sort(key=lambda r: (r["ts"], r["rank"], r["id"]), reverse=True)
    return rows


def _has_older(conn: sqlite3.Connection, actors: Sequence[str], start: date) -> bool:
    """Whether any change by ``actors`` lies before ``start`` — one row probed per table."""
    marks = ",".join("?" for _ in actors)
    args = (*actors, start.isoformat())
    return any(
        conn.execute(
            f"SELECT 1 FROM {table} x JOIN tasks t ON t.id = x.task_id "
            f"WHERE x.{who} IN ({marks}) AND substr(x.ts, 1, 10) < ? LIMIT 1",
            args,
        ).fetchone()
        for table, who in (("activity", "actor"), ("comments", "author"))
    )


def _task_labels(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, str]:
    ids = {
        v for r in rows if r["field"] in _TASK_ID_FIELDS
        for v in (r["old_value"], r["new_value"]) if v and v.isdigit()
    }
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    found = conn.execute(f"SELECT id, title FROM tasks WHERE id IN ({marks})", sorted(ids)).fetchall()
    return {str(r["id"]): r["title"] for r in found}


def _entry(row: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    old, new = row["old_value"], row["new_value"]
    entry: dict[str, Any] = {
        "ts": row["ts"],
        "kind": classify(row["field"], old, new),
        "field": row["field"],
        "old": old,
        "new": new[:COMMENT_PREVIEW_CHARS] if row["field"] == "comment" and new else new,
        "actor": row["actor"],
    }
    if row["field"] in _TASK_ID_FIELDS:
        entry["old_label"] = labels.get(old or "")
        entry["new_label"] = labels.get(new or "")
    return entry


def group_changes(rows: list[dict[str, Any]], labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """``[{day, count, groups: [{task_id, title, status, entries}]}]`` from rows
    already ordered newest first: a new day starts a new day block, and inside
    a day a change to another task than the one before starts a new group, so
    only *consecutive* changes to one task fold together."""
    days: list[dict[str, Any]] = []
    for row in rows:
        day = row["ts"][:10]
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "count": 0, "groups": []})
        block = days[-1]
        groups = block["groups"]
        if not groups or groups[-1]["task_id"] != row["task_id"]:
            groups.append({"task_id": row["task_id"], "title": row["title"], "status": row["status"], "entries": []})
        groups[-1]["entries"].append(_entry(row, labels or {}))
        block["count"] += 1
    return days


def history(
    conn: sqlite3.Connection,
    actors: Sequence[str],
    *,
    day_from: str | date | None = None,
    day_to: str | date | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """The feed for ``actors`` between two local days (both inclusive; default
    today only), optionally one ``kind``. ``counts`` is per kind over the whole
    window whatever ``kind`` is, so the chips can say what each would show;
    ``older`` says whether anything by ``actors`` exists before ``day_from``."""
    if not actors:
        raise ValidationError("history needs at least one actor")
    if kind in ("", "all"):
        kind = None
    if kind is not None and kind not in KINDS:
        raise ValidationError(f"kind must be one of all, {', '.join(KINDS)} (got {kind!r})")
    end = _parse_day(day_to, "to", today())
    start = _parse_day(day_from, "from", end)
    if start > end:
        raise ValidationError("from must not be after to")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise ValidationError(f"a window is at most {MAX_WINDOW_DAYS} days")

    rows = _changes(conn, actors, "substr({ts}, 1, 10) BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
    counts = dict.fromkeys(KINDS, 0)
    kept = []
    for row in rows:
        k = classify(row["field"], row["old_value"], row["new_value"])
        counts[k] += 1
        if kind is None or k == kind:
            kept.append(row)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "actors": list(actors),
        "kind": kind or "all",
        "counts": {"all": len(rows), **counts},
        "older": _has_older(conn, actors, start),
        "days": group_changes(kept, _task_labels(conn, kept)),
    }
