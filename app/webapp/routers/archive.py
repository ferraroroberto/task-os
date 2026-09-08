"""Archive route family — batch-archive the Outlook Inbox (#157).

    POST /api/archive/run  {limit?}      → 202 the run row, ``running``; the
                                           work continues in a worker thread
    GET  /api/archive/runs?limit=        → {runs, count} — latest first
    GET  /api/archive/runs/{id}          → the run with its items
    POST /api/archive/items/{id}/revert  → delete the files, mail back to Inbox
    POST /api/archive/items/{id}/move    {folder, hint?} → file into that folder
                                           (a filed row is undone first; a
                                           ``needs_review`` one is simply filed)
    POST /api/archive/items/{id}/accept  {hint?} → mark a reviewable row seen (no files)

``hint`` is the optional one-line note the report screen (#159) offers when you
overrule the ranking ("bills from this sender always go to the flat"). It is
stored on the ``archive_corrections`` row the action writes (#158) and ridden
into every later prompt as a few-shot example, so a correction explained once
does not have to be repeated.

``limit`` is the one knob beyond the run itself: *at most this many mails this
run*, in the archiver's own plan order. It exists so a first run against a real
Inbox can be one mail — trust is built on a run you can undo, not on a promise —
and it rides either the JSON body or ``?limit=``, because the first thing anyone
does with this route is `curl` it.

Everything the archiver does happens in a subprocess (``src/archive_batch.py``),
so every route here is thin: it hands ``ArchiveError`` to the one JSON envelope
and lets the service own the state machine. The run's own progress is not
polled: ``GET /api/archive/runs/{id}`` is the whole story, and the screen (#159)
reads it.

There is deliberately no ``GET /api/archive/status``: the service's configured /
reason / running / last_run ride ``GET /api/status`` under ``archive``, beside
capture, mirror and the rest, so Settings reads the whole install in one call.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.webapp.routers._helpers import error_response
from src.archive_batch import MAX_HINT_CHARS, ArchiveError, get_run, list_items, list_runs
from src.db import get_db

router = APIRouter(prefix="/api/archive", tags=["archive"])


class RunBody(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)


class MoveBody(BaseModel):
    folder: str = Field(min_length=1)
    hint: str | None = Field(default=None, max_length=MAX_HINT_CHARS)


class AcceptBody(BaseModel):
    hint: str | None = Field(default=None, max_length=MAX_HINT_CHARS)


def _service(request: Request) -> Any:
    return getattr(request.app.state, "archive", None)


def _unavailable(service: Any) -> JSONResponse:
    reason = service.reason if service else "archive service not started"
    return error_response(409, "archive_disabled", reason or "batch archiving is off")


@router.post("/run", status_code=202)
def archive_run(
    request: Request,
    body: RunBody | None = None,
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> Any:
    """Start a run and answer immediately — a full Inbox takes minutes over COM."""
    service = _service(request)
    if service is None or not service.enabled:
        return _unavailable(service)
    try:
        run = service.start_run(limit=(body.limit if body and body.limit else limit))
    except ArchiveError as exc:
        return error_response(exc.http_status, exc.code, str(exc), exc.detail)
    return JSONResponse(run, status_code=202)


@router.get("/runs")
def archive_runs(
    db: sqlite3.Connection = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    runs = list_runs(db, limit=limit)
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{run_id}")
def archive_run_detail(run_id: int, db: sqlite3.Connection = Depends(get_db)) -> Any:
    run = get_run(db, run_id)
    if run is None:
        return error_response(404, "not_found", f"no archive run {run_id}")
    return {**run, "items": list_items(db, run_id)}


@router.post("/items/{item_id}/revert")
async def archive_item_revert(
    item_id: int, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> Any:
    service = _service(request)
    if service is None or not service.enabled:
        return _unavailable(service)
    try:
        return await run_in_threadpool(service.revert, db, item_id)
    except ArchiveError as exc:
        return error_response(exc.http_status, exc.code, str(exc), exc.detail)


@router.post("/items/{item_id}/move")
async def archive_item_move(
    item_id: int, body: MoveBody, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> Any:
    service = _service(request)
    if service is None or not service.enabled:
        return _unavailable(service)
    try:
        return await run_in_threadpool(service.move, db, item_id, body.folder, hint=body.hint)
    except ArchiveError as exc:
        return error_response(exc.http_status, exc.code, str(exc), exc.detail)


@router.post("/items/{item_id}/accept")
def archive_item_accept(
    item_id: int, request: Request, body: AcceptBody | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> Any:
    service = _service(request)
    if service is None:
        return _unavailable(service)
    try:
        return service.accept(db, item_id, hint=body.hint if body else None)
    except ArchiveError as exc:
        return error_response(exc.http_status, exc.code, str(exc), exc.detail)
