"""Task writes — create, update, move, blockers, done, delete, the importer and
the one-way capture. Every entry point logs ``activity`` and ends by notifying
the write listeners with the task ids it touched.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date
from typing import Any

from src.clock import now_iso, today
from src.dates import next_due
from src.schema import (
    CAPTURE_STATUS,
    CLOSED_STATUSES,
    DEFAULT_STATUS,
)
from src.tasks.queries import find_by_external_id, get_task, would_cycle
from src.tasks.schema import (
    _ENUMS,
    _TASK_FIELDS,
    DATE_FIELDS,
    DEFAULT_ACTOR,
    CycleError,
    NotFound,
    RepoError,
    ValidationError,
    _blocked_reachable,
    _carry_anchor,
    _carry_interval,
    _descendant_ids,
    _log,
    _owner_of,
    _require_person,
    _require_task,
    _touched,
    _validate_anchor,
    _validate_date,
    _validate_enum,
    _validate_interval,
    _validate_owner,
)


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
        "parent_id": None, "code": None, "type": "task", "status": DEFAULT_STATUS,
        "priority": "none", "due": None, "starts": None, "recurrence": None,
        "recurrence_anchor": None, "recurrence_interval": None,
        "description": "", "folder_ref": None, "next_action": None, "person_id": None,
        "owner": None,
    }
    values.update({k: v for k, v in fields.items() if k != "title"})
    values["title"] = title
    values["type"] = values["type"] or "task"
    values["status"] = values["status"] or DEFAULT_STATUS
    values["priority"] = values["priority"] or "none"
    values["description"] = values["description"] or ""
    values["recurrence"] = values["recurrence"] or None
    _validate_enum("type", values["type"])
    _validate_enum("status", values["status"])
    _validate_enum("priority", values["priority"])
    _validate_enum("recurrence", values["recurrence"], nullable=True)
    values["recurrence_anchor"] = _validate_anchor(
        values["recurrence"], values["recurrence_anchor"]
    )
    values["recurrence_interval"] = _validate_interval(
        values["recurrence"], values["recurrence_interval"]
    )
    for f in DATE_FIELDS:
        values[f] = _validate_date(values[f], f)
    if values["type"] == "coding":
        raise ValidationError(
            "type 'coding' is derived — attach an issue (PUT /api/tasks/{id}/issue) instead"
        )
    if values["parent_id"] is not None:
        _require_task(conn, int(values["parent_id"]))
    if values["person_id"] is not None:
        _require_person(conn, int(values["person_id"]))
    if values["owner"] is not None:
        values["owner"] = _validate_owner(values["owner"])

    ts = now_iso()
    actor = actor or DEFAULT_ACTOR
    cur = conn.execute(
        """
        INSERT INTO tasks(parent_id, code, title, type, status, priority, due, starts, recurrence,
                          recurrence_anchor, recurrence_interval,
                          description, folder_ref, next_action, person_id, owner, created_by,
                          created_at, updated_at, done_at)
        VALUES (:parent_id, :code, :title, :type, :status, :priority, :due, :starts, :recurrence,
                :recurrence_anchor, :recurrence_interval, :description,
                :folder_ref,
                :next_action, :person_id, :owner, :created_by, :ts, :ts, :done_at)
        """,
        {
            **values,
            "created_by": actor,
            "ts": ts,
            "done_at": ts if values["status"] in CLOSED_STATUSES else None,
        },
    )
    assert cur.lastrowid is not None  # an INSERT always sets it
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

    ``parent_id`` is checked by :func:`move`'s cycle guard up front but written
    last, in the same transaction as the other fields — a rejected field never
    leaves the task re-parented; ``type='coding'`` is refused unless an
    issue_ref exists; ``status='done'`` stamps ``done_at`` (and leaving
    ``done`` clears it). ``owner`` is compared, and logged, as the effective
    owner (#476): naming the install owner on a task whose NULL already means
    them changes nothing.
    """
    unknown = set(changes) - set(_TASK_FIELDS)
    if unknown:
        raise ValidationError(f"unknown task field(s): {', '.join(sorted(unknown))}")
    current = _require_task(conn, task_id)
    actor = actor or DEFAULT_ACTOR

    reparent = False
    new_parent: int | None = None
    if "parent_id" in changes:
        new_parent = _check_reparent(conn, task_id, changes.pop("parent_id"))
        reparent = new_parent != current["parent_id"]

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
        elif field in DATE_FIELDS:
            value = _validate_date(value, field)
        elif field == "description":
            value = value or ""
        elif field == "person_id":
            value = int(value) if value is not None else None
            if value is not None:
                _require_person(conn, value)
        elif field == "owner":
            value = _validate_owner(value)
            if value != _owner_of(current):
                sets[field] = value
            continue
        if value != current[field]:
            sets[field] = value

    # Snooze (#486): `starts` pushed past `due` would hide the task until the
    # day after it was due. The start carries the due with it — unless the
    # caller named `due` itself, which is their own pair and stays as sent.
    if sets.get("starts") and "due" not in changes:
        due = current["due"]
        if due and due < sets["starts"]:
            sets["due"] = sets["starts"]

    # Recurrence anchor (#112) — resolved against the cadence the task *ends*
    # with, so PATCHing both at once validates the pair, and changing only the
    # cadence re-checks the anchor already stored (dropping it when the new
    # cadence cannot carry it) instead of leaving a stale fixed day behind.
    if "recurrence" in sets or "recurrence_anchor" in changes:
        cadence = sets.get("recurrence", current["recurrence"])
        anchor = (
            _validate_anchor(cadence, changes["recurrence_anchor"])
            if "recurrence_anchor" in changes
            else _carry_anchor(cadence, current["recurrence_anchor"])
        )
        if anchor != current["recurrence_anchor"]:
            sets["recurrence_anchor"] = anchor
        else:
            sets.pop("recurrence_anchor", None)
    # Interval (#229) — the same end-state resolution as the anchor above.
    if "recurrence" in sets or "recurrence_interval" in changes:
        cadence = sets.get("recurrence", current["recurrence"])
        interval = (
            _validate_interval(cadence, changes["recurrence_interval"])
            if "recurrence_interval" in changes
            else _carry_interval(cadence, current["recurrence_interval"])
        )
        if interval != current["recurrence_interval"]:
            sets["recurrence_interval"] = interval
        else:
            sets.pop("recurrence_interval", None)

    if "type" in sets:
        has_ref = conn.execute(
            "SELECT 1 FROM issue_refs WHERE task_id = ?", (task_id,)
        ).fetchone() is not None
        if sets["type"] == "coding" and not has_ref:
            raise ValidationError("type 'coding' requires an issue_ref — attach an issue first")
        if sets["type"] != "coding" and has_ref:
            raise ValidationError("a task with an issue_ref is 'coding' — detach the issue first")

    if not sets and not reparent:
        return get_task(conn, task_id)

    ts = now_iso()
    if reparent:
        sets["parent_id"] = new_parent
    if "status" in sets:
        # closed-at (#102): any move into done / cancelled stamps the moment,
        # any move back out clears it (a reopened task has no closing day)
        if sets["status"] in CLOSED_STATUSES:
            sets["done_at"] = ts
        elif current["status"] in CLOSED_STATUSES:
            sets["done_at"] = None
    sets["updated_at"] = ts
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    conn.execute(f"UPDATE tasks SET {assignments} WHERE id = :id", {**sets, "id": task_id})
    for field, value in sets.items():
        if field in ("updated_at", "done_at"):
            continue
        old = _owner_of(current) if field == "owner" else current[field]
        _log(conn, task_id, actor, "parent" if field == "parent_id" else field, old, value, ts)
    conn.commit()
    _touched(task_id, *((current["parent_id"], new_parent) if reparent else ()))
    return get_task(conn, task_id)


