"""Domain operations over the task schema — the one place the rules live.

Every entry point takes an open ``sqlite3.Connection`` (row factory
``sqlite3.Row``) and returns plain dicts, so the REST routers, the ``tasks``
CLI in local mode, the fixture seed and the tests all share one code path.
Writes commit before returning.

Rules enforced here (plan §04):

- a task with children is a project — the ``project`` filter is "descendant
  of", the tree/breadcrumb are recursive CTEs, nesting depth is unlimited;
- ``move()`` refuses cycles (a task can't become its own descendant);
- every due / status / parent / priority (and title, type, recurrence,
  person, description, …) change writes an ``activity`` row with actor,
  field, old → new;
- ``done()`` on a recurring task rolls the *same* task's due forward from the
  due date (``src.dates.advance``) and logs the completion; a non-recurring
  task becomes ``done`` with ``done_at``;
- ``coding`` ⇔ an ``issue_refs`` row exists: attaching one sets the type,
  detaching reverts it, and setting ``type='coding'`` by hand is rejected;
- full-text search hits title / description / comment bodies via the two
  FTS5 indexes and returns a snippet per hit;
- an importer is idempotent on ``external_id`` (tasks, comments, people):
  :func:`import_task` creates with the source's own timestamps and logs ONE
  ``imported`` row, or updates the fields that changed on a re-run.

Timestamps come from :func:`now_iso` (local time, second precision, offset
kept) so a seed or a test can pin the clock with :func:`use_clock`.

Write hooks: every mutation ends by calling the registered write listeners
with the task ids it touched (:func:`add_write_listener`) — the markdown
mirror's debounced exporter (``src/mirror.py``) hangs off this so a change
made through the API, the CLI's local backend or an importer all reach the
mirror through the one layer that owns the rules.

Folder refs stay unresolved in the row (``{onedrive}/house`` — plan §04); the
one presentation hook, :func:`set_folder_resolver`, lets the app plug the
placeholder resolution in so every summary carries ``folder_resolved`` (this
server's absolute path, for display) and ``folder_url`` (the web link from a
``links(kind=folder)`` row, when one exists) — the UI never resolves a ref
client-side (Step 9).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

from src.dates import advance
from src.schema import (
    COMMENT_ORIGINS,
    ISSUE_PROVIDERS,
    LINK_KINDS,
    RECURRENCES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    TASK_TYPES,
)

logger = logging.getLogger(__name__)

DEFAULT_ACTOR = "me"

# Columns a client may set on create / update (everything else is derived).
_TASK_FIELDS = (
    "parent_id", "code", "title", "type", "status", "priority", "due", "recurrence",
    "description", "folder_ref", "next_action", "person_id",
)
_TASK_COLUMNS = ("id", *_TASK_FIELDS, "created_by", "created_at", "updated_at", "done_at")
_ENUMS: dict[str, tuple[str, ...]] = {
    "type": TASK_TYPES,
    "status": TASK_STATUSES,
    "priority": TASK_PRIORITIES,
    "recurrence": RECURRENCES,
}


# ---------------------------------------------------------------- errors


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


# ----------------------------------------------------------------- clock

_clock: Callable[[], datetime] = lambda: datetime.now().astimezone()  # noqa: E731


def now_iso() -> str:
    """Current local timestamp, ISO 8601, second precision, with offset."""
    return _clock().isoformat(timespec="seconds")


def today() -> date:
    return _clock().date()


@contextmanager
def use_clock(fn: Callable[[], datetime]) -> Iterator[None]:
    """Pin the repo clock (seed / tests): ``with use_clock(lambda: dt): ...``."""
    global _clock
    previous = _clock
    _clock = fn
    try:
        yield
    finally:
        _clock = previous


# ------------------------------------------------------- folder resolver

FolderResolver = Callable[[str], str | None]
_folder_resolver: FolderResolver | None = None


def set_folder_resolver(fn: FolderResolver | None) -> None:
    """Install (or clear, with ``None``) the ``ref → absolute path`` hook every
    summary calls for ``folder_resolved``. The app sets it from its config
    (``src.placeholders.resolve``); with none installed the field is ``None``
    — unknown, never a guessed path."""
    global _folder_resolver
    _folder_resolver = fn


# ----------------------------------------------------------- write hooks

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


# --------------------------------------------------------------- helpers


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


def _validate_due(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValidationError(f"due must be an ISO date YYYY-MM-DD (got {value!r})") from exc


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


def _summary(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    """A task row plus the cheap derived bits every list view wants."""
    out = dict(row)
    n = conn.execute("SELECT COUNT(*) FROM tasks WHERE parent_id = ?", (row["id"],)).fetchone()[0]
    out["child_count"] = int(n)
    out["is_project"] = out["child_count"] > 0
    ref = conn.execute("SELECT * FROM issue_refs WHERE task_id = ?", (row["id"],)).fetchone()
    out["issue_ref"] = _row(ref)
    if row.get("person_id") is not None:
        p = conn.execute("SELECT id, name FROM people WHERE id = ?", (row["person_id"],)).fetchone()
        out["person"] = _row(p)
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
        link = conn.execute(
            "SELECT url FROM links WHERE task_id = ? AND kind = 'folder'"
            " AND (url LIKE 'http://%' OR url LIKE 'https://%') ORDER BY id LIMIT 1",
            (row["id"],),
        ).fetchone()
        out["folder_url"] = link["url"] if link else None
    return out


# ------------------------------------------------------------------ tasks


def create_task(
    conn: sqlite3.Connection,
    title: str,
    *,
    actor: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Insert a task; log ``created``. Unknown fields are rejected."""
    title = (title or "").strip()
    if not title:
        raise ValidationError("title is required")
    unknown = set(fields) - set(_TASK_FIELDS) - {"title"}
    if unknown:
        raise ValidationError(f"unknown task field(s): {', '.join(sorted(unknown))}")

    values: dict[str, Any] = {
        "parent_id": None, "code": None, "type": "task", "status": "inbox",
        "priority": "none", "due": None, "recurrence": None, "description": "",
        "folder_ref": None, "next_action": None, "person_id": None,
    }
    values.update({k: v for k, v in fields.items() if k != "title"})
    values["title"] = title
    values["type"] = values["type"] or "task"
    values["status"] = values["status"] or "inbox"
    values["priority"] = values["priority"] or "none"
    values["description"] = values["description"] or ""
    values["recurrence"] = values["recurrence"] or None
    _validate_enum("type", values["type"])
    _validate_enum("status", values["status"])
    _validate_enum("priority", values["priority"])
    _validate_enum("recurrence", values["recurrence"], nullable=True)
    values["due"] = _validate_due(values["due"])
    if values["type"] == "coding":
        raise ValidationError(
            "type 'coding' is derived — attach an issue (PUT /api/tasks/{id}/issue) instead"
        )
    if values["parent_id"] is not None:
        _require_task(conn, int(values["parent_id"]))
    if values["person_id"] is not None:
        _require_person(conn, int(values["person_id"]))

    ts = now_iso()
    actor = actor or DEFAULT_ACTOR
    cur = conn.execute(
        """
        INSERT INTO tasks(parent_id, code, title, type, status, priority, due, recurrence,
                          description, folder_ref, next_action, person_id,
                          created_by, created_at, updated_at, done_at)
        VALUES (:parent_id, :code, :title, :type, :status, :priority, :due, :recurrence,
                :description, :folder_ref, :next_action, :person_id,
                :created_by, :ts, :ts, :done_at)
        """,
        {
            **values,
            "created_by": actor,
            "ts": ts,
            "done_at": ts if values["status"] == "done" else None,
        },
    )
    task_id = int(cur.lastrowid)
    _log(conn, task_id, actor, "created", None, title, ts)
    conn.commit()
    _touched(task_id, values["parent_id"])
    return get_task(conn, task_id)


