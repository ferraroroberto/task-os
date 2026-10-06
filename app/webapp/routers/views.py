"""View routes — the pre-bucketed shapes the Board and Today tabs render.

    GET /api/board?project=&person=&q=
        → {"today", "columns": {inbox, todo, standby, done: [summary…]}}
          ``done`` = completed on the current local day only.
    GET /api/today?person=
        → {"today", "due": [{root, items}], "week": [{root, items}], "counts",
           "calendar"}
          ``due`` = open tasks due ≤ today grouped by root project (sorted by
          due date within each group); ``week`` = tomorrow … +7 days,
          same shape; ``calendar`` = the read-only calendar lane (#96,
          ``src.calendar_lane``): today's events from ``calendar.ics_url``
          plus the state that says whether an empty list is a free day. It
          never holds the response longer than ``calendar.timeout_seconds``.
    POST /api/calendar/refresh
        → the same ``calendar`` group after fetching now (Settings' *Refresh
          now*), still bounded by the timeout.

The GETs are read-only projections of ``tasks_repo.list_tasks`` (the same
enriched summaries the Table gets); the bucketing rules live in
``src.tasks_repo.board`` / ``today_view`` so the CLI can reuse them later.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from src import tasks_repo as repo
from src.db import get_db

router = APIRouter(prefix="/api", tags=["views"])


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
