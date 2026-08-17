"""Shell + liveness + build-identity routes.

    GET /              → the PWA shell (index.html, asset URLs hash-stamped,
                         served no-cache so a deploy is picked up on reload)
    GET /healthz       → liveness probe (200 while the process answers)
    GET /api/version   → {git_sha, built_at, asset_hash, schema_version} —
                         the build-identity contract the restart recipe
                         verifies against (a stale process passes /healthz;
                         it cannot fake this)
    GET /opener/opener.cmd → the per-PC folder opener handler (Step 9), served
                         as text so a second PC's install one-liner can
                         Invoke-WebRequest it (public — see src/auth.py)
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.webapp.routers._helpers import BUILD_INFO, STATIC_DIR
from src.db import get_db, schema_version
from src.opener import HANDLER_PATH

router = APIRouter()


@router.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html missing")
    html = BUILD_INFO.stamp_html(index_path.read_text(encoding="utf-8"))
    # The shell must always revalidate: a cached shell pointing at an old
    # ?v= entry module would defeat the fleet-hash cache-busting entirely.
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True}


@router.get("/opener/opener.cmd", include_in_schema=False)
async def opener_handler() -> FileResponse:
    if not HANDLER_PATH.exists():
        raise HTTPException(status_code=404, detail="opener.cmd missing")
    return FileResponse(
        str(HANDLER_PATH), media_type="text/plain; charset=utf-8", filename="opener.cmd",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/version")
async def version(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    payload: dict[str, Any] = dict(BUILD_INFO.as_dict())
    # ``None`` (not a number) when the settings table is missing — an
    # unestablished fact is reported as unknown, never folded into "fine".
    payload["schema_version"] = schema_version(db)
    return payload
