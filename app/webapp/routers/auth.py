"""Login page, the token/password → cookie swap, team mode's pick-your-name,
and the access status.

    GET  /login        → the sign-in page (one field: token or password), and
                         in team mode the pick-your-name step (``?step=name``);
                         public — it is where a denied page request lands
    POST /api/login    → {secret} → verifies the bearer token or the optional
                         password (src.auth) and sets the ``taskos_token``
                         cookie for 90 days; in team mode the team password
                         sets the ``taskos_team`` cookie instead (``via:
                         "team"``); 401 on refusal, 503 when no token is
                         configured (nothing to hand back)
    POST /api/logout   → clears the cookie (and, in team mode, the team + name cookies)
    GET  /api/team     → {enabled, people: [{name, avatar}], you} — who can be
                         picked and who this browser is
    POST /api/team/name → {name} → sets the ``taskos_name`` cookie (an
                         authorship label, not a credential — src/team.py);
                         409 with team mode off, 422 for a name not in ``team.people``
    GET  /api/team/avatars/{index} → that person's ``data/avatars`` image, 404 without one

``access_status(request)`` — ``{https, auth: {enabled, password, client}}``:
how this request came in and what the install accepts. Folded into the one
``GET /api/status`` (``routers/mirror``) that drives the Settings pane.

Failed and successful sign-ins are logged with the client host (info level)
so a phone-side review is one grep of ``data/logs/task-os.log``. A presented
secret is never logged — only its length.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.webapp.routers._helpers import BUILD_INFO, STATIC_DIR, error_response
from src.auth import COOKIE_MAX_AGE, COOKIE_NAME, TEAM_COOKIE, check_secret, team_session
from src.config import AuthConfig, TeamConfig
from src.team import NAME_COOKIE, avatar_file, encode_name, member_from_cookie

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginBody(BaseModel):
    secret: str = ""


class NameBody(BaseModel):
    name: str = ""


def _auth(request: Request) -> AuthConfig:
    return request.app.state.config.auth


def _team(request: Request) -> TeamConfig:
    return request.app.state.config.team


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _set_cookie(response: JSONResponse, request: Request, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.get("/login", include_in_schema=False)
async def login_page() -> HTMLResponse:
    page = STATIC_DIR / "login.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="login.html missing")
    html = BUILD_INFO.stamp_html(page.read_text(encoding="utf-8"))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


@router.post("/api/login")
async def login(body: LoginBody, request: Request) -> JSONResponse:
    auth = _auth(request)
    team = _team(request)
    host = _client(request)
    if not auth.enabled:
        logger.warning("⚠️ login attempt from %s but no auth token is configured (scripts/gen_token.py)", host)
        raise HTTPException(status_code=503, detail="no auth token configured — run scripts/gen_token.py on the host")
    how = check_secret(body.secret.strip(), auth, team)
    if how is None:
        logger.warning("🚨 failed sign-in from %s (%d chars presented)", host, len(body.secret))
        raise HTTPException(status_code=401, detail="wrong token or password")
    logger.info("🔓 sign-in from %s via %s", host, how)
    if how == "team":
        session = team_session(auth, team)
        if session is None:  # unreachable: check_secret answers "team" only when one exists
            raise HTTPException(status_code=401, detail="wrong token or password")
        you = member_from_cookie(request.cookies.get(NAME_COOKIE), team)
        response = JSONResponse({"ok": True, "via": how, "you": you})
        _set_cookie(response, request, TEAM_COOKIE, session)
        return response
    response = JSONResponse({"ok": True, "via": how})
    _set_cookie(response, request, COOKIE_NAME, auth.token)
    return response


@router.post("/api/logout")
async def logout(request: Request) -> JSONResponse:
    logger.info("🔒 sign-out from %s", _client(request))
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    if _team(request).enabled:
        response.delete_cookie(TEAM_COOKIE, path="/")
        response.delete_cookie(NAME_COOKIE, path="/")
    return response


@router.get("/api/team")
async def team_info(request: Request) -> dict[str, Any]:
    team = _team(request)
    if not team.enabled:
        return {"enabled": False, "people": [], "you": None}
    people = [
        {"name": name, "avatar": f"/api/team/avatars/{i}" if avatar_file(name) else None}
        for i, name in enumerate(team.people)
    ]
    return {"enabled": True, "people": people, "you": member_from_cookie(request.cookies.get(NAME_COOKIE), team)}


@router.post("/api/team/name")
async def pick_name(body: NameBody, request: Request) -> JSONResponse:
    team = _team(request)
    if not team.enabled:
        return error_response(409, "team_disabled", "team mode is off")
    name = body.name.strip()
    if name not in team.people:
        return error_response(422, "validation_error", "not a team member", {"name": name})
    logger.info("👤 %s picked the name %s", _client(request), name)
    response = JSONResponse({"ok": True, "you": name})
    _set_cookie(response, request, NAME_COOKIE, encode_name(name))
    return response


@router.get("/api/team/avatars/{index}")
async def team_avatar(index: int, request: Request) -> FileResponse:
    team = _team(request)
    # Addressed by position, never by a client-supplied file name: the path is
    # built from the configured name alone.
    if not team.enabled or not 0 <= index < len(team.people):
        raise HTTPException(status_code=404, detail="no such team member")
    path = avatar_file(team.people[index])
    if path is None:
        raise HTTPException(status_code=404, detail="no avatar")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def access_status(request: Request) -> dict[str, Any]:
    """The transport + access facts for ``GET /api/status``."""
    auth = _auth(request)
    return {
        "https": request.url.scheme == "https",
        "auth": {
            "enabled": auth.enabled,
            "password": bool(auth.password_hash),
            "client": getattr(request.state, "auth", "unknown"),
        },
    }
