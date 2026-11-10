"""Folders route family — placeholder resolution + folder-explorer's folder search (Step 9).

    POST /api/resolve  {"ref": "<ref or absolute path>"}
        → {ref, path, resolved, unresolved, href, web_url}
          ``ref`` is the value folded back onto the placeholders (an absolute
          path pasted in the drawer becomes ``{onedrive}/…`` — the portable
          form the task stores); ``path`` is this server's resolved absolute
          path (display only); ``href`` the ``taskos://open?ref=…`` link;
          ``web_url`` the cloud twin from ``config.web_roots`` (#28), or null.
    GET  /api/folders/search?q=<terms>&limit=30
        → {q, items: [{path, ref, name, depth}], count}
          folder-explorer's v1 folder search (src/search/folder_explorer.py), each
          hit's path folded onto the placeholders; 503 ``folders_unavailable``
          with ``detail: {state, reason}`` when folder-explorer cannot answer
          (``not-configured`` · ``indexing`` · ``failed`` · ``unreachable``) —
          never an empty ``items`` that would read as "no folder matches".

``/api/resolve`` is a POST although it only reads: ``ref`` is a *query
parameter name on every tracking-parameter blocklist*, so a URL-cleaning
browser extension (uBlock Origin's "Remove tracking parameters", AdGuard,
ClearURLs, Brave shields) strips it by redirecting to the query-less URL —
the drawer's "paste an absolute path" then 422s on a server that never saw
the value (#66). A body carries no query string, so no cleaner can touch it,
and the folder path stays out of the URL, the history and any access log.

The client lives on ``app.state.folder_explorer`` (built by the lifespan). The
``tasks folders …`` CLI calls these when the app is up.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.webapp.routers._helpers import error_response
from src import placeholders
from src.search.folder_explorer import Unavailable
from src.search.folders_adapter import folder_item

router = APIRouter(prefix="/api", tags=["folders"])


class ResolveBody(BaseModel):
    ref: str = Field(min_length=1)




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
    client = getattr(request.app.state, "folder_explorer", None)
    if client is None:
        return error_response(503, "folders_unavailable", "folder search client not started",
                              detail={"state": "not-configured", "reason": "folder search client not started"})
    try:
        body = client.folders(q, limit)
    except Unavailable as exc:
        return error_response(503, "folders_unavailable", f"folder-explorer is {exc.state}: {exc.reason}",
                              detail={"state": exc.state, "reason": exc.reason})
    items = [folder_item(r, request.app.state.config.placeholders) for r in body.get("results") or []]
    return {"q": q, "items": items, "count": len(items)}
