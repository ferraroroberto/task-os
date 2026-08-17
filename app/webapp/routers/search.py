"""Search route family — one box over four indexes (Step 10).

    GET /api/search?q=<text>&kinds=tasks,folders,emails,issues&limit=20
        → {"q", "took_ms", "groups": [{kind, configured, reason, note, hits, count,
                                        took_ms, error, skipped}, …]}
          always the four groups in that order (src/search/federated.py) — an
          adapter that is not configured on this install is ``configured:false``
          + reason, never silently missing; ``kinds`` narrows which adapters run
          (the command palette asks for ``tasks`` only); ``limit`` is per group.
    GET /api/search/status
        → {"adapters": [{kind, name, configured, reason, note}, …]} — the
          Settings card, no query.

Hit shape per kind: ``src/search/base.py``. The federated service lives on
``app.state.search`` (built by the lifespan over the folder-index and
issue-sync services); ``tasks search`` in the CLI calls this when the app is
up.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from src.search import DEFAULT_LIMIT, parse_kinds

router = APIRouter(prefix="/api", tags=["search"])


def _service(request: Request) -> Any:
    return getattr(request.app.state, "search", None)


@router.get("/search")
def search(
    request: Request,
    q: str = Query(min_length=1),
    kinds: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=200),
) -> dict[str, Any]:
    svc = _service(request)
    return svc.search(q, kinds=parse_kinds(kinds), limit=limit)


@router.get("/search/status")
def search_status(request: Request) -> dict[str, Any]:
    svc = _service(request)
    return {"adapters": svc.status() if svc else []}