def set_due(conn: sqlite3.Connection, task_id: int, due: str | date | None, *, actor: str | None = None) -> dict[str, Any]:
    return update_task(conn, task_id, actor=actor, due=due)


def set_starts(conn: sqlite3.Connection, task_id: int, starts: str | date | None, *, actor: str | None = None) -> dict[str, Any]:
    """Set (or clear, with ``None``) the day the task starts mattering — what
    the Today row's snooze control and ``tasks starts`` both do (#87)."""
    return update_task(conn, task_id, actor=actor, starts=starts)


def set_status(conn: sqlite3.Connection, task_id: int, status: str, *, actor: str | None = None) -> dict[str, Any]:
    return update_task(conn, task_id, actor=actor, status=status)


def set_priority(conn: sqlite3.Connection, task_id: int, priority: str, *, actor: str | None = None) -> dict[str, Any]:
    return update_task(conn, task_id, actor=actor, priority=priority)


def bulk_update(
    conn: sqlite3.Connection,
    task_ids: Iterable[int],
    *,
    actor: str | None = None,
    complete: bool = False,
    **changes: Any,
) -> list[dict[str, Any]]:
    """Apply the same change to many tasks — one result row per id, in order.

    The bulk twin of the single-task path, and deliberately nothing more: each
    id goes through :func:`update_task` (or :func:`done` when ``complete``),
    so the activity rows, the ``done_at`` stamp, the recurrence roll and the
    mirror hooks are identical to editing the tasks one by one. ``complete``
    is the bulk form of the row status select's ``complete`` pseudo-status
    (issue #54) — it rolls a recurring task's due instead of closing it;
    ``status='done'`` stays a plain field update, closed for good.

    **Every id is attempted.** A :class:`RepoError` on one id becomes that
    id's failure row and the loop goes on — a batch is not a transaction, and
    a caller that dropped the rest of the selection because id 3 was deleted
    in another tab would be worse than one that reports which id failed.
    Duplicate ids collapse to the first occurrence so a double-click cannot
    roll a recurring task's due twice.

    :returns: ``[{"id", "ok": True, "task": …} | {"id", "ok": False, "error": {"code", "message"}}]``
    """
    seen: set[int] = set()
    results: list[dict[str, Any]] = []
    for raw in task_ids:
        task_id = int(raw)
        if task_id in seen:
            continue
        seen.add(task_id)
        try:
            task = (
                done(conn, task_id, actor=actor)
                if complete
                else update_task(conn, task_id, actor=actor, **changes)
            )
        except RepoError as exc:
            results.append(
                {"id": task_id, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
            )
        else:
            results.append({"id": task_id, "ok": True, "task": task})
    return results


def _check_reparent(
    conn: sqlite3.Connection, task_id: int, new_parent_id: int | str | None
) -> int | None:
    """Validate a proposed parent with no side effects; returns it as an int/None."""
    if new_parent_id is None:
        return None
    new_parent_id = int(new_parent_id)
    # Self and descendant stay two messages: "you picked yourself" and
    # "you picked something below you" have different fixes.
    if new_parent_id == task_id:
        raise CycleError(f"task {task_id} cannot be its own parent")
    _require_task(conn, new_parent_id)
    if would_cycle(conn, task_id, new_parent_id):
        raise CycleError(
            f"task {new_parent_id} is a descendant of task {task_id} — that would be a cycle"
        )
    return new_parent_id


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
    new_parent_id = _check_reparent(conn, task_id, new_parent_id)
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


def add_blocker(
    conn: sqlite3.Connection,
    task_id: int,
    blocker_id: int,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """``blocker_id`` must close before ``task_id`` counts as unblocked (#100).

    Refuses a self-block and a cycle: ``blocker_id`` may not be (transitively)
    blocked by ``task_id`` already — a separate graph from the parent tree, so
    a blocks-edge may freely cross subtrees; only its own edges can cycle.
    Logs ``blocked_by`` on ``task_id`` and ``blocks`` on ``blocker_id`` (#100
    asks for both sides to tell the story); idempotent on a duplicate edge.
    """
    task_id = int(task_id)
    blocker_id = int(blocker_id)
    if blocker_id == task_id:
        raise CycleError(f"task {task_id} cannot block itself")
    _require_task(conn, task_id)
    _require_task(conn, blocker_id)
    if blocker_id in _blocked_reachable(conn, task_id):
        raise CycleError(
            f"task {task_id} already (transitively) blocks task {blocker_id} — that would be a cycle"
        )
    exists = conn.execute(
        "SELECT 1 FROM task_blocks WHERE blocker_id = ? AND blocked_id = ?", (blocker_id, task_id)
    ).fetchone()
    if exists:
        return get_task(conn, task_id)
    ts = now_iso()
    conn.execute(
        "INSERT INTO task_blocks(blocker_id, blocked_id) VALUES (?, ?)", (blocker_id, task_id)
    )
    _log(conn, task_id, actor, "blocked_by", None, blocker_id, ts)
    _log(conn, blocker_id, actor, "blocks", None, task_id, ts)
    conn.commit()
    _touched(task_id, blocker_id)
    return get_task(conn, task_id)


def remove_blocker(
    conn: sqlite3.Connection,
    task_id: int,
    blocker_id: int,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Drop the ``blocker_id → task_id`` edge; logs on both sides like :func:`add_blocker`."""
    task_id = int(task_id)
    blocker_id = int(blocker_id)
    cur = conn.execute(
        "DELETE FROM task_blocks WHERE blocker_id = ? AND blocked_id = ?", (blocker_id, task_id)
    )
    if cur.rowcount == 0:
        raise NotFound(f"task {task_id} is not blocked by task {blocker_id}")
    ts = now_iso()
    _log(conn, task_id, actor, "blocked_by", blocker_id, None, ts)
    _log(conn, blocker_id, actor, "blocks", task_id, None, ts)
    conn.commit()
    _touched(task_id, blocker_id)
    return get_task(conn, task_id)


def done(conn: sqlite3.Connection, task_id: int, *, actor: str | None = None) -> dict[str, Any]:
    """Complete a task.

    Recurring → the same task rolls: ``due`` moves to the next occurrence
    after both the completed due and today (from today when it had none),
    status is untouched, and the log gets ``done`` (old = the due that was
    completed) plus ``due`` old→new. A ``recurrence_anchor`` makes that
    occurrence a fixed day — a Friday task completed on Monday lands on the
    coming Friday, not the next Monday — and the catch-up means an overdue
    task never rolls onto another overdue date (#112).
    Non-recurring → ``status='done'``, ``done_at`` stamped, ``status`` logged.

    The roll deliberately leaves ``starts`` alone (#87). A start date is an
    absolute one-time gate, not a cadence: it always eventually arrives, so a
    snoozed recurring task wakes on its start day and rolls normally from then
    on. Advancing it with the due would make the gate chase the task forever.
    """
    current = _require_task(conn, task_id)
    actor = actor or DEFAULT_ACTOR
    if current["recurrence"]:
        base = date.fromisoformat(current["due"]) if current["due"] else None
        nxt = next_due(
            base,
            current["recurrence"],
            current["recurrence_anchor"],
            current["recurrence_interval"],
            today=today(),
        ).isoformat()
        ts = now_iso()
        conn.execute("UPDATE tasks SET due = ?, updated_at = ? WHERE id = ?", (nxt, ts, task_id))
        _log(conn, task_id, actor, "done", current["due"], nxt, ts)
        _log(conn, task_id, actor, "due", current["due"], nxt, ts)
        conn.commit()
        _touched(task_id)
        return get_task(conn, task_id)
    return set_status(conn, task_id, "done", actor=actor)


def delete_task(
    conn: sqlite3.Connection, task_id: int, *, actor: str | None = None
) -> dict[str, Any]:
    """Delete a task **and its subtree** (FK cascade); returns ``{id, deleted}`` counts.

    A task the doomed subtree blocks loses that blocker: the ``task_blocks``
    row cascades with the row, but a still-alive dependent gets an explicit
    ``blocked_by`` old→None activity row (#100) so its own log says why it
    unblocked rather than the edge just vanishing silently.
    """
    current = _require_task(conn, task_id)
    subtree = _descendant_ids(conn, task_id)
    doomed = {task_id, *subtree}
    freed = conn.execute(
        f"SELECT DISTINCT blocker_id, blocked_id FROM task_blocks"
        f" WHERE blocker_id IN ({', '.join('?' * len(doomed))})",
        list(doomed),
    ).fetchall()
    ts = now_iso()
    survivors: set[int] = set()
    for r in freed:
        if r["blocked_id"] not in doomed:
            _log(conn, r["blocked_id"], actor, "blocked_by", r["blocker_id"], None, ts)
            survivors.add(r["blocked_id"])
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    _touched(task_id, *subtree, current["parent_id"], *survivors)
    return {"id": task_id, "deleted": 1 + len(subtree)}


def bulk_delete(conn: sqlite3.Connection, task_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Delete many tasks — one result row per id, in order (issue #121).

    The bulk twin of :func:`delete_task`, shaped like :func:`bulk_update`:
    **every id is attempted**, a :class:`RepoError` on one id is that id's
    failure row, duplicates collapse to the first occurrence. One wrinkle is
    the selection that holds a parent *and* one of its children: the parent's
    cascade takes the child first, so the child's row reads ``ok: True,
    deleted: 0`` (it went with its parent) rather than a spurious not-found —
    only an id that is genuinely gone for another reason is a named failure.

    :returns: ``[{"id", "ok": True, "deleted": n} | {"id", "ok": False, "error": {"code", "message"}}]``
    """
    seen: set[int] = set()
    gone: set[int] = set()
    results: list[dict[str, Any]] = []
    for raw in task_ids:
        task_id = int(raw)
        if task_id in seen:
            continue
        seen.add(task_id)
        if task_id in gone:
            results.append({"id": task_id, "ok": True, "deleted": 0})
            continue
        subtree = _descendant_ids(conn, task_id)   # [] for an id that is not there
        try:
            r = delete_task(conn, task_id)
        except RepoError as exc:
            results.append(
                {"id": task_id, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
            )
        else:
            gone.update(subtree)
            results.append({"id": task_id, "ok": True, "deleted": r["deleted"]})
    return results


def capture_task(
    conn: sqlite3.Connection,
    *,
    external_id: str,
    title: str,
    actor: str,
    **fields: Any,
) -> tuple[dict[str, Any] | None, str]:
    """Land a task from a capture source, once → ``(task, "created" | "unchanged")`` or ``(None, "dismissed")``.

    The rule behind every inbound channel (#98): flagged emails polled from the
    archiver's index, a WhatsApp message the radar marks, anything later. It is
    :func:`import_task`'s one-way twin — an import *reconciles* (a changed
    source field lands on the task), a capture only ever **lands**:

    - ``external_id`` already known → that task comes back untouched, with no
      write and no activity row. Un-flagging the email, editing the title here,
      moving the task on: none of it is undone by the next pass. A captured
      task, once real, is yours.
    - ``external_id`` captured before but its task since **deleted** →
      ``(None, "dismissed")``, no write (#254). Deleting is yours too: the
      source keeps offering the id (an archived ``.msg`` keeps its flag), and
      ``capture_keys`` — which outlives the row — is what stops it coming back.
    - otherwise the task is created normally (``created`` activity, ``status``
      ``inbox`` unless a caller says otherwise — named here rather than
      inherited, because :data:`DEFAULT_STATUS` is now ``todo``), stamped
      with ``external_id``, and its key recorded in ``capture_keys``.

    The stamp is a second statement rather than a ``create_task`` field because
    ``external_id`` is not a task *field* (it is not in ``_TASK_FIELDS``, so it
    is not settable through the API or loggable as a change) — the same shape
    :func:`import_task` uses. Two passes racing on one source id collide on the
    v3 partial unique index; the loser reads the winner's row back and reports
    ``unchanged``, so a retry can never double-create.
    """
    external_id = (external_id or "").strip()
    if not external_id:
        raise ValidationError("external_id is required to capture a task")
    existing = find_by_external_id(conn, "tasks", external_id)
    if existing is not None:
        return get_task(conn, int(existing["id"])), "unchanged"
    if conn.execute(
        "SELECT 1 FROM capture_keys WHERE external_id = ?", (external_id,)
    ).fetchone() is not None:
        return None, "dismissed"

    # Inbox is named here rather than inherited from `create_task`'s default:
    # that default is now "todo" (#148, what a *hand-made* task means), and the
    # arrivals tray must not follow it. A caller that says otherwise still wins.
    # `not fields.get(...)` rather than `setdefault`: a caller with no opinion
    # can express it as an absent key, a `None` or a blank, and all three mean
    # the same thing here.
    if not fields.get("status"):
        fields["status"] = CAPTURE_STATUS
    created = create_task(conn, title, actor=actor, **fields)
    task_id = int(created["id"])
    try:
        conn.execute("UPDATE tasks SET external_id = ? WHERE id = ?", (external_id, task_id))
        conn.execute(
            "INSERT OR IGNORE INTO capture_keys(external_id, captured_at) VALUES (?, ?)",
            (external_id, created["created_at"]),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Another pass captured the same source id between the lookup and here.
        conn.rollback()
        delete_task(conn, task_id)
        winner = find_by_external_id(conn, "tasks", external_id)
        if winner is None:  # pragma: no cover — the index says one of us won
            raise
        return get_task(conn, int(winner["id"])), "unchanged"
    _touched(task_id)
    return get_task(conn, task_id), "created"


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
        return value or DEFAULT_STATUS
    if field == "priority":
        return value or "none"
    if field == "due":
        return _validate_date(value)
    return value if value not in ("", None) else None
