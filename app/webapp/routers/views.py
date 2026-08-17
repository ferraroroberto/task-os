"""View routes — the pre-bucketed shapes the Board and Today tabs render.

    GET /api/board?project=&person=&q=
        → {"today", "columns": {inbox, todo, doing, standby, done: [summary…]}}
          ``done`` = completed on the current local day only.
    GET /api/today?person=
        → {"today", "due": [{root, items}], "week": [{root, items}], "counts"}
          ``due`` = open tasks due ≤ today grouped by root project (recurring
          first inside a group); ``week`` = tomorrow … +7 days, same shape.

Both are read-only projections of ``tasks_repo.list_tasks`` (the same
enriched summaries the Table gets); the bucketing rules live in
``src.tasks_repo.board`` / ``today_view`` so the CLI can reuse them later.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

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


@router.get("/today")
def today(person: int | None = None, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.today_view(db, person_id=person)
