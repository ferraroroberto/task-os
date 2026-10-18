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

**One token per person** (#474): those two secrets are the install owner's
(the first member); another member gets their own (``auth.people.<id>``,
``gen_token.py --person`` / ``set_password.py --person``), so the credential
itself says who signed in. Each passes the gate exactly as the owner's does,
``/login`` hands a member back their own token as the cookie, and a member
removed from the config has no token any more (401). :func:`resolve_viewer`
reads the member — only from a credential that already passed — onto
``scope["state"]["viewer"]`` (``GET /api/me``). A person binding is never a
credential by itself.

**Team mode** (``team.enabled``, Step 12) adds one more way through the same
gate and loosens nothing: ``/login`` also accepts the shared team password
(``scripts/set_team_password.py``, the same PBKDF2 hash) and hands back a
``taskos_team`` cookie — never the owner's token (it grants the same access to
the app while it is valid, but it is not the bearer secret and cannot outlive
a change of either secret). Its value is derived (HMAC of the team password hash keyed by
the token), so rotating either one signs every teammate out, and with no token
configured there is no team cookie either: the gate stays closed. A teammate
must then pick a name (``src/team.py``) before any page loads. Team mode off =
the team password and the team cookie are never consulted.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import IMPLICIT_PERSON, AuthConfig, Person, TeamConfig
from src.team import NAME_COOKIE, member_from_cookie

logger = logging.getLogger(__name__)

COOKIE_NAME = "taskos_token"
TEAM_COOKIE = "taskos_team"
COOKIE_MAX_AGE = 90 * 24 * 3600  # 90 days — one login per phone per quarter
_TEAM_SESSION_CONTEXT = b"task-os team session\x00"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

PUBLIC_PREFIXES = ("/static/",)
# /opener/opener.{cmd,ps1}: the per-PC folder opener (Step 9) — a second PC's
# install one-liner downloads both with Invoke-WebRequest, which carries no
# cookie; the files are public source anyway (they live in the repo).
PUBLIC_EXACT = frozenset({
    "/healthz", "/api/version", "/login", "/api/login",
    "/opener/opener.cmd", "/opener/opener.ps1",
})

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


def token_person(presented: str | None, auth: AuthConfig) -> str | None:
    """The member a presented token belongs to — the owner for ``auth.token``,
    a member for their own ``auth.people`` token (#474) — else ``None``."""
    if not presented:
        return None
    # Bytes, not str: compare_digest refuses a non-ASCII str, and a cookie is
    # now read on loopback too, where a stray one must be no one, never a 500.
    candidate = presented.encode("utf-8", "surrogatepass")
    for person_id, token in auth.tokens():
        if hmac.compare_digest(candidate, token.encode("utf-8")):
            return person_id
    return None


def token_matches(presented: str | None, auth: AuthConfig) -> bool:
    return token_person(presented, auth) is not None


def team_session(auth: AuthConfig, team: TeamConfig) -> str | None:
    """The ``taskos_team`` cookie value, or ``None`` when team sign-in is off.

    Derived, never stored: HMAC-SHA256 of the team password hash keyed by the
    bearer token. Needs all three of team mode on, a team password and a token.
    """
    if not (team.enabled and team.password_hash and auth.token):
        return None
    mac = hmac.new(auth.token.encode("utf-8"), _TEAM_SESSION_CONTEXT + team.password_hash.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode("ascii").rstrip("=")


def team_session_matches(presented: str | None, auth: AuthConfig, team: TeamConfig) -> bool:
    expected = team_session(auth, team)
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented, expected)


@dataclass(frozen=True)
class SignIn:
    """A secret ``/login`` accepted: ``via`` is ``"token"`` / ``"password"`` /
    ``"team"``; ``token`` the bearer the ``taskos_token`` cookie carries —
    the signing-in member's own ("" for the team sign-in, whose cookie is
    derived)."""

    via: str
    token: str = ""


def check_secret(secret: str, auth: AuthConfig, team: TeamConfig | None = None) -> SignIn | None:
    """What ``/login`` accepts: a member's token itself, a member's optional
    password (the owner's or their own, #474), or — in team mode — the shared
    team password. ``None`` when refused."""
    person = token_person(secret, auth)
    if person is not None:
        return SignIn("token", secret)
    for person, stored in auth.password_hashes():
        # A password only unlocks a token: a member with none has nothing to hand back.
        if auth.token_of(person) and verify_password(secret, stored):
            return SignIn("password", auth.token_of(person))
    if team is not None and team_session(auth, team) and verify_password(secret, team.password_hash):
        return SignIn("team")
    return None


