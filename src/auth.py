"""Access control for the webapp — the fleet launcher's model, kept minimal.

Two classes of caller:

- **Loopback** (``127.0.0.1`` / ``::1`` — this PC, the tray, the ``tasks``
  CLI, the restart probe) is the owner and passes with no credential.
- **Everything else** (the tailnet, the LAN) must present the bearer token
  ``scripts/gen_token.py`` wrote into ``config/config.json`` — as an
  ``Authorization: Bearer <token>`` header (scripts, an LLM) or as the
  ``taskos_token`` cookie the ``/login`` page sets for 90 days (the phone).
  ``/login`` also accepts the optional password (``scripts/set_password.py``,
  stored as a PBKDF2 hash) and hands the same cookie back — a memorable
  secret to type instead of pasting a token.

No token configured (the committed sample) means **only loopback can use the
app**: the gate is closed, not open, and startup says so loudly.

What stays public on any client: the static assets (``/static/``, incl. the
manifest + icons a phone needs *before* it can log in), ``/healthz``,
``/api/version`` (the build-identity contract), the ``/login`` page and
``/api/login`` itself. Every other ``/api/`` path answers ``401`` with the
one JSON error envelope; a page request redirects to ``/login?next=…``.

Pure ASGI middleware (not ``BaseHTTPMiddleware``) so it never wraps the
response body — the static mount streams files, and the lifespan scope
passes straight through.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import AuthConfig

logger = logging.getLogger(__name__)

COOKIE_NAME = "taskos_token"
COOKIE_MAX_AGE = 90 * 24 * 3600  # 90 days — one login per phone per quarter
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

PUBLIC_PREFIXES = ("/static/",)
# /opener/opener.cmd: the per-PC folder opener (Step 9) — a second PC's install
# one-liner downloads it with Invoke-WebRequest, which carries no cookie; the
# file is public source anyway (it lives in the repo).
PUBLIC_EXACT = frozenset({"/healthz", "/api/version", "/login", "/api/login", "/opener/opener.cmd"})

_PBKDF2_ITERATIONS = 200_000
_HASH_PREFIX = "pbkdf2_sha256"


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    """``pbkdf2_sha256$<iterations>$<salt>$<digest>`` — stdlib only, salted."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "$".join([
        _HASH_PREFIX,
        str(_PBKDF2_ITERATIONS),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    ])


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a :func:`hash_password` value."""
    try:
        prefix, iterations, salt_b64, digest_b64 = stored.split("$")
        if prefix != _HASH_PREFIX:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def new_token() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------- the check

def is_loopback(host: str | None) -> bool:
    return (host or "") in LOOPBACK_HOSTS


def is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def token_matches(presented: str | None, auth: AuthConfig) -> bool:
    if not presented or not auth.token:
        return False
    return hmac.compare_digest(presented, auth.token)


def check_secret(secret: str, auth: AuthConfig) -> str | None:
    """What ``/login`` accepts: the token itself or the optional password.

    Returns ``"token"`` / ``"password"`` on success, ``None`` when refused.
    """
    if token_matches(secret, auth):
        return "token"
    if auth.password_hash and verify_password(secret, auth.password_hash):
        return "password"
    return None


def _cookie_value(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE_NAME:
                return v.strip()
    return None


def _bearer_value(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    return None


def classify(scope: Scope, auth: AuthConfig) -> str:
    """``"loopback"`` · ``"token"`` (bearer header or cookie) · ``"public"``
    (an exempt path) · ``"denied"``."""
    client = scope.get("client")
    host = client[0] if client else ""
    if is_loopback(host):
        return "loopback"
    path = scope.get("path", "")
    headers = scope.get("headers", [])
    if token_matches(_bearer_value(headers), auth) or token_matches(_cookie_value(headers), auth):
        return "token"
    if is_public_path(path):
        return "public"
    return "denied"


class AuthMiddleware:
    """The one auth choke point (see the module docstring)."""

    def __init__(self, app: ASGIApp, get_auth: Callable[[], AuthConfig]) -> None:
        self.app = app
        self._get_auth = get_auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = self._get_auth()
        verdict = classify(scope, auth)
        scope.setdefault("state", {})["auth"] = verdict
        if verdict != "denied":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        client = scope.get("client")
        host = client[0] if client else "?"
        response: Any
        if path.startswith("/api/"):
            logger.info("🔒 401 %s %s from %s", scope.get("method", "?"), path, host)
            detail = "sign in at /login" if auth.enabled else "no auth token configured — run scripts/gen_token.py"
            response = JSONResponse(
                {"error": {"code": "unauthorized", "message": "authentication required", "detail": detail}},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="task-os"'},
            )
        else:
            query = scope.get("query_string", b"").decode("latin-1")
            target = path + ("?" + query if query else "")
            response = RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=302)
        await response(scope, receive, send)
