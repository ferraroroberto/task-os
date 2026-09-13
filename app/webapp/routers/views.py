"""View routes — the pre-bucketed shapes the Board and Today tabs render.

    GET /api/board?project=&person=&q=
        → {"today", "columns": {inbox, todo, standby, done: [summary…]}}
          ``done`` = completed on the current local day only.
    GET /api/today?person=
        → {"today", "plan", "due": [{root, items}], "week": [{root, items}], "counts",
           "calendar"}
          ``plan`` = tasks committed to today (#89), ordered by plan_order,
          done ones included for the progress line; ``due`` = open tasks due
          ≤ today grouped by root project (sorted by due date within each
          group), minus what is already in the plan; ``week`` = tomorrow …
          +7 days,
          same shape; ``calendar`` = the read-only calendar lane (#96,
          ``src.calendar_lane``): today's events from ``calendar.ics_url``
          plus the state that says whether an empty list is a free day. It
          never holds the response longer than ``calendar.timeout_seconds``.
    POST /api/calendar/refresh
        → the same ``calendar`` group after fetching now (Settings' *Refresh
          now*), still bounded by the timeout.
    GET /api/plan/candidates?person=
        → {"items", "count"} — what plan-my-day offers (#89): open overdue +
          due-today + inbox tasks not already planned today; a candidate
          whose ``planned_on`` is an earlier day wears the "planned
          yesterday" note client-side.
    POST /api/plan/reorder {ids}
        → {"planned": n} — rewrite today's plan order (#89); ``ids`` must be
          a permutation of every task planned today.

The GETs are read-only projections of ``tasks_repo.list_tasks`` (the same
enriched summaries the Table gets); the bucketing rules live in
``src.tasks_repo.board`` / ``today_view`` so the CLI can reuse them later,
and the reorder rule in ``tasks_repo.plan_reorder``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src import tasks_repo as repo
from src.db import get_db

router = APIRouter(prefix="/api", tags=["views"])


class ReorderBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


@router.get("/board")
def board(
    project: int | None = None,
    person: int | None = None,
    q: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return repo.board(db, project=project, person_id=person, q=q or None)


_CALENDAR_NOT_STARTED = {"configured": False, "state": "off", "reason": "calendar service not started",
                         "all_day": [], "events": []}


@router.get("/today")
def today(
    request: Request, person: int | None = None, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    payload = repo.today_view(db, person_id=person)
    calendar = getattr(request.app.state, "calendar", None)
    payload["calendar"] = calendar.today() if calendar else dict(_CALENDAR_NOT_STARTED)
    return payload


@router.post("/calendar/refresh")
def calendar_refresh(request: Request) -> dict[str, Any]:
    calendar = getattr(request.app.state, "calendar", None)
    return calendar.refresh() if calendar else dict(_CALENDAR_NOT_STARTED)


@router.get("/plan/candidates")
def plan_candidates(
    person: int | None = None, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    items = repo.plan_candidates(db, person_id=person)
    return {"items": items, "count": len(items)}


@router.post("/plan/reorder")
def plan_reorder(body: ReorderBody, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.plan_reorder(db, body.ids)
