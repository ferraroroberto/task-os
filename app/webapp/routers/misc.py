"""Shell + liveness + build-identity routes.

    GET /              → the PWA shell (index.html, asset URLs hash-stamped,
                         served no-cache so a deploy is picked up on reload;
                         ETag + If-None-Match → a bodyless 304 on a repeat)
    GET /healthz       → liveness probe (200 while the process answers)
    GET /api/version   → {git_sha, built_at, asset_hash, schema_version} —
                         the build-identity contract the restart recipe
                         verifies against (a stale process passes /healthz;
                         it cannot fake this)
    GET /opener/opener.cmd → the per-PC folder opener handler (Step 9), served
    GET /opener/opener.ps1   as text so a second PC's install one-liner can
                         Invoke-WebRequest them (public — see src/auth.py).
                         Both: the launcher is what gets registered, the
                         handler is what it calls.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from app.webapp.routers._helpers import BUILD_INFO, STATIC_DIR
from src.db import get_db, schema_version
from src.opener import HANDLER_PATH, LAUNCHER_PATH

router = APIRouter()


_INDEX_CACHE_CONTROL = "no-cache, must-revalidate"


def _etag_of(html: str) -> str:
    """Weak validator of the stamped page. The stamp names the fleet hash of
    every static file, so any asset edit or new build is a new page and a new
    tag: a 304 can never outlive a build."""
    return 'W/"' + hashlib.sha256(html.encode("utf-8")).hexdigest()[:20] + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    """``If-None-Match`` against ``etag`` — weak comparison, ``*`` and lists tolerated."""
    if not if_none_match:
        return False
    wanted = etag.removeprefix("W/")
    for candidate in (c.strip() for c in if_none_match.split(",")):
        if candidate == "*" or candidate.removeprefix("W/") == wanted:
            return True
    return False


@router.get("/", include_in_schema=False)
async def index(request: Request) -> Response:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html missing")
    html = BUILD_INFO.stamp_html(index_path.read_text(encoding="utf-8"))
    # The shell must always revalidate: a cached shell pointing at an old
    # ?v= entry module would defeat the fleet-hash cache-busting entirely.
    # The validator makes that revalidation a bodyless 304 on a relaunch (#280).
    etag = _etag_of(html)
    headers = {"Cache-Control": _INDEX_CACHE_CONTROL, "ETag": etag}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return HTMLResponse(html, headers=headers)


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True}


def _opener_file(path: Path) -> FileResponse:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} missing")
    return FileResponse(
        str(path), media_type="text/plain; charset=utf-8", filename=path.name,
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/opener/opener.cmd", include_in_schema=False)
async def opener_handler() -> FileResponse:
    return _opener_file(HANDLER_PATH)


@router.get("/opener/opener.ps1", include_in_schema=False)
async def opener_launcher() -> FileResponse:
    return _opener_file(LAUNCHER_PATH)


@router.get("/api/version")
async def version(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    payload: dict[str, Any] = dict(BUILD_INFO.as_dict())
    # ``None`` (not a number) when the settings table is missing — an
    # unestablished fact is reported as unknown, never folded into "fine".
    payload["schema_version"] = schema_version(db)
    return payload
