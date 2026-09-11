"""Generate, stage, accept and reject AI suggestions for Inbox tasks (#95)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable
from datetime import date
from typing import Any

from src import clock
from src import tasks_repo as repo
from src.ai.client import AIClient, AIError

logger = logging.getLogger(__name__)

MAX_TASKS = 50
MAX_PROJECT_NODES = 200
MAX_DESCRIPTION_CHARS = 500
MAX_REASON_CHARS = 240
MAX_TOKENS = 2400
ALLOWED_PRIORITIES = frozenset({"none", "low", "medium", "high"})
ALLOWED_FIELDS = frozenset({"parent_id", "priority", "due", "person_id", "reason"})
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = """You triage Inbox tasks in a personal task manager.
Return JSON only, with this exact top-level shape:
{"suggestions":[{"task_id":1,"parent_id":2,"priority":"medium","due":null,"person_id":null,"reason":"short explanation"}]}
Return exactly one suggestion for every supplied Inbox task and no others.
Use only ids present in the supplied projects and people. Parent, due and person may be null.
Priority must be one of none, low, medium, high. Due must be YYYY-MM-DD or null.
Do not propose a status: accepting a suggestion moves the task to Todo.
Do not invent facts. Keep each reason under 20 words."""


def _json_text(raw: str) -> str:
    text = (raw or "").strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def _inbox_rows(conn: sqlite3.Connection, task_ids: Iterable[int] | None) -> list[dict[str, Any]]:
    requested = [int(task_id) for task_id in (task_ids or [])]
    if len(requested) != len(set(requested)):
        raise repo.ValidationError("task_ids must not contain duplicates")
    if len(requested) > MAX_TASKS:
        raise repo.ValidationError(f"triage accepts at most {MAX_TASKS} tasks at once")
    if requested:
        marks = ", ".join("?" for _ in requested)
        rows = conn.execute(
            f"SELECT id, title, description, due, priority, person_id FROM tasks "
            f"WHERE id IN ({marks}) AND status = 'inbox' ORDER BY id",
            requested,
        ).fetchall()
        found = {int(row["id"]) for row in rows}
        missing = sorted(set(requested) - found)
        if missing:
            raise repo.ValidationError(
                "every requested task must still be in Inbox "
                f"(not eligible: {', '.join(map(str, missing))})"
            )
    else:
        rows = conn.execute(
            "SELECT id, title, description, due, priority, person_id FROM tasks "
            "WHERE status = 'inbox' ORDER BY id LIMIT ?",
            (MAX_TASKS + 1,),
        ).fetchall()
        if len(rows) > MAX_TASKS:
            raise repo.ValidationError(f"Inbox has more than the {MAX_TASKS}-task triage limit")
    return [dict(row) for row in rows]


def _project_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The bounded set of open project nodes the model is allowed to name."""
    return conn.execute(
        "SELECT p.id, p.parent_id, p.title FROM tasks p "
        "WHERE p.status NOT IN ('done', 'cancelled') "
        "AND EXISTS (SELECT 1 FROM tasks c WHERE c.parent_id = p.id) "
        "ORDER BY p.id LIMIT ?",
        (MAX_PROJECT_NODES,),
    ).fetchall()


