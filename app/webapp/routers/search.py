"""Search route — full text over tasks (title, description) and comment bodies.

    GET /api/search?q=<text>&limit=50
        → {"q", "items": [task summary + snippet + matched_in + breadcrumb], "count"}

Step 10 widens this to folders, emails and issues; the task leg keeps this
shape so the UI's search pane and the CLI's ``tasks search`` don't change.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from src import tasks_repo as repo
from src.db import get_db

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(
    q: str = Query(min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    items = repo.search(db, q, limit=limit)
    return {"q": q, "items": items, "count": len(items)}
