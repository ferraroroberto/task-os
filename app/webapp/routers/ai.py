"""Staged AI Inbox triage routes (#95).

Generation is blocking and may take seconds, so it runs in FastAPI's worker
thread. Every response is staged; only the explicit accept endpoint writes a
task, and rejection only resolves the suggestion.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.webapp.routers._helpers import error_response
from src.ai import (
    AIError,
    accept_suggestion,
    generate_suggestions,
    list_suggestions,
    reject_suggestion,
)
from src.db import get_db

router = APIRouter(prefix="/api/ai", tags=["ai"])


class TriageBody(BaseModel):
    task_ids: list[int] | None = Field(default=None, max_length=50)


@router.get("/suggestions")
def suggestions(
    status: str = Query(default="pending"),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return {"items": list_suggestions(db, status=status)}


@router.post("/triage")
async def triage(
    body: TriageBody,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> Any:
    client = getattr(request.app.state, "ai", None)
    if client is None:
        return error_response(409, "ai_disabled", "AI service not started")
    try:
        items = await run_in_threadpool(generate_suggestions, db, client, body.task_ids)
    except AIError as exc:
        return error_response(exc.http_status, exc.code, str(exc))
    return {"items": items}


@router.post("/suggestions/{suggestion_id}/accept")
def accept(suggestion_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return accept_suggestion(db, suggestion_id)


@router.post("/suggestions/{suggestion_id}/reject")
def reject(suggestion_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return reject_suggestion(db, suggestion_id)
