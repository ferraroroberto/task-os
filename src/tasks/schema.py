"""Shared foundation of the task domain layer — errors, column and enum constants,
the plug-in hooks (members, folder resolvers, write listeners), the row helpers and
validators, and the summary shapes every read returns.

Everything that reads a hook's module state lives here, so :func:`set_members`,
:func:`set_folder_resolver` and :func:`add_write_listener` write and read that state
in one module. Part of the ``src.tasks`` package, whose docstring holds the rules.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from src.clock import now_iso
from src.dates import AnchorError, IntervalError, normalise_anchor, normalise_interval
from src.schema import (
    CLOSED_SQL,
    CLOSED_STATUSES,
    RECURRENCES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    TASK_TYPES,
)

logger = logging.getLogger(__name__)


DEFAULT_ACTOR = "me"


# Columns a client may set on create / update (everything else is derived).
_TASK_FIELDS = (
    "parent_id", "code", "title", "type", "status", "priority", "due", "starts", "recurrence",
    "recurrence_anchor", "recurrence_interval", "description", "folder_ref",
    "next_action", "person_id", "owner",
)


#: Date columns — validated the same way, cleared by ``None`` / ``""``.
DATE_FIELDS = ("due", "starts")


_TASK_COLUMNS = ("id", *_TASK_FIELDS, "created_by", "created_at", "updated_at", "done_at")


_ENUMS: dict[str, tuple[str, ...]] = {
    "type": TASK_TYPES,
    "status": TASK_STATUSES,
    "priority": TASK_PRIORITIES,
    "recurrence": RECURRENCES,
}


class RepoError(Exception):
    """Base for domain errors the API maps to a JSON error body."""

    code = "repo_error"
    http_status = 400


class NotFound(RepoError):
    code = "not_found"
    http_status = 404


class ValidationError(RepoError):
    code = "validation_error"
    http_status = 422


class CycleError(ValidationError):
    code = "cycle"
    http_status = 409


class CaptureDismissed(RepoError):
    """A capture source replayed an id whose task was deleted (#254)."""

    code = "capture_dismissed"
    http_status = 410


#: The install's member ids, the owner first — ``config.people``, set by
#: the app's lifespan and the CLI's local backend. Unset = the one implicit
#: member ``me`` (``src.config.IMPLICIT_PERSON``), the install on its own.
_members: tuple[str, ...] = (DEFAULT_ACTOR,)


def set_members(ids: Sequence[str] | None) -> None:
    """Plug in the members an ``owner`` may name, the install owner first;
    ``None`` (or an empty list) restores the one implicit member."""
    global _members
    _members = tuple(str(i) for i in ids) if ids else (DEFAULT_ACTOR,)


def install_owner() -> str:
    """The member a NULL ``owner`` stands for — the first member."""
    return _members[0]


def _owner_of(row: dict[str, Any]) -> str:
    """A task row's effective owner: its own, else the install owner's."""
    return row.get("owner") or install_owner()


def _validate_owner(value: Any) -> str:
    if value not in _members:
        raise ValidationError(f"owner must be one of {', '.join(_members)} (got {value!r})")
    return str(value)


FolderResolver = Callable[[str], str | None]


_folder_resolver: FolderResolver | None = None


def set_folder_resolver(fn: FolderResolver | None) -> None:
    """Install (or clear, with ``None``) the ``ref → absolute path`` hook every
    summary calls for ``folder_resolved``. The app sets it from its config
    (``src.placeholders.resolve``); with none installed the field is ``None``
    — unknown, never a guessed path."""
    global _folder_resolver
    _folder_resolver = fn


_folder_web_resolver: FolderResolver | None = None


def set_folder_web_resolver(fn: FolderResolver | None) -> None:
    """Install (or clear) the ``ref → cloud web URL`` hook (#28). Only the
    fallback: an explicit ``links(kind=folder)`` web link on the task always
    wins. The app sets it from ``config.web_roots``
    (``src.placeholders.web_url``); with none installed, no derivation."""
    global _folder_web_resolver
    _folder_web_resolver = fn


WriteListener = Callable[[list[int]], None]


_write_listeners: list[WriteListener] = []


def add_write_listener(fn: WriteListener) -> None:
    """Register ``fn(task_ids)`` to run after every committed mutation."""
    if fn not in _write_listeners:
        _write_listeners.append(fn)


def remove_write_listener(fn: WriteListener) -> None:
    if fn in _write_listeners:
        _write_listeners.remove(fn)


def _touched(*task_ids: int | None) -> None:
    ids = [int(t) for t in task_ids if t is not None]
    if not ids:
        return
    for fn in list(_write_listeners):
        try:
            fn(ids)
        except Exception:  # noqa: BLE001 — a listener never breaks the write
            logger.exception("⚠️ write listener %r failed for tasks %s", fn, ids)


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def _rows(rs: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rs]


def _str(v: Any) -> str | None:
    return None if v is None else str(v)


def _validate_enum(field: str, value: Any, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    allowed = _ENUMS[field]
    if value not in allowed:
        raise ValidationError(f"{field} must be one of {', '.join(allowed)} (got {value!r})")


def _validate_anchor(recurrence: str | None, value: Any) -> str | None:
    """The canonical anchor for ``recurrence``; a bad one is a 422 (#112)."""
    try:
        return normalise_anchor(recurrence, value)
    except AnchorError as exc:
        raise ValidationError(str(exc)) from exc


def _carry_anchor(recurrence: str | None, value: Any) -> str | None:
    """The stored anchor kept across a *cadence* change, or dropped if it no longer fits.

    Switching Repeat from weekly-on-Friday to quarterly is a deliberate edit,
    not a mistake to reject — the anchor simply stops applying, so it is
    cleared (and activity-logged) rather than raised on.
    """
    try:
        return normalise_anchor(recurrence, value)
    except AnchorError:
        return None


def _validate_interval(recurrence: str | None, value: Any) -> int | None:
    """The stored "every N" for ``recurrence``; a bad one is a 422 (#229)."""
    try:
        return normalise_interval(recurrence, value)
    except IntervalError as exc:
        raise ValidationError(str(exc)) from exc


def _carry_interval(recurrence: str | None, value: Any) -> int | None:
    """The stored interval kept across a cadence change — :func:`_carry_anchor`'s twin.

    Every cadence takes an interval, so it survives a switch between them
    (the drawer shows "every 7" right beside the new cadence); only clearing
    Repeat drops it, since a task that does not repeat has nothing to count.
    """
    try:
        return normalise_interval(recurrence, value)
    except IntervalError:
        return None


def _validate_date(value: Any, field: str = "due") -> str | None:
    """An ISO date column's value, or ``None`` for "no date".

    The repo layer only ever sees ISO: the natural phrases (`tomorrow`, `fri`,
    `this weekend`) are resolved at the edges — ``app/webapp/routers/tasks.py``
    for HTTP, ``src/cli.py`` for the terminal — through ``src/dates.py``.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO date YYYY-MM-DD (got {value!r})") from exc


def _require_task(conn: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise NotFound(f"task {task_id} not found")
    return dict(row)


def _require_person(conn: sqlite3.Connection, person_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    if row is None:
        raise NotFound(f"person {person_id} not found")
    return dict(row)


def _log(
    conn: sqlite3.Connection,
    task_id: int,
    actor: str | None,
    field: str,
    old: Any,
    new: Any,
    ts: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activity(task_id, ts, actor, field, old_value, new_value) VALUES (?,?,?,?,?,?)",
        (task_id, ts or now_iso(), actor or DEFAULT_ACTOR, field, _str(old), _str(new)),
    )


def _ancestors(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    """Root → parent chain (excludes ``task_id`` itself)."""
    rows = conn.execute(
        """
        WITH RECURSIVE up(id, parent_id, title, depth) AS (
            SELECT t.id, t.parent_id, t.title, 0 FROM tasks t WHERE t.id = ?
            UNION ALL
            SELECT t.id, t.parent_id, t.title, up.depth + 1
              FROM tasks t JOIN up ON t.id = up.parent_id
        )
        SELECT id, title FROM up WHERE depth > 0 ORDER BY depth DESC
        """,
        (task_id,),
    ).fetchall()
    return _rows(rows)


def _descendant_ids(conn: sqlite3.Connection, task_id: int) -> list[int]:
    rows = conn.execute(
        """
        WITH RECURSIVE down(id) AS (
            SELECT id FROM tasks WHERE parent_id = ?
            UNION ALL
            SELECT t.id FROM tasks t JOIN down ON t.parent_id = down.id
        )
        SELECT id FROM down
        """,
        (task_id,),
    ).fetchall()
    return [r["id"] for r in rows]


def _blocked_reachable(conn: sqlite3.Connection, blocker_id: int) -> set[int]:
    """Every id ``blocker_id`` transitively blocks, following ``blocks`` edges."""
    rows = conn.execute(
        """
        WITH RECURSIVE down(id) AS (
            SELECT blocked_id FROM task_blocks WHERE blocker_id = ?
            UNION ALL
            SELECT tb.blocked_id FROM task_blocks tb JOIN down ON tb.blocker_id = down.id
        )
        SELECT id FROM down
        """,
        (blocker_id,),
    ).fetchall()
    return {r["id"] for r in rows}


def _currently_blocked_ids(conn: sqlite3.Connection) -> set[int]:
    """Every task with at least one still-open blocker — the one query
    :func:`list_tasks` filters on (#100)."""
    rows = conn.execute(
        "SELECT DISTINCT tb.blocked_id FROM task_blocks tb JOIN tasks t ON t.id = tb.blocker_id"
        f" WHERE t.status NOT IN ({CLOSED_SQL})"
    ).fetchall()
    return {r["blocked_id"] for r in rows}


def _blocker_rows(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    """``task_id``'s blockers — id/title/status, ordered by id."""
    return _rows(
        conn.execute(
            "SELECT t.id, t.title, t.status FROM task_blocks tb JOIN tasks t ON t.id = tb.blocker_id"
            " WHERE tb.blocked_id = ? ORDER BY t.id",
            (task_id,),
        ).fetchall()
    )


def _blocked_fields(blocked_by: list[dict[str, Any]]) -> dict[str, Any]:
    """The blocked-by keys every task shape carries (#100), from its blockers.

    The blockers themselves (id/title/status, for the drawer's list and the
    mirror export) plus the two derived facts every list view wants without
    walking edges itself — ``blocked`` (any blocker still open) and
    ``blocker_count`` (how many of them). One place for what "an open blocker"
    means: :func:`_summary` and :func:`tree` both read it from here.
    """
    open_blockers = [b for b in blocked_by if b["status"] not in CLOSED_STATUSES]
    return {"blocked_by": blocked_by, "blocked": bool(open_blockers), "blocker_count": len(open_blockers)}


def _summary_lookups(conn: sqlite3.Connection, ids: list[int]) -> dict[str, Any]:
    """The five row-scoped lookups :func:`_summary` needs, fetched once for a
    whole page of task ids — five queries for the page instead of five per row,
    the strategy :func:`_enrich_list` and :func:`tree` already use (#186)."""
    marks = ", ".join("?" * len(ids))
    children: dict[int, int] = {
        r["parent_id"]: int(r["n"])
        for r in conn.execute(
            f"SELECT parent_id, COUNT(*) AS n FROM tasks WHERE parent_id IN ({marks}) GROUP BY parent_id",
            ids,
        ).fetchall()
    }
    refs: dict[int, dict[str, Any]] = {
        r["task_id"]: dict(r)
        for r in conn.execute(f"SELECT * FROM issue_refs WHERE task_id IN ({marks})", ids).fetchall()
    }
    folder_urls: dict[int, str] = {}
    for r in conn.execute(
        f"SELECT task_id, url FROM links WHERE task_id IN ({marks}) AND kind = 'folder'"
        " AND (url LIKE 'http://%' OR url LIKE 'https://%') ORDER BY task_id, id",
        ids,
    ).fetchall():
        folder_urls.setdefault(r["task_id"], r["url"])  # ORDER BY id ⇒ the first link wins
    ai_links: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        f"SELECT task_id, url, label FROM links WHERE task_id IN ({marks}) AND kind = 'ai' ORDER BY task_id, id",
        ids,
    ).fetchall():
        ai_links.setdefault(r["task_id"], {"url": r["url"], "label": r["label"]})
    blockers: dict[int, list[dict[str, Any]]] = {}
    for r in conn.execute(
        "SELECT tb.blocked_id, t.id, t.title, t.status FROM task_blocks tb JOIN tasks t ON t.id = tb.blocker_id"
        f" WHERE tb.blocked_id IN ({marks}) ORDER BY tb.blocked_id, t.id",
        ids,
    ).fetchall():
        blockers.setdefault(r["blocked_id"], []).append(
            {"id": r["id"], "title": r["title"], "status": r["status"]}
        )
    return {
        "children": children,
        "refs": refs,
        "folder_urls": folder_urls,
        "ai_links": ai_links,
        "blockers": blockers,
    }


def _summaries(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """:func:`_summary` for a whole page of task rows.

    Same shape per row; the five row-scoped lookups come from
    :func:`_summary_lookups` instead of being re-queried per row, so a list
    view costs a fixed number of queries rather than five per row (#186). The
    people lookup is keyed on the rows' ``person_id`` set, so it runs only
    when some row is assigned.
    """
    if not rows:
        return []
    pre = _summary_lookups(conn, [int(r["id"]) for r in rows])
    person_ids = sorted({int(r["person_id"]) for r in rows if r.get("person_id") is not None})
    people: dict[int, dict[str, Any]] = {}
    if person_ids:
        people = {
            r["id"]: dict(r)
            for r in conn.execute(
                f"SELECT id, name FROM people WHERE id IN ({', '.join('?' * len(person_ids))})",
                person_ids,
            ).fetchall()
        }
    return [_summary_from(row, pre, people) for row in rows]


def _summary_from(
    row: dict[str, Any], pre: dict[str, Any], people: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """One row's summary, read out of the prefetched maps. The two folder
    resolvers stay per-row: they are caller-supplied callbacks, not queries."""
    out = dict(row)
    out["child_count"] = pre["children"].get(row["id"], 0)
    out["is_project"] = out["child_count"] > 0
    out["issue_ref"] = pre["refs"].get(row["id"])
    out["owner"] = _owner_of(row)
    if row.get("person_id") is not None:
        out["person"] = people.get(row["person_id"])
    else:
        out["person"] = None
    ref = row.get("folder_ref")
    out["folder_resolved"] = None
    out["folder_url"] = None
    if ref:
        if _folder_resolver is not None:
            try:
                out["folder_resolved"] = _folder_resolver(str(ref))
            except Exception:  # noqa: BLE001 — a resolver bug never breaks a list
                logger.exception("⚠️ folder resolver failed for %r", ref)
        out["folder_url"] = pre["folder_urls"].get(row["id"])
        if out["folder_url"] is None and _folder_web_resolver is not None:
            try:
                out["folder_url"] = _folder_web_resolver(str(ref))
            except Exception:  # noqa: BLE001 — a resolver bug never breaks a list
                logger.exception("⚠️ folder web resolver failed for %r", ref)
    # The AI-conversation chip on the row: first links(kind=ai), same
    # shape as folder_url — the UI never scans a task's links list-side.
    ai = pre["ai_links"].get(row["id"])
    out["ai_url"] = ai["url"] if ai else None
    out["ai_label"] = (ai["label"] if ai else None) or None
    out.update(_blocked_fields(pre["blockers"].get(row["id"], [])))
    return out


def _summary(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    """A task row plus the cheap derived bits every list view wants."""
    return _summaries(conn, [row])[0]
