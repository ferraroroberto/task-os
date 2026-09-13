"""Shared bits for the routers: paths, the once-per-process build identity,
the actor resolver and the JSON error shape."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from src.static_versioning import BuildInfo
from src.tasks_repo import DEFAULT_ACTOR
from src.team import NAME_COOKIE, member_from_cookie

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = PROJECT_ROOT / "app" / "webapp" / "static"

# Computed once at import: git SHA + fleet asset hash + build time. The tray
# restarts the webapp on every code change (restart recipe in CLAUDE.md), so
# there is no watcher and no per-request work.
BUILD_INFO = BuildInfo(STATIC_DIR, PROJECT_ROOT)

ACTOR_HEADER = "X-Actor"


def resolve_actor(request: Request, explicit: str | None = None) -> str:
    """Who is acting: an explicit body field → the ``X-Actor`` header → in
    team mode, the name this browser picked (``src.team``) → the first
    configured team member → ``"me"``."""
    if explicit and explicit.strip():
        return explicit.strip()
    header = request.headers.get(ACTOR_HEADER, "").strip()
    if header:
        return header
    config = getattr(request.app.state, "config", None)
    team = getattr(config, "team", None)
    if team is not None:
        picked = member_from_cookie(request.cookies.get(NAME_COOKIE), team)
        if picked:
            return picked
    people = getattr(team, "people", None) or []
    return str(people[0]) if people else DEFAULT_ACTOR


def error_response(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    """The one JSON error envelope every route family emits."""
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(body, status_code=status)


def service_unavailable(service: Any, code: str, name: str) -> JSONResponse:
    """The 409 for a background service that is off — or was never started.

    ``service`` is what the lifespan put on ``app.state`` (``None`` when it
    built none); its own ``reason`` says which of its failures applies. A
    missing service, and a blank reason, are worded here — the message is
    never null.
    """
    if service is None:
        return error_response(409, code, f"{name} service not started")
    return error_response(409, code, service.reason or f"{name} is off")
