"""Mirror + backup route family — the install status and on-demand runs.

    GET  /api/status          {https, auth: {enabled, password, client},
                               mirror: {enabled, dir, files, last_export, last_import,
                               errors, …}, backup: {enabled, dir, last_file, next_run, …},
                               folders: {enabled, roots, entries, last_indexed, indexing, …},
                               opener: {install, uninstall, env_template, installed_here},
                               placeholders: {…}}
                              — the one status the Settings pane reads (the https /
                              auth part comes from routers/auth.access_status; the
                              folder index + opener parts are Step 9)
    POST /api/mirror/export   full export now → {tasks, written, removed}
    POST /api/mirror/import   one watcher pass now → {checked, imported, errors}
    POST /api/backup          one backup now → {file, dir} (409 when disabled)

The services live on ``app.state.mirror`` / ``app.state.backup`` (started by
the lifespan); when the mirror is not configured the status says so and the
run endpoints answer 409 with the reason — never a silent no-op. The
``tasks`` CLI calls these when the app is up so a single process owns the
watcher's bookkeeping.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.webapp.routers._helpers import error_response
from app.webapp.routers.auth import access_status
from src import opener
from src.db import get_db

router = APIRouter(prefix="/api", tags=["mirror"])


def _services(request: Request) -> tuple[Any, Any]:
    return getattr(request.app.state, "mirror", None), getattr(request.app.state, "backup", None)


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    mirror, backup = _services(request)
    folders = getattr(request.app.state, "folders", None)
    ph = dict(request.app.state.config.placeholders)
    return {
        **access_status(request),
        "mirror": mirror.status() if mirror else {"enabled": False, "reason": "mirror service not started"},
        "backup": backup.status() if backup else {"enabled": False, "reason": "backup service not started"},
        "folders": folders.status() if folders else {"enabled": False, "reason": "folder index service not started"},
        "opener": opener.status(ph),
        "placeholders": ph,
    }


@router.post("/mirror/export")
def mirror_export(request: Request, db: sqlite3.Connection = Depends(get_db)) -> Any:
    mirror, _ = _services(request)
    if mirror is None or not mirror.enabled:
        reason = mirror.reason if mirror else "mirror service not started"
        return error_response(409, "mirror_disabled", reason)
    return mirror.export_all(db)


@router.post("/mirror/import")
def mirror_import(request: Request, db: sqlite3.Connection = Depends(get_db)) -> Any:
    mirror, _ = _services(request)
    if mirror is None or not mirror.enabled:
        reason = mirror.reason if mirror else "mirror service not started"
        return error_response(409, "mirror_disabled", reason)
    return mirror.import_tick(db)


@router.post("/backup")
def backup_now(request: Request) -> Any:
    _, backup = _services(request)
    if backup is None or not backup.enabled:
        reason = backup.reason if backup else "backup service not started"
        return error_response(409, "backup_disabled", reason)
    target = backup.run_now()
    if target is None:
        return error_response(500, "backup_failed", backup.last_error or "backup failed")
    return {"file": target.name, "dir": str(target.parent), "path": str(target)}