def assemble_context(
    conn: sqlite3.Connection, task_ids: Iterable[int] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return eligible rows and compact, deterministic model context."""
    tasks = _inbox_rows(conn, task_ids)
    if not tasks:
        raise repo.ValidationError("Inbox has no tasks to triage")
    projects = [
        {"id": int(row["id"]), "parent_id": row["parent_id"], "title": row["title"]}
        for row in _project_rows(conn)
    ]
    people = [
        {"id": int(row["id"]), "name": row["name"]}
        for row in conn.execute("SELECT id, name FROM people ORDER BY id").fetchall()
    ]
    compact_tasks = [
        {
            "id": int(task["id"]),
            "title": task["title"],
            "description": (task["description"] or "")[:MAX_DESCRIPTION_CHARS],
            "current_due": task["due"],
            "current_priority": task["priority"],
            "current_person_id": task["person_id"],
        }
        for task in tasks
    ]
    context = json.dumps(
        {
            "today": clock.today().isoformat(),
            "inbox_tasks": compact_tasks,
            "projects": projects,
            "people": people,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return tasks, context


def _invalid(detail: str) -> AIError:
    """The one error a rejected suggestions document raises; only ``detail`` varies."""
    return AIError("ai_invalid_response", "AI returned invalid suggestions", http_status=502, detail=detail)


def _validate_response(
    conn: sqlite3.Connection, raw: str, expected_ids: set[int],
) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(_json_text(raw))
    except ValueError as exc:
        raise _invalid(f"invalid JSON: {exc}") from exc
    suggestions = decoded.get("suggestions") if isinstance(decoded, dict) else None
    if not isinstance(decoded, dict) or set(decoded) != {"suggestions"}:
        raise _invalid("response must contain exactly the suggestions key")
    if not isinstance(suggestions, list):
        raise _invalid("suggestions is not a list")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("task_id"), int)
        or isinstance(item.get("task_id"), bool)
        for item in suggestions
    ):
        raise _invalid("every suggestion must carry an integer task_id")
    task_ids = [item["task_id"] for item in suggestions]
    if set(task_ids) != expected_ids or len(task_ids) != len(expected_ids):
        raise _invalid("response task ids do not exactly match the request")
    project_ids = {int(row["id"]) for row in _project_rows(conn)}
    person_ids = {int(row[0]) for row in conn.execute("SELECT id FROM people").fetchall()}
    valid: list[dict[str, Any]] = []
    for item in suggestions:
        expected_keys = {"task_id"} | ALLOWED_FIELDS
        if set(item) != expected_keys:
            raise _invalid("every suggestion must contain exactly the documented keys")
        task_id = int(item["task_id"])
        parent_id = item.get("parent_id")
        person_id = item.get("person_id")
        priority = item.get("priority")
        due = item.get("due")
        reason = item.get("reason")
        if parent_id is not None and (
            not isinstance(parent_id, int) or isinstance(parent_id, bool)
            or parent_id not in project_ids or parent_id == task_id
        ):
            raise _invalid(f"invalid parent_id for task {task_id}")
        # The cycle rule belongs to tasks_repo, which is what would enforce it
        # anyway when accept_suggestion calls update_task — a suggestion that
        # could only ever be rejected is not worth storing and showing.
        if repo.would_cycle(conn, task_id, parent_id):
            raise _invalid(f"parent_id would create a cycle for task {task_id}")
        if person_id is not None and (
            not isinstance(person_id, int) or isinstance(person_id, bool) or person_id not in person_ids
        ):
            raise _invalid(f"invalid person_id for task {task_id}")
        if priority not in ALLOWED_PRIORITIES:
            raise _invalid(f"invalid priority for task {task_id}")
        if due is not None:
            if not isinstance(due, str):
                raise _invalid(f"invalid due date for task {task_id}")
            try:
                parsed_due = date.fromisoformat(due)
            except ValueError as exc:
                raise _invalid(f"invalid due date for task {task_id}") from exc
            if parsed_due.isoformat() != due:
                raise _invalid(f"invalid due date for task {task_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise _invalid(f"missing reason for task {task_id}")
        valid.append({
            "task_id": task_id,
            "parent_id": parent_id,
            "priority": priority,
            "due": due,
            "person_id": person_id,
            "reason": reason.strip()[:MAX_REASON_CHARS],
        })
    return valid


def _suggestion_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    task = conn.execute("SELECT title, status FROM tasks WHERE id = ?", (row["task_id"],)).fetchone()
    parent = None
    if payload.get("parent_id") is not None:
        found = conn.execute("SELECT id, title FROM tasks WHERE id = ?", (payload["parent_id"],)).fetchone()
        parent = dict(found) if found else None
    person = None
    if payload.get("person_id") is not None:
        found = conn.execute("SELECT id, name FROM people WHERE id = ?", (payload["person_id"],)).fetchone()
        person = dict(found) if found else None
    return {
        "id": int(row["id"]),
        "task_id": int(row["task_id"]),
        "task_title": task["title"] if task else None,
        "task_status": task["status"] if task else None,
        **payload,
        "parent": parent,
        "person": person,
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def list_suggestions(
    conn: sqlite3.Connection, *, status: str | None = "pending",
) -> list[dict[str, Any]]:
    if status is not None and status not in {"pending", "accepted", "rejected"}:
        raise repo.ValidationError(f"unknown suggestion status: {status}")
    sql = "SELECT * FROM ai_suggestions"
    args: tuple[Any, ...] = ()
    if status is not None:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY id"
    return [_suggestion_row(conn, row) for row in conn.execute(sql, args).fetchall()]


def generate_suggestions(
    conn: sqlite3.Connection, client: AIClient, task_ids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    tasks, context = assemble_context(conn, task_ids)
    expected = {int(task["id"]) for task in tasks}
    raw = client.complete(system=SYSTEM_PROMPT, user=context, max_tokens=MAX_TOKENS)
    try:
        suggestions = _validate_response(conn, raw, expected)
    except AIError as exc:
        logger.warning(
            "⚠️ ai triage: rejected the whole response for %d task(s) — %s",
            len(expected), exc.detail or exc.code,
        )
        raise
    created_at = clock.now_iso()
    for suggestion in suggestions:
        task_id = suggestion.pop("task_id")
        conn.execute(
            "DELETE FROM ai_suggestions WHERE task_id = ? AND status = 'pending'",
            (task_id,),
        )
        conn.execute(
            "INSERT INTO ai_suggestions(task_id, payload, status, created_at) VALUES (?,?, 'pending', ?)",
            (task_id, json.dumps(suggestion, ensure_ascii=False, separators=(",", ":")), created_at),
        )
    conn.commit()
    logger.info("ℹ️ ai triage: staged %d suggestion(s) from %d context chars", len(suggestions), len(context))
    return list_suggestions(conn)


def _pending(conn: sqlite3.Connection, suggestion_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM ai_suggestions WHERE id = ? AND status = 'pending'", (suggestion_id,)
    ).fetchone()
    if row is None:
        raise repo.NotFound(f"pending suggestion {suggestion_id} not found")
    return row


def accept_suggestion(conn: sqlite3.Connection, suggestion_id: int) -> dict[str, Any]:
    row = _pending(conn, suggestion_id)
    payload = json.loads(row["payload"])
    task = repo.get_task(conn, int(row["task_id"]))
    if task["status"] != "inbox":
        raise repo.ValidationError("the task is no longer in Inbox")
    changes = {key: payload[key] for key in ("parent_id", "priority", "due", "person_id")}
    updated = repo.update_task(conn, int(row["task_id"]), actor="ai", status="todo", **changes)
    resolved_at = clock.now_iso()
    conn.execute(
        "UPDATE ai_suggestions SET status = 'accepted', resolved_at = ? WHERE id = ?",
        (resolved_at, suggestion_id),
    )
    conn.commit()
    return {"suggestion": _suggestion_row(conn, conn.execute(
        "SELECT * FROM ai_suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()), "task": updated}


def reject_suggestion(conn: sqlite3.Connection, suggestion_id: int) -> dict[str, Any]:
    _pending(conn, suggestion_id)
    conn.execute(
        "UPDATE ai_suggestions SET status = 'rejected', resolved_at = ? WHERE id = ?",
        (clock.now_iso(), suggestion_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ai_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    return _suggestion_row(conn, row)
