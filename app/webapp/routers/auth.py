"""Login page, the token/password → cookie swap, and the access status.

    GET  /login        → the sign-in page (one field: token or password);
                         public — it is where a denied page request lands
    POST /api/login    → {secret} → verifies the bearer token or the optional
                         password (src.auth) and sets the ``taskos_token``
                         cookie for 90 days; 401 on refusal, 503 when no token
                         is configured (nothing to hand back)
    POST /api/logout   → clears the cookie
    GET  /api/status   → {https, auth: {enabled, password, client}} — how this
                         request came in and what the install accepts; drives
                         the Settings pane's "Phone access" card

Failed and successful sign-ins are logged with the client host (info level)
so a phone-side review is one grep of ``data/logs/task-os.log``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.webapp.routers._helpers import BUILD_INFO, STATIC_DIR
from src.auth import COOKIE_MAX_AGE, COOKIE_NAME, check_secret
from src.config import AuthConfig

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginBody(BaseModel):
    secret: str = ""


def _auth(request: Request) -> AuthConfig:
    return request.app.state.config.auth


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


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
    host = _client(request)
    if not auth.enabled:
        logger.warning("⚠️ login attempt from %s but no auth token is configured (scripts/gen_token.py)", host)
        raise HTTPException(status_code=503, detail="no auth token configured — run scripts/gen_token.py on the host")
    how = check_secret(body.secret.strip(), auth)
    if how is None:
        logger.warning("🚨 failed sign-in from %s (%d chars presented)", host, len(body.secret))
        raise HTTPException(status_code=401, detail="wrong token or password")
    logger.info("🔓 sign-in from %s via %s", host, how)
    response = JSONResponse({"ok": True, "via": how})
    response.set_cookie(
        COOKIE_NAME,
        auth.token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.post("/api/logout")
async def logout(request: Request) -> JSONResponse:
    logger.info("🔒 sign-out from %s", _client(request))
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    auth = _auth(request)
    return {
        "https": request.url.scheme == "https",
        "auth": {
            "enabled": auth.enabled,
            "password": bool(auth.password_hash),
            "client": getattr(request.state, "auth", "unknown"),
        },
    }