def update_task(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    actor: str | None = None,
    **changes: Any,
) -> dict[str, Any]:
    """Apply field changes; one ``activity`` row per field that actually changed.

    ``parent_id`` goes through :func:`move` (cycle guard); ``type='coding'``
    is refused unless an issue_ref exists; ``status='done'`` stamps
    ``done_at`` (and leaving ``done`` clears it).
    """
    unknown = set(changes) - set(_TASK_FIELDS)
    if unknown:
        raise ValidationError(f"unknown task field(s): {', '.join(sorted(unknown))}")
    current = _require_task(conn, task_id)
    actor = actor or DEFAULT_ACTOR

    if "parent_id" in changes:
        new_parent = changes.pop("parent_id")
        new_parent = int(new_parent) if new_parent is not None else None
        if new_parent != current["parent_id"]:
            move(conn, task_id, new_parent, actor=actor)
            current = _require_task(conn, task_id)

    sets: dict[str, Any] = {}
    for field, value in changes.items():
        if field == "title":
            value = (value or "").strip()
            if not value:
                raise ValidationError("title cannot be empty")
        elif field in _ENUMS:
            if field == "recurrence":
                value = value or None
            _validate_enum(field, value, nullable=(field == "recurrence"))
        elif field == "due":
            value = _validate_due(value)
        elif field == "description":
            value = value or ""
        elif field == "person_id":
            value = int(value) if value is not None else None
            if value is not None:
                _require_person(conn, value)
        if value != current[field]:
            sets[field] = value

    if "type" in sets:
        has_ref = conn.execute(
            "SELECT 1 FROM issue_refs WHERE task_id = ?", (task_id,)
        ).fetchone() is not None
        if sets["type"] == "coding" and not has_ref:
            raise ValidationError("type 'coding' requires an issue_ref — attach an issue first")
        if sets["type"] != "coding" and has_ref:
            raise ValidationError("a task with an issue_ref is 'coding' — detach the issue first")

    if not sets:
        return get_task(conn, task_id)

    ts = now_iso()
    if "status" in sets:
        if sets["status"] == "done":
            sets["done_at"] = ts
        elif current["status"] == "done":
            sets["done_at"] = None
    sets["updated_at"] = ts
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    conn.execute(f"UPDATE tasks SET {assignments} WHERE id = :id", {**sets, "id": task_id})
    for field, value in sets.items():
        if field in ("updated_at", "done_at"):
            continue
        _log(conn, task_id, actor, field, current[field], value, ts)
    conn.commit()
    _touched(task_id)
    return get_task(conn, task_id)


