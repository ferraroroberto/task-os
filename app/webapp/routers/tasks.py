"""Tasks route family — CRUD, tree, move, done, comments, links, issue, activity.

    GET    /api/tasks                    filtered flat list (summaries)
    POST   /api/tasks                    create → 201
    POST   /api/tasks/bulk               {ids, status?, due?} → per-id results
    GET    /api/tasks/tree?root=N        nested forest (or N's subtree)
    GET    /api/tasks/{id}               detail: links, comments, activity, children, breadcrumb
    PATCH  /api/tasks/{id}               update fields (parent_id goes through the cycle guard)
    DELETE /api/tasks/{id}               delete the task and its subtree
    POST   /api/tasks/{id}/move          {parent_id | null}
    POST   /api/tasks/{id}/done          complete (recurring → roll due)
    GET    /api/tasks/{id}/comments      thread order
    POST   /api/tasks/{id}/comments      {body, origin?, author?} → 201
    GET    /api/tasks/{id}/links
    POST   /api/tasks/{id}/links         {url, label?, kind?} → 201
    DELETE /api/tasks/{id}/links/{lid}
    PUT    /api/tasks/{id}/issue         {provider, repo, number, url?, state?} → type=coding
    DELETE /api/tasks/{id}/issue         detach → type=task
    GET    /api/activity?task=N&limit=   newest first (all tasks when no task)
    POST   /api/parse                    {text} → quick-add split: title, due, parent

Query filters on the list: ``status`` (repeatable, or ``open``), ``parent``
(id or ``root``), ``project`` (descendant-of), ``due`` (``today`` · ``week``
· ``overdue`` · date), ``due_from`` / ``due_to``, ``type``, ``person``
(repeatable / comma-separated ids), ``q`` (full text), ``updated_since``
(date), ``updated_before`` (date — the stale windows' inverse twin, #101),
``done_on`` (date), ``include_closed``, ``limit``.

``status`` also takes the pseudo-value ``deferred`` (#87) — not a status but
a modifier: it flips the list from awake tasks to the sleeping ones (``starts``
still in the future), intersected with any real statuses alongside it. The
split happens here, in the one presentational place that knows the URL
vocabulary; the rule itself is ``list_tasks(deferred=…)``.

``due`` and ``starts`` on create / update accept the same natural phrases the
CLI does (``tomorrow``, ``next friday``, ``this weekend``, ``in 2 weeks``,
ISO) — resolved here through ``src.dates.parse_date`` so the repo layer only
ever sees ISO dates; an unknown phrase is a 422, never a silently unset date.

The actor written to ``activity`` / ``comments`` is the body's ``actor`` /
``author`` field, else the ``X-Actor`` header, else the configured default
(``_helpers.resolve_actor``). Domain errors surface as the shared JSON
envelope via the app-level ``RepoError`` handler.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.webapp.routers._helpers import resolve_actor
from src import quick_add
from src import tasks_repo as repo
from src.dates import DateParseError, parse_date
from src.db import get_db

router = APIRouter(prefix="/api", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    parent_id: int | None = None
    code: str | None = None
    type: str | None = None
    status: str | None = None
    priority: str | None = None
    due: str | None = None
    starts: str | None = None
    recurrence: str | None = None
    description: str | None = None
    folder_ref: str | None = None
    next_action: str | None = None
    person_id: int | None = None
    actor: str | None = None


class TaskUpdate(BaseModel):
    """Partial update — only fields present in the JSON body are applied."""

    parent_id: int | None = None
    code: str | None = None
    title: str | None = None
    type: str | None = None
    status: str | None = None
    priority: str | None = None
    due: str | None = None
    starts: str | None = None
    recurrence: str | None = None
    description: str | None = None
    folder_ref: str | None = None
    next_action: str | None = None
    person_id: int | None = None
    actor: str | None = None


class BulkBody(BaseModel):
    """One change applied to many tasks — the Board/Table selection (issue #81).

    ``status`` takes the same vocabulary as the row select, ``complete``
    included; ``due`` takes the same natural phrases as a single-task update
    (``null`` / ``""`` clears it). Both may travel together, except
    ``complete`` (which rolls the due itself) with an explicit ``due``.
    """

    ids: list[int] = Field(min_length=1, max_length=500)
    status: str | None = None
    due: str | None = None
    actor: str | None = None


class MoveBody(BaseModel):
    parent_id: int | None = None
    actor: str | None = None


class ActorBody(BaseModel):
    actor: str | None = None


class CommentBody(BaseModel):
    body: str
    origin: str = "ui"
    author: str | None = None


class LinkBody(BaseModel):
    url: str
    label: str | None = None
    kind: str = "web"


class ParseBody(BaseModel):
    text: str
    today: str | None = None


#: The pseudo-value the status multi-select adds (#87) — see the module docstring.
DEFERRED = "deferred"


def _resolve_dates(fields: dict[str, Any]) -> dict[str, Any]:
    """Natural date phrases → ISO (in place); ``None`` / ``""`` clear them.

    Covers every date field a client may set (``due``, ``starts``), so the two
    can never drift into accepting different vocabularies.
    """
    for field in repo.DATE_FIELDS:
        if field not in fields:
            continue
        value = fields[field]
        if value is None or str(value).strip() == "":
            fields[field] = None
            continue
        try:
            d = parse_date(str(value))
        except DateParseError as exc:
            raise repo.ValidationError(str(exc)) from exc
        fields[field] = d.isoformat() if d else None
    return fields


def _split_deferred(statuses: list[str]) -> tuple[list[str], str | None]:
    """``[…, "deferred"] → (the real statuses, "only")``; otherwise ``None``,
    which lets ``list_tasks`` follow ``include_closed``."""
    if DEFERRED not in statuses:
        return statuses, None
    return [s for s in statuses if s != DEFERRED], "only"


class IssueBody(BaseModel):
    provider: str = "github"
    repo: str
    number: int = Field(gt=0)
    url: str | None = None
    state: str | None = None
    actor: str | None = None


# ------------------------------------------------------------------ list


@router.get("/tasks")
def list_tasks(
    status: list[str] | None = Query(default=None),
    parent: str | None = None,
    project: int | None = None,
    due: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    type: str | None = None,
    person: list[str] | None = Query(default=None),
    q: str | None = None,
    updated_since: str | None = None,
    updated_before: str | None = None,
    done_on: str | None = None,
    include_closed: bool = False,
    limit: int | None = Query(default=None, ge=1, le=1000),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    statuses: list[str] = []
    for s in status or []:
        statuses.extend(p.strip() for p in s.split(",") if p.strip())
    statuses, deferred = _split_deferred(statuses)
    people: list[int] = []
    for s in person or []:
        for p in s.split(","):
            if p.strip():
                try:
                    people.append(int(p))
                except ValueError as exc:
                    raise repo.ValidationError(f"person must be an id, got {p!r}") from exc
    parent_id: int | str | None = None
    if parent is not None:
        parent_id = "root" if parent in ("root", "none", "null", "") else int(parent)
    items = repo.list_tasks(
        db,
        status=statuses or None,
        parent_id=parent_id,
        project=project,
        due=due,
        due_from=due_from,
        due_to=due_to,
        type=type,
        person_id=people or None,
        q=q,
        include_closed=include_closed,
        limit=limit,
        done_on=done_on,
        updated_since=updated_since,
        updated_before=updated_before,
        deferred=deferred,
    )
    return {"items": items, "count": len(items)}


@router.post("/tasks", status_code=201)
def create_task(
    body: TaskCreate, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    fields = _resolve_dates(body.model_dump(exclude={"title", "actor"}, exclude_none=True))
    return repo.create_task(db, body.title, actor=resolve_actor(request, body.actor), **fields)


@router.post("/tasks/bulk")
def bulk_tasks(
    body: BulkBody, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    """Apply one status / due change to a selection of tasks (issue #81).

    Declared before ``/tasks/{task_id}`` so the literal path always wins.
    ``due`` is resolved **once** here: an unparseable phrase is one 422 for
    the request, not the same error repeated per id. Per-*task* failures (an
    id deleted in another tab, a status the task refuses) are data, not an
    error — they come back as ``ok: false`` rows on a 200 so the caller can
    say which ids failed and keep them selected for a retry.
    """
    changes = body.model_dump(exclude={"ids", "actor", "status"}, exclude_unset=True)
    complete = body.status == "complete"
    if body.status is None and "due" not in changes:
        raise repo.ValidationError("a bulk change needs a status, a due date, or both")
    if complete and "due" in changes:
        raise repo.ValidationError("'complete' rolls the due date itself — don't set one too")
    if body.status is not None and not complete:
        changes["status"] = body.status
    _resolve_dates(changes)
    results = repo.bulk_update(
        db, body.ids, actor=resolve_actor(request, body.actor), complete=complete, **changes
    )
    updated = sum(1 for r in results if r["ok"])
    return {"results": results, "updated": updated, "failed": len(results) - updated}


@router.get("/tasks/tree")
def tree(
    root: int | None = None,
    include_closed: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return {"items": repo.tree(db, root, include_closed=include_closed)}


# ---------------------------------------------------------------- detail


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.get_task(db, task_id)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int, body: TaskUpdate, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    changes = _resolve_dates(body.model_dump(exclude={"actor"}, exclude_unset=True))
    return repo.update_task(db, task_id, actor=resolve_actor(request, body.actor), **changes)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.delete_task(db, task_id)


@router.post("/tasks/{task_id}/move")
def move_task(
    task_id: int, body: MoveBody, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return repo.move(db, task_id, body.parent_id, actor=resolve_actor(request, body.actor))


@router.post("/tasks/{task_id}/done")
def done_task(
    task_id: int,
    request: Request,
    body: ActorBody | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    actor = resolve_actor(request, body.actor if body else None)
    return repo.done(db, task_id, actor=actor)


# -------------------------------------------------------------- comments


@router.get("/tasks/{task_id}/comments")
def list_comments(task_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    repo.get_task(db, task_id)  # 404 on an unknown task rather than an empty list
    return {"items": repo.list_comments(db, task_id)}


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_comment(
    task_id: int, body: CommentBody, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return repo.add_comment(
        db, task_id, body.body, author=resolve_actor(request, body.author), origin=body.origin
    )


# ----------------------------------------------------------------- links


@router.get("/tasks/{task_id}/links")
def list_links(task_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    repo.get_task(db, task_id)
    return {"items": repo.list_links(db, task_id)}


@router.post("/tasks/{task_id}/links", status_code=201)
def add_link(task_id: int, body: LinkBody, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.add_link(db, task_id, body.url, label=body.label, kind=body.kind)


@router.delete("/tasks/{task_id}/links/{link_id}")
def remove_link(task_id: int, link_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    repo.remove_link(db, task_id, link_id)
    return {"id": link_id, "deleted": 1}


# ----------------------------------------------------------------- issue


@router.put("/tasks/{task_id}/issue")
def set_issue(
    task_id: int, body: IssueBody, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return repo.set_issue_ref(
        db,
        task_id,
        provider=body.provider,
        repo=body.repo,
        number=body.number,
        url=body.url,
        state=body.state,
        actor=resolve_actor(request, body.actor),
    )


@router.delete("/tasks/{task_id}/issue")
def remove_issue(
    task_id: int, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return repo.remove_issue_ref(db, task_id, actor=resolve_actor(request))


# -------------------------------------------------------------- activity


@router.get("/activity")
def activity(
    task: int | None = None,
    limit: int | None = Query(default=200, ge=1, le=5000),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    if task is not None:
        repo.get_task(db, task)
    return {"items": repo.list_activity(db, task, limit=limit)}


# ------------------------------------------------------------- quick-add


@router.post("/parse")
def parse_quick_add(body: ParseBody, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Split a quick-add line: ``{title, due, due_phrase, starts, starts_phrase,
    parent, parent_ref}``.

    ``parent`` is the resolved ``{id, title}`` (or ``None`` when the reference
    names nothing — the UI shows that rather than guessing); ``today`` pins
    the reference date (tests / a client in another zone).
    """
    today = None
    if body.today:
        try:
            today = date.fromisoformat(body.today)
        except ValueError as exc:
            raise repo.ValidationError(f"today must be YYYY-MM-DD (got {body.today!r})") from exc
    parsed = quick_add.parse(body.text, today)
    parsed["parent"] = quick_add.resolve_parent(db, parsed["parent_ref"])
    return parsed
