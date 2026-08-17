"""Folders route family — placeholder resolution + the folder index (Step 9).

    GET  /api/resolve?ref=<ref or absolute path>
        → {ref, path, resolved, unresolved, href}
          ``ref`` is the value folded back onto the placeholders (an absolute
          path pasted in the drawer becomes ``{onedrive}/…`` — the portable
          form the task stores); ``path`` is this server's resolved absolute
          path (display only); ``href`` the ``taskos://open?ref=…`` link.
    GET  /api/folders/search?q=<terms>&limit=30
        → {q, items: [{path, ref, name, depth}], count, indexing, reason?}
          substring AND search over the folder index (see src/folder_index.py);
          409 ``folders_disabled`` when no root is configured / resolves.
    POST /api/folders/reindex
        → {entries, roots, seconds, index_file} — rescan now, foreground.

The service lives on ``app.state.folders`` (started by the lifespan; the
startup reindex runs in its own daemon thread). The ``tasks folders …`` CLI
calls these when the app is up.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.webapp.routers._helpers import error_response
from src import placeholders

router = APIRouter(prefix="/api", tags=["folders"])


def _service(request: Request) -> Any:
    return getattr(request.app.state, "folders", None)


@router.get("/resolve")
def resolve(request: Request, ref: str = Query(min_length=1)) -> dict[str, Any]:
    ph = request.app.state.config.placeholders
    folded = placeholders.to_ref(ref, ph)
    r = placeholders.resolve(folded, ph)
    return r.as_dict()


@router.get("/folders/search")
def folders_search(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=30, ge=1, le=200),
) -> Any:
    svc = _service(request)
    if svc is None or not svc.enabled:
        reason = svc.reason if svc else "folder index service not started"
        return error_response(409, "folders_disabled", reason)
    items = svc.search(q, limit=limit)
    return {"q": q, "items": items, "count": len(items), "indexing": svc.indexing, "entries": svc.status()["entries"]}


@router.post("/folders/reindex")
def folders_reindex(request: Request) -> Any:
    svc = _service(request)
    if svc is None or not svc.enabled:
        reason = svc.reason if svc else "folder index service not started"
        return error_response(409, "folders_disabled", reason)
    try:
        return svc.reindex()
    except Exception as exc:  # noqa: BLE001 — surfaced as the envelope, logged by the service
        return error_response(500, "reindex_failed", str(exc))
