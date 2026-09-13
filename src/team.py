"""Team mode's authorship side (Step 12): who a browser says it is.

With ``team.enabled`` each browser picks one name from ``team.people`` once;
the choice rides the ``taskos_name`` cookie and becomes the ``author`` /
``actor`` on the comments and activity it writes (``routers/_helpers.
resolve_actor``). **The name is an authorship label, not a credential**: it
grants no access (that is ``src/auth.py``'s gate — loopback, the token, or the
team sign-in), anyone who can already write can also say any name through the
API's ``actor`` / ``X-Actor``, and it is ignored unless it names someone
currently listed in the config. Team mode off = the cookie is never read.

Avatars are optional: ``data/avatars/<slug>.<png|jpg|jpeg|webp>``, the slug
being the name lower-cased with every run of other characters as one ``-``
(``Sam Rivera`` → ``sam-rivera.png``). A person with no file gets initials.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote

from src.config import PROJECT_ROOT, TeamConfig

NAME_COOKIE = "taskos_name"
AVATARS_DIR = PROJECT_ROOT / "data" / "avatars"
AVATAR_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def encode_name(name: str) -> str:
    """The cookie value for ``name`` — percent-encoded, so spaces and accents survive."""
    return quote(name, safe="")


def member_from_cookie(value: str | None, team: TeamConfig) -> str | None:
    """The configured team member a ``taskos_name`` cookie names, else ``None``
    (team mode off, no cookie, or a name no longer in ``team.people``)."""
    if not team.enabled or not value:
        return None
    name = unquote(value).strip()
    return name if name and name in team.people else None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def avatar_file(name: str, avatars_dir: Path | None = None) -> Path | None:
    """The avatar image for ``name``, or ``None`` when there is none."""
    base = avatars_dir or AVATARS_DIR
    stem = slug(name)
    if not stem:
        return None
    for suffix in AVATAR_SUFFIXES:
        candidate = base / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None
