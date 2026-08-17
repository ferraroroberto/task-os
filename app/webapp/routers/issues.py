"""Issues route family — the provider's status, the sync, create-from-task.

    GET  /api/issues/status          {provider, enabled, reason, last_sync, last_result,
                                      last_error, next_run, repos}
    POST /api/issues/sync            one reconciliation pass now → the SyncResult
                                     (409 issues_disabled · 502 provider_error)
    GET  /api/tasks/{id}/issue       {ref, info} — the stored issue_ref + the last-seen
                                     issue (labels, updated_at) from the sync cache;
                                     ?live=1 asks the provider now
    POST /api/tasks/{id}/issue       {repo} → create an issue from the task (title +
                                     description), link it → the task becomes coding
                                     (409 already_linked / issues_disabled · 502 provider_error)

Attach an existing issue (``PUT /api/tasks/{id}/issue``) and detach
(``DELETE``) live in the tasks router — they are plain repo-layer writes.
The service lives on ``app.state.issues`` (started by the lifespan).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.webapp.routers._helpers import error_response, resolve_actor
from src import tasks_repo as repo
from src.db import get_db
from src.issues import IssueProviderError, short_repo

router = APIRouter(prefix="/api", tags=["issues"])


class CreateIssueBody(BaseModel):
    repo: str
    actor: str | None = None


def _service(request: Request) -> Any:
    return getattr(request.app.state, "issues", None)


def _repos(db: sqlite3.Connection, service: Any) -> list[str]:
    seen = {r["repo"] for r in repo.list_issue_refs(db)}
    if service is not None:
        seen.update(service.status().get("repos") or [])
    return sorted(seen)


@router.get("/issues/status")
def issues_status(request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    service = _service(request)
    if service is None:
        return {"provider": None, "enabled": False, "reason": "issue service not started", "repos": _repos(db, None)}
    body = service.status()
    body["repos"] = _repos(db, service)
    return body


@router.post("/issues/sync")
def issues_sync(request: Request, db: sqlite3.Connection = Depends(get_db)) -> Any:
    service = _service(request)
    if service is None or not service.enabled:
        reason = service.reason if service else "issue service not started"
        return error_response(409, "issues_disabled", reason)
    result = service.run_now(db)
    if result is None:
        return error_response(502, "provider_error", service.last_error or "sync failed",
                              {"code": service.last_error_code})
    return result.to_dict()


@router.get("/tasks/{task_id}/issue")
def task_issue(task_id: int, request: Request, live: bool = False, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    task = repo.get_task(db, task_id)
    ref = task.get("issue_ref")
    if ref is None:
        return {"ref": None, "info": None}
    service = _service(request)
    info = None
    error = None
    if service is not None:
        if live and service.enabled:
            try:
                fresh = service.provider.get(ref["repo"], int(ref["number"]))
                service.cache[fresh.key] = fresh
            except IssueProviderError as exc:
                error = {"code": exc.code, "message": str(exc)}
        cached = service.cached(ref["provider"], ref["repo"], int(ref["number"]))
        info = cached.to_dict() if cached else None
    body: dict[str, Any] = {"ref": ref, "info": info}
    if error:
        body["error"] = error
    return body


@router.post("/tasks/{task_id}/issue", status_code=201)
def create_issue_from_task(
    task_id: int, body: CreateIssueBody, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> Any:
    task = repo.get_task(db, task_id)
    if task.get("issue_ref"):
        ref = task["issue_ref"]
        return error_response(409, "already_linked", f"task {task_id} is already linked to {ref['repo']}#{ref['number']}")
    service = _service(request)
    if service is None or not service.enabled:
        reason = service.reason if service else "issue service not started"
        return error_response(409, "issues_disabled", reason)
    target = (body.repo or "").strip().strip("/")
    if "/" not in target:
        return error_response(422, "validation_error", "repo must be owner/name")
    actor = resolve_actor(request, body.actor)
    try:
        info = service.provider.create(target, task["title"], task.get("description") or "")
    except IssueProviderError as exc:
        return error_response(502, "provider_error", str(exc), {"code": exc.code})
    service.cache[info.key] = info
    repo.add_link(db, task_id, info.url, label=info.ref, kind="issue")
    updated = repo.set_issue_ref(
        db, task_id, provider=info.provider, repo=info.repo, number=info.number,
        url=info.url, state=info.state, actor=actor,
    )
    if not updated.get("code"):
        updated = repo.update_task(db, task_id, actor=actor, code=f"{short_repo(info.repo)}#{info.number}")
    return updated
