"""Shared bits for the routers: paths, the once-per-process build identity,
the actor resolver and the JSON error shape."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from src.static_versioning import BuildInfo
from src.tasks_repo import DEFAULT_ACTOR

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = PROJECT_ROOT / "app" / "webapp" / "static"

# Computed once at import: git SHA + fleet asset hash + build time. The tray
# restarts the webapp on every code change (restart recipe in CLAUDE.md), so
# there is no watcher and no per-request work.
BUILD_INFO = BuildInfo(STATIC_DIR, PROJECT_ROOT)

ACTOR_HEADER = "X-Actor"


def resolve_actor(request: Request, explicit: str | None = None) -> str:
    """Who is acting: an explicit body field → the ``X-Actor`` header → the
    first configured team member → ``"me"``."""
    if explicit and explicit.strip():
        return explicit.strip()
    header = request.headers.get(ACTOR_HEADER, "").strip()
    if header:
        return header
    config = getattr(request.app.state, "config", None)
    people = getattr(getattr(config, "team", None), "people", None) or []
    return str(people[0]) if people else DEFAULT_ACTOR


def error_response(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    """The one JSON error envelope every route family emits."""
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(body, status_code=status)