def set_due(conn: sqlite3.Connection, task_id: int, due: str | date | None, *, actor: str | None = None) -> dict[str, Any]:
    return update_task(conn, task_id, actor=actor, due=due)


def set_status(conn: sqlite3.Connection, task_id: int, status: str, *, actor: str | None = None) -> dict[str, Any]:
    return update_task(conn, task_id, actor=actor, status=status)


def set_priority(conn: sqlite3.Connection, task_id: int, priority: str, *, actor: str | None = None) -> dict[str, Any]:
    return update_task(conn, task_id, actor=actor, priority=priority)


def move(
    conn: sqlite3.Connection,
    task_id: int,
    new_parent_id: int | None,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Re-parent ``task_id`` under ``new_parent_id`` (``None`` = root); logs ``parent``.

    Refuses a cycle: the new parent may not be the task itself or any of its
    descendants.
    """
    current = _require_task(conn, task_id)
    if new_parent_id is not None:
        new_parent_id = int(new_parent_id)
        if new_parent_id == task_id:
            raise CycleError(f"task {task_id} cannot be its own parent")
        _require_task(conn, new_parent_id)
        if new_parent_id in _descendant_ids(conn, task_id):
            raise CycleError(
                f"task {new_parent_id} is a descendant of task {task_id} — that would be a cycle"
            )
    if new_parent_id == current["parent_id"]:
        return get_task(conn, task_id)
    ts = now_iso()
    conn.execute(
        "UPDATE tasks SET parent_id = ?, updated_at = ? WHERE id = ?", (new_parent_id, ts, task_id)
    )
    _log(conn, task_id, actor, "parent", current["parent_id"], new_parent_id, ts)
    conn.commit()
    _touched(task_id, current["parent_id"], new_parent_id)
    return get_task(conn, task_id)


def done(conn: sqlite3.Connection, task_id: int, *, actor: str | None = None) -> dict[str, Any]:
    """Complete a task.

    Recurring → the same task rolls: ``due`` advances one cadence from the
    current due (from today when it had none), status is untouched, and the
    log gets ``done`` (old = the due that was completed) plus ``due`` old→new.
    Non-recurring → ``status='done'``, ``done_at`` stamped, ``status`` logged.
    """
    current = _require_task(conn, task_id)
    actor = actor or DEFAULT_ACTOR
    if current["recurrence"]:
        base = date.fromisoformat(current["due"]) if current["due"] else today()
        nxt = advance(base, current["recurrence"]).isoformat()
        ts = now_iso()
        conn.execute("UPDATE tasks SET due = ?, updated_at = ? WHERE id = ?", (nxt, ts, task_id))
        _log(conn, task_id, actor, "done", current["due"], nxt, ts)
        _log(conn, task_id, actor, "due", current["due"], nxt, ts)
        conn.commit()
        _touched(task_id)
        return get_task(conn, task_id)
    return set_status(conn, task_id, "done", actor=actor)


def delete_task(conn: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    """Delete a task **and its subtree** (FK cascade); returns ``{id, deleted}`` counts."""
    current = _require_task(conn, task_id)
    subtree = _descendant_ids(conn, task_id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    _touched(task_id, *subtree, current["parent_id"])
    return {"id": task_id, "deleted": 1 + len(subtree)}


_EXTERNAL_ID_TABLES = ("tasks", "comments", "people")


def find_by_external_id(
    conn: sqlite3.Connection, table: str, external_id: str
) -> dict[str, Any] | None:
    """The row of ``tasks`` / ``comments`` / ``people`` carrying ``external_id``, or ``None``."""
    if table not in _EXTERNAL_ID_TABLES:
        raise ValueError(f"no external_id on {table!r}")
    return _row(
        conn.execute(f"SELECT * FROM {table} WHERE external_id = ?", (external_id,)).fetchone()
    )


def import_task(
    conn: sqlite3.Connection,
    *,
    external_id: str,
    title: str,
    actor: str,
    created_at: str,
    updated_at: str,
    done_at: str | None = None,
    **fields: Any,
) -> tuple[dict[str, Any], str]:
    """Create-or-update a task keyed by ``external_id`` → ``(task, "created" | "updated" | "unchanged")``.

    First import: the row is inserted with the *source's* ``created_at`` /
    ``updated_at`` / ``done_at`` (not the import moment) and ONE activity row
    ``imported`` (new_value = ``external_id``) — never one row per field.
    Re-import: only the fields that differ go through :func:`update_task`
    (a genuine change in the source is logged per field like any other
    change); an identical page touches nothing.
    """
    existing = find_by_external_id(conn, "tasks", external_id)
    if existing is None:
        created = create_task(conn, title, actor=actor, **fields)
        task_id = created["id"]
        conn.execute(
            "UPDATE tasks SET external_id = ?, created_at = ?, updated_at = ?, done_at = ? "
            "WHERE id = ?",
            (external_id, created_at, updated_at, done_at, task_id),
        )
        # create_task logged "created" at the import moment; the import is the
        # one event worth recording, so that row becomes the single "imported".
        conn.execute(
            "UPDATE activity SET field = 'imported', new_value = ? "
            "WHERE task_id = ? AND field = 'created'",
            (external_id, task_id),
        )
        conn.commit()
        _touched(task_id)
        return get_task(conn, task_id), "created"

    task_id = existing["id"]
    diff = import_diff(existing, title=title, done_at=done_at, **fields)
    if not diff:
        return get_task(conn, task_id), "unchanged"
    new_done_at = diff.pop("done_at", existing.get("done_at"))
    if diff:
        update_task(conn, task_id, actor=actor, **diff)
    # update_task stamps done_at with the import moment on a status flip; the
    # source's own completion time wins (and a bare done_at drift is applied too).
    conn.execute("UPDATE tasks SET done_at = ? WHERE id = ?", (new_done_at, task_id))
    conn.commit()
    _touched(task_id)
    return get_task(conn, task_id), "updated"


def import_diff(existing: dict[str, Any], **incoming: Any) -> dict[str, Any]:
    """The subset of ``incoming`` that differs from the stored row (empty ≡ default)."""
    return {
        k: v for k, v in incoming.items()
        if _normalise(k, v) != _normalise(k, existing.get(k))
    }


def _normalise(field: str, value: Any) -> Any:
    if field == "description":
        return value or ""
    if field == "status":
        return value or "inbox"
    if field == "priority":
        return value or "none"
    if field == "due":
        return _validate_due(value)
    return value if value not in ("", None) else None


def get_task(conn: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    """The full detail view: task + links, comments, activity, children, breadcrumb."""
    row = _require_task(conn, task_id)
    out = _summary(conn, row)
    out["breadcrumb"] = _ancestors(conn, task_id)
    out["children"] = [
        _summary(conn, dict(r))
        for r in conn.execute(
            "SELECT * FROM tasks WHERE parent_id = ? ORDER BY id", (task_id,)
        ).fetchall()
    ]
    out["links"] = list_links(conn, task_id)
    out["comments"] = list_comments(conn, task_id)
    out["activity"] = list_activity(conn, task_id)
    return out


def _due_window(due: str | None) -> tuple[str | None, str | None, bool]:
    """``today|week|overdue|YYYY-MM-DD`` → (from, to, overdue_only)."""
    if not due:
        return None, None, False
    t = today()
    if due == "today":
        return t.isoformat(), t.isoformat(), False
    if due == "week":
        return t.isoformat(), (t + timedelta(days=7)).isoformat(), False
    if due == "overdue":
        return None, (t - timedelta(days=1)).isoformat(), True
    d = _validate_due(due)
    return d, d, False


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | list[str] | None = None,
    parent_id: int | str | None = None,
    project: int | None = None,
    due: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    type: str | None = None,
    person_id: int | None = None,
    q: str | None = None,
    include_closed: bool = False,
    limit: int | None = None,
    done_on: str | None = None,
) -> list[dict[str, Any]]:
    """Filtered flat list (summaries), ordered due → priority → id.

    - ``status``: one value or a list; ``"open"`` = not done/cancelled;
    - ``parent_id``: an id, or ``"root"`` for top-level tasks only;
    - ``project``: descendant-of ``project`` (any depth);
    - ``due``: ``today`` · ``week`` · ``overdue`` · a date; or ``due_from``/``due_to``;
    - ``q``: FTS over title/description/comments (see :func:`search`);
    - ``done_on``: a local calendar date — only tasks whose ``done_at`` falls
      on that day (the Board's *Done today* column; ``done_at`` is a local
      timestamp, so the boundary is local midnight).
    - closed (done/cancelled) tasks are hidden unless ``include_closed`` or a
      status filter names them.

    Each item is a summary plus ``breadcrumb`` (root → parent), ``root`` (the
    top ancestor — the Table's project column) and ``last_comment``.
    """
    where: list[str] = []
    args: list[Any] = []

    if status:
        values = [status] if isinstance(status, str) else list(status)
        if values == ["open"]:
            where.append("t.status NOT IN ('done', 'cancelled')")
        else:
            for v in values:
                _validate_enum("status", v)
            where.append(f"t.status IN ({', '.join('?' * len(values))})")
            args.extend(values)
    elif not include_closed:
        where.append("t.status NOT IN ('done', 'cancelled')")

    if parent_id is not None:
        if parent_id == "root":
            where.append("t.parent_id IS NULL")
        else:
            where.append("t.parent_id = ?")
            args.append(int(parent_id))

    if project is not None:
        ids = _descendant_ids(conn, int(project))
        if not ids:
            return []
        where.append(f"t.id IN ({', '.join('?' * len(ids))})")
        args.extend(ids)

    d_from, d_to, overdue = _due_window(due)
    d_from = _validate_due(due_from) or d_from
    d_to = _validate_due(due_to) or d_to
    if d_from:
        where.append("t.due >= ?")
        args.append(d_from)
    if d_to:
        where.append("t.due <= ?")
        args.append(d_to)
    if overdue:
        where.append("t.due IS NOT NULL")

    if type:
        _validate_enum("type", type)
        where.append("t.type = ?")
        args.append(type)

    if person_id is not None:
        where.append("t.person_id = ?")
        args.append(int(person_id))

    if done_on:
        where.append("substr(t.done_at, 1, 10) = ?")
        args.append(_validate_due(done_on))

    if q:
        hit_ids = [h["id"] for h in search(conn, q, limit=500)]
        if not hit_ids:
            return []
        where.append(f"t.id IN ({', '.join('?' * len(hit_ids))})")
        args.extend(hit_ids)

    sql = "SELECT t.* FROM tasks t"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (
        " ORDER BY t.due IS NULL, t.due, "
        "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, t.id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    items = [_summary(conn, dict(r)) for r in conn.execute(sql, args).fetchall()]
    _enrich_list(conn, items)
    return items


def _enrich_list(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    """Add what the Table needs per row — ``breadcrumb`` (root → parent),
    ``root`` (the top ancestor, i.e. the project column) and ``last_comment``
    — in three queries total instead of three per row."""
    if not items:
        return
    titles: dict[int, tuple[int | None, str]] = {
        r["id"]: (r["parent_id"], r["title"])
        for r in conn.execute("SELECT id, parent_id, title FROM tasks").fetchall()
    }
    ids = [it["id"] for it in items]
    last: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        f"""
        SELECT c.task_id, c.ts, c.author, c.body, c.origin
          FROM comments c
          JOIN (SELECT task_id, MAX(ts) AS ts, MAX(id) AS id FROM comments
                 WHERE task_id IN ({', '.join('?' * len(ids))}) GROUP BY task_id) m
            ON m.task_id = c.task_id AND m.id = c.id
        """,
        ids,
    ).fetchall():
        last[r["task_id"]] = {"ts": r["ts"], "author": r["author"], "body": r["body"], "origin": r["origin"]}
    for it in items:
        chain: list[dict[str, Any]] = []
        pid = it["parent_id"]
        seen: set[int] = set()
        while pid is not None and pid in titles and pid not in seen:
            seen.add(pid)
            chain.append({"id": pid, "title": titles[pid][1]})
            pid = titles[pid][0]
        chain.reverse()
        it["breadcrumb"] = chain
        it["root"] = chain[0] if chain else None
        it["last_comment"] = last.get(it["id"])


def tree(
    conn: sqlite3.Connection,
    root_id: int | None = None,
    *,
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    """Nested ``{...task, children: [...]}`` forest — the whole tree, or ``root_id``'s subtree.

    Closed (done/cancelled) tasks are pruned unless ``include_closed``; a
    closed project keeps showing while it has open descendants.
    """
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    by_parent: dict[int | None, list[dict[str, Any]]] = {}
    for r in rows:
        by_parent.setdefault(r["parent_id"], []).append(dict(r))

    def build(pid: int | None, depth: int) -> list[dict[str, Any]]:
        out = []
        for row in by_parent.get(pid, []):
            node = dict(row)
            node["depth"] = depth
            node["children"] = build(row["id"], depth + 1)
            node["child_count"] = len(by_parent.get(row["id"], []))
            node["is_project"] = node["child_count"] > 0
            closed = row["status"] in ("done", "cancelled")
            if closed and not include_closed and not node["children"]:
                continue
            out.append(node)
        return out

    if root_id is None:
        return build(None, 0)
    root = _require_task(conn, root_id)
    node = dict(root)
    node["depth"] = 0
    node["children"] = build(root_id, 1)
    node["child_count"] = len(by_parent.get(root_id, []))
    node["is_project"] = node["child_count"] > 0
    return [node]


# --------------------------------------------------------------- comments


def add_comment(
    conn: sqlite3.Connection,
    task_id: int,
    body: str,
    *,
    author: str | None = None,
    origin: str = "ui",
    ts: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Append a comment (thread order = ``ts``).

    ``ts`` / ``external_id`` are the import path: a historical comment keeps
    its original timestamp and source id (dedupe key) and does **not** bump
    the task's ``updated_at`` — only a fresh comment (no ``ts``) does.
    """
    _require_task(conn, task_id)
    body = (body or "").strip()
    if not body:
        raise ValidationError("comment body is required")
    if origin not in COMMENT_ORIGINS:
        raise ValidationError(f"origin must be one of {', '.join(COMMENT_ORIGINS)} (got {origin!r})")
    historical = ts is not None
    ts = ts or now_iso()
    cur = conn.execute(
        "INSERT INTO comments(task_id, author, ts, body, origin, external_id) VALUES (?,?,?,?,?,?)",
        (task_id, author or DEFAULT_ACTOR, ts, body, origin, external_id),
    )
    if not historical:
        conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (ts, task_id))
    conn.commit()
    _touched(task_id)
    return _row(conn.execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_comments(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    """Oldest first (thread order), ties broken by insertion."""
    return _rows(
        conn.execute(
            "SELECT * FROM comments WHERE task_id = ? ORDER BY ts, id", (task_id,)
        ).fetchall()
    )


def delete_comment(conn: sqlite3.Connection, comment_id: int) -> None:
    row = conn.execute("SELECT task_id FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise NotFound(f"comment {comment_id} not found")
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    _touched(row["task_id"])


# ------------------------------------------------------------------ links


def add_link(
    conn: sqlite3.Connection,
    task_id: int,
    url: str,
    *,
    label: str | None = None,
    kind: str = "web",
) -> dict[str, Any]:
    _require_task(conn, task_id)
    url = (url or "").strip()
    if not url:
        raise ValidationError("link url is required")
    if kind not in LINK_KINDS:
        raise ValidationError(f"kind must be one of {', '.join(LINK_KINDS)} (got {kind!r})")
    cur = conn.execute(
        "INSERT INTO links(task_id, url, label, kind) VALUES (?,?,?,?)", (task_id, url, label, kind)
    )
    conn.commit()
    _touched(task_id)
    return _row(conn.execute("SELECT * FROM links WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_links(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    return _rows(conn.execute("SELECT * FROM links WHERE task_id = ? ORDER BY id", (task_id,)).fetchall())


def remove_link(conn: sqlite3.Connection, task_id: int, link_id: int) -> None:
    cur = conn.execute("DELETE FROM links WHERE id = ? AND task_id = ?", (link_id, task_id))
    conn.commit()
    if cur.rowcount == 0:
        raise NotFound(f"link {link_id} on task {task_id} not found")
    _touched(task_id)


# --------------------------------------------------------------- activity


def list_activity(
    conn: sqlite3.Connection, task_id: int | None = None, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Newest first; all tasks when ``task_id`` is ``None``."""
    sql = "SELECT * FROM activity"
    args: list[Any] = []
    if task_id is not None:
        sql += " WHERE task_id = ?"
        args.append(task_id)
    sql += " ORDER BY ts DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _rows(conn.execute(sql, args).fetchall())


# ------------------------------------------------------------- issue refs


def set_issue_ref(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    provider: str,
    repo: str,
    number: int,
    url: str | None = None,
    state: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Attach (or replace) the issue on a task → the task becomes ``coding``."""
    current = _require_task(conn, task_id)
    if provider not in ISSUE_PROVIDERS:
        raise ValidationError(f"provider must be one of {', '.join(ISSUE_PROVIDERS)} (got {provider!r})")
    if not repo or not number:
        raise ValidationError("repo and number are required")
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO issue_refs(task_id, provider, repo, number, state, url, last_synced)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(task_id) DO UPDATE SET provider = excluded.provider, repo = excluded.repo,
            number = excluded.number, state = excluded.state, url = excluded.url,
            last_synced = excluded.last_synced
        """,
        (task_id, provider, repo, int(number), state, url, ts),
    )
    if current["type"] != "coding":
        conn.execute("UPDATE tasks SET type = 'coding', updated_at = ? WHERE id = ?", (ts, task_id))
        _log(conn, task_id, actor, "type", current["type"], "coding", ts)
    _log(conn, task_id, actor, "issue", None, f"{repo}#{number}", ts)
    conn.commit()
    _touched(task_id)
    return get_task(conn, task_id)


def remove_issue_ref(conn: sqlite3.Connection, task_id: int, *, actor: str | None = None) -> dict[str, Any]:
    """Detach the issue → the task reverts to ``task``."""
    current = _require_task(conn, task_id)
    ref = conn.execute("SELECT * FROM issue_refs WHERE task_id = ?", (task_id,)).fetchone()
    if ref is None:
        raise NotFound(f"task {task_id} has no issue_ref")
    ts = now_iso()
    conn.execute("DELETE FROM issue_refs WHERE task_id = ?", (task_id,))
    conn.execute("UPDATE tasks SET type = 'task', updated_at = ? WHERE id = ?", (ts, task_id))
    _log(conn, task_id, actor, "type", current["type"], "task", ts)
    _log(conn, task_id, actor, "issue", f"{ref['repo']}#{ref['number']}", None, ts)
    conn.commit()
    _touched(task_id)
    return get_task(conn, task_id)


# ----------------------------------------------------------------- people


def create_person(
    conn: sqlite3.Connection,
    name: str,
    *,
    email: str | None = None,
    avatar_path: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValidationError("name is required")
    cur = conn.execute(
        "INSERT INTO people(name, email, avatar_path, external_id) VALUES (?,?,?,?)",
        (name, email, avatar_path, external_id),
    )
    conn.commit()
    return get_person(conn, int(cur.lastrowid))


def get_person(conn: sqlite3.Connection, person_id: int) -> dict[str, Any]:
    p = _require_person(conn, person_id)
    n = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE person_id = ? AND status NOT IN ('done','cancelled')",
        (person_id,),
    ).fetchone()[0]
    p["open_tasks"] = int(n)
    return p


def list_people(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id FROM people ORDER BY name COLLATE NOCASE, id").fetchall()
    return [get_person(conn, r["id"]) for r in rows]


def update_person(conn: sqlite3.Connection, person_id: int, **changes: Any) -> dict[str, Any]:
    allowed = {"name", "email", "avatar_path", "external_id"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError(f"unknown person field(s): {', '.join(sorted(unknown))}")
    _require_person(conn, person_id)
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise ValidationError("name cannot be empty")
    if changes:
        assignments = ", ".join(f"{k} = :{k}" for k in changes)
        conn.execute(f"UPDATE people SET {assignments} WHERE id = :id", {**changes, "id": person_id})
        conn.commit()
        if "name" in changes:
            _touched(*_person_task_ids(conn, person_id))
    return get_person(conn, person_id)


def delete_person(conn: sqlite3.Connection, person_id: int) -> None:
    """Remove a person; tasks pointing at them keep going with ``person_id = NULL``."""
    _require_person(conn, person_id)
    affected = _person_task_ids(conn, person_id)
    conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
    conn.commit()
    _touched(*affected)


def _person_task_ids(conn: sqlite3.Connection, person_id: int) -> list[int]:
    rows = conn.execute("SELECT id FROM tasks WHERE person_id = ?", (person_id,)).fetchall()
    return [r["id"] for r in rows]


# ----------------------------------------------------------------- search


def _fts_query(q: str) -> str:
    """Turn free text into a safe FTS5 query: each word a prefix term, ANDed.

    Quotes every token so punctuation (``#``, ``-``, ``:``) can't break the
    MATCH grammar; a trailing ``*`` makes ``pass`` hit ``passport``.
    """
    tokens = [t.replace('"', '""') for t in q.split() if t.strip()]
    return " ".join(f'"{t}"*' for t in tokens)


def search(conn: sqlite3.Connection, q: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Full-text hits over title / description / comment bodies.

    Returns task summaries with ``snippet`` (the matched text, ``[`` ``]``
    marks) and ``matched_in`` (``title|description|comment``); a task that
    hits in several places appears once with the best-ranked location.
    """
    q = (q or "").strip()
    if not q:
        return []
    match = _fts_query(q)
    hits: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        """
        SELECT rowid AS id, bm25(tasks_fts) AS rank,
               snippet(tasks_fts, 0, '[', ']', '…', 12) AS s_title,
               snippet(tasks_fts, 1, '[', ']', '…', 12) AS s_desc,
               highlight(tasks_fts, 0, '[', ']') AS h_title
          FROM tasks_fts WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?
        """,
        (match, limit),
    ).fetchall():
        matched_in = "title" if "[" in (r["h_title"] or "") else "description"
        snippet = r["s_title"] if matched_in == "title" else r["s_desc"]
        hits[r["id"]] = {"rank": r["rank"], "matched_in": matched_in, "snippet": snippet}
    for r in conn.execute(
        """
        SELECT c.task_id AS id, bm25(comments_fts) AS rank,
               snippet(comments_fts, 0, '[', ']', '…', 12) AS s_body
          FROM comments_fts JOIN comments c ON c.id = comments_fts.rowid
         WHERE comments_fts MATCH ? ORDER BY rank LIMIT ?
        """,
        (match, limit),
    ).fetchall():
        prev = hits.get(r["id"])
        if prev is None or r["rank"] < prev["rank"]:
            hits[r["id"]] = {"rank": r["rank"], "matched_in": "comment", "snippet": r["s_body"]}
    if not hits:
        return []
    ordered = sorted(hits.items(), key=lambda kv: (kv[1]["rank"], kv[0]))[:limit]
    ids = [tid for tid, _ in ordered]
    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            f"SELECT * FROM tasks WHERE id IN ({', '.join('?' * len(ids))})", ids
        ).fetchall()
    }
    out = []
    for tid, meta in ordered:
        if tid not in rows:
            continue
        item = _summary(conn, rows[tid])
        item.update(meta)
        item["breadcrumb"] = _ancestors(conn, tid)
        out.append(item)
    return out


# ------------------------------------------------------------------ views

BOARD_COLUMNS = ("inbox", "todo", "doing", "standby", "done")


def board(
    conn: sqlite3.Connection,
    *,
    project: int | None = None,
    person_id: int | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """The Board's five buckets: ``inbox · todo · doing · standby · done``.

    The first four are the open statuses; ``done`` holds only tasks completed
    **today** (``done_at`` on the current local calendar day — an older done
    task never shows, and the boundary is local midnight, not UTC). Items are
    the same enriched summaries :func:`list_tasks` returns, in its order
    (due → priority → id). Two queries: one over the open statuses, one over
    today's done.
    """
    day = today().isoformat()
    columns: dict[str, list[dict[str, Any]]] = {key: [] for key in BOARD_COLUMNS}
    for item in list_tasks(
        conn, status=list(BOARD_COLUMNS[:-1]), project=project, person_id=person_id, q=q
    ):
        columns[item["status"]].append(item)
    columns["done"] = list_tasks(
        conn, status=["done"], project=project, person_id=person_id, q=q, done_on=day
    )
    return {"today": day, "columns": columns}


def _group_by_root(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``[{root, items}]`` — grouped by top ancestor (``None`` = no project);
    groups ordered by their earliest due, then root title; inside a group
    recurring tasks come first, then due → priority → id (the list order)."""
    groups: dict[int | None, dict[str, Any]] = {}
    for it in items:
        root = it.get("root")
        key = root["id"] if root else None
        g = groups.setdefault(key, {"root": root, "items": []})
        g["items"].append(it)
    for g in groups.values():
        g["items"].sort(key=lambda t: 0 if t.get("recurrence") else 1)  # stable: keeps due order
    return sorted(
        groups.values(),
        key=lambda g: (
            min(t["due"] for t in g["items"]),
            (g["root"] or {}).get("title", "").lower(),
        ),
    )


def today_view(conn: sqlite3.Connection, *, person_id: int | None = None) -> dict[str, Any]:
    """The Today tab: open tasks due ≤ today (overdue first, then today),
    grouped by root project with recurring tasks first, plus a *later this
    week* bucket (tomorrow … +7 days) in the same shape."""
    t = today()
    due = list_tasks(conn, status="open", due_to=t.isoformat(), person_id=person_id)
    week = list_tasks(
        conn,
        status="open",
        due_from=(t + timedelta(days=1)).isoformat(),
        due_to=(t + timedelta(days=7)).isoformat(),
        person_id=person_id,
    )
    iso = t.isoformat()
    return {
        "today": iso,
        "due": _group_by_root(due),
        "week": _group_by_root(week),
        "counts": {
            "overdue": sum(1 for it in due if it["due"] < iso),
            "today": sum(1 for it in due if it["due"] == iso),
            "week": len(week),
        },
    }


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts per table — the health/summary readout."""
    out: dict[str, int] = {}
    for table in ("tasks", "people", "comments", "links", "activity", "issue_refs"):
        out[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return out
