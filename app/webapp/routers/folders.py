"""Folders route family — placeholder resolution + the folder index (Step 9).

    POST /api/resolve  {"ref": "<ref or absolute path>"}
        → {ref, path, resolved, unresolved, href, web_url}
          ``ref`` is the value folded back onto the placeholders (an absolute
          path pasted in the drawer becomes ``{onedrive}/…`` — the portable
          form the task stores); ``path`` is this server's resolved absolute
          path (display only); ``href`` the ``taskos://open?ref=…`` link;
          ``web_url`` the cloud twin from ``config.web_roots`` (#28), or null.
    GET  /api/folders/search?q=<terms>&limit=30
        → {q, items: [{path, ref, name, depth}], count, indexing, reason?}
          substring AND search over the folder index (see src/folder_index.py);
          409 ``folders_disabled`` when no root is configured / resolves.
    POST /api/folders/reindex
        → {entries, roots, seconds, index_file} — rescan now, foreground.

``/api/resolve`` is a POST although it only reads: ``ref`` is a *query
parameter name on every tracking-parameter blocklist*, so a URL-cleaning
browser extension (uBlock Origin's "Remove tracking parameters", AdGuard,
ClearURLs, Brave shields) strips it by redirecting to the query-less URL —
the drawer's "paste an absolute path" then 422s on a server that never saw
the value (#66). A body carries no query string, so no cleaner can touch it,
and the folder path stays out of the URL, the history and any access log.

The service lives on ``app.state.folders`` (started by the lifespan; the
startup reindex runs in its own daemon thread). The ``tasks folders …`` CLI
calls these when the app is up.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.webapp.routers._helpers import error_response
from src import placeholders

router = APIRouter(prefix="/api", tags=["folders"])


class ResolveBody(BaseModel):
    ref: str = Field(min_length=1)


def _service(request: Request) -> Any:
    return getattr(request.app.state, "folders", None)


@router.post("/resolve")
def resolve(request: Request, body: ResolveBody) -> dict[str, Any]:
    cfg = request.app.state.config
    folded = placeholders.to_ref(body.ref, cfg.placeholders)
    r = placeholders.resolve(folded, cfg.placeholders, cfg.web_roots)
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