def _cookie_value(headers: list[tuple[bytes, bytes]], cookie: str = COOKIE_NAME) -> str | None:
    for name, value in headers:
        if name != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            k, _, v = part.strip().partition("=")
            if k == cookie:
                return v.strip()
    return None


def _bearer_value(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    return None


def classify(scope: Scope, auth: AuthConfig, team: TeamConfig | None = None) -> str:
    """``"loopback"`` · ``"token"`` (bearer header or cookie) · ``"team"`` (the
    team sign-in cookie, team mode only) · ``"public"`` (an exempt path) ·
    ``"denied"``."""
    client = scope.get("client")
    host = client[0] if client else ""
    if is_loopback(host):
        return "loopback"
    path = scope.get("path", "")
    headers = scope.get("headers", [])
    if token_matches(_bearer_value(headers), auth) or token_matches(_cookie_value(headers), auth):
        return "token"
    if team is not None and team_session_matches(_cookie_value(headers, TEAM_COOKIE), auth, team):
        return "team"
    if is_public_path(path):
        return "public"
    return "denied"


@dataclass(frozen=True)
class Viewer:
    """Who a request is (#474) — ``GET /api/me``'s body. ``id`` / ``name`` are
    the member; ``via`` how that was established: ``"token"`` (their own
    token, as a bearer header or the cookie a token or password sign-in set),
    ``"team"`` (the team sign-in: the name it picked, ``id`` ``None`` when
    that name is no member, both ``None`` before a pick) or ``"loopback"``
    (this PC with no credential: the install owner)."""

    id: str | None
    name: str | None
    via: str


def resolve_viewer(
    scope: Scope, verdict: str, auth: AuthConfig, team: TeamConfig, people: Sequence[Person]
) -> Viewer | None:
    """The member behind a request the gate let through (``verdict`` is
    :func:`classify`'s), read only from a credential that passed it: a
    member's token on any client, loopback included → that member; a team
    sign-in → the member its name step picked; plain loopback → the install
    owner (the first member). A denied or anonymous public request is nobody."""
    names = {p.id: p.name for p in people}
    headers = scope.get("headers", [])
    for presented in (_bearer_value(headers), _cookie_value(headers)):
        person = token_person(presented, auth)
        if person is not None and person in names:
            return Viewer(person, names[person], "token")
    if verdict == "team":
        picked = member_from_cookie(_cookie_value(headers, NAME_COOKIE), team)
        member = next((p.id for p in people if p.name == picked), None) if picked else None
        return Viewer(member, picked, "team")
    if verdict == "loopback" and people:
        return Viewer(people[0].id, people[0].name, "loopback")
    return None


def _login_redirect(scope: Scope, extra: str = "") -> RedirectResponse:
    path: str = scope.get("path", "")
    query = scope.get("query_string", b"").decode("latin-1")
    target = path + ("?" + query if query else "")
    return RedirectResponse(f"/login?{extra}next={quote(target, safe='')}", status_code=302)


class AuthMiddleware:
    """The one auth choke point (see the module docstring)."""

    def __init__(
        self,
        app: ASGIApp,
        get_auth: Callable[[], AuthConfig],
        get_team: Callable[[], TeamConfig] = TeamConfig,
        get_people: Callable[[], Sequence[Person]] = lambda: (IMPLICIT_PERSON,),
    ) -> None:
        self.app = app
        self._get_auth = get_auth
        self._get_team = get_team
        self._get_people = get_people

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = self._get_auth()
        team = self._get_team()
        verdict = classify(scope, auth, team)
        state = scope.setdefault("state", {})
        state["auth"] = verdict
        state["viewer"] = resolve_viewer(scope, verdict, auth, team, self._get_people())
        path: str = scope.get("path", "")
        if verdict == "team" and not path.startswith("/api/") and not is_public_path(path):
            # A teammate names themselves before any page loads, so nothing
            # they write is signed with the owner's default name.
            if member_from_cookie(_cookie_value(scope.get("headers", []), NAME_COOKIE), team) is None:
                await _login_redirect(scope, "step=name&")(scope, receive, send)
                return
        if verdict != "denied":
            await self.app(scope, receive, send)
            return

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
            response = _login_redirect(scope)
        await response(scope, receive, send)
