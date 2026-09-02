"""Project configuration — ``config/config.json`` with a committed sample twin.

The real file is gitignored (it carries this machine's paths); the committed
``config/config.sample.json`` documents every key. Loading is defensive: a
missing real file falls back to the sample so a fresh clone boots — with the
markdown mirror and the backup **off** (the sample's placeholders resolve to
a real synced folder; a checkout without its own config must never write
into it, #126) — and every key has a code-level default so a partial file
never crashes startup.

``TASKOS_CONFIG_PATH`` overrides the file location — the e2e harness points a
disposable instance at a temp copy so the gate never reads (or writes) the
real config.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"
CONFIG_SAMPLE_PATH = CONFIG_DIR / "config.sample.json"
CONFIG_PATH_ENV = "TASKOS_CONFIG_PATH"

DEFAULT_PORT = 8448

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_:.-]+)\}")


def resolve_placeholders(value: str, placeholders: Mapping[str, str]) -> str:
    """Expand ``{onedrive}``-style tokens from ``config.placeholders``.

    Unknown tokens are left verbatim so the caller can see (and report) what
    is missing — see :func:`unresolved_placeholders`. Used for the mirror /
    backup dirs here; folder refs go through ``src.placeholders`` (Step 9),
    which builds on this.
    """
    return _PLACEHOLDER_RE.sub(lambda m: str(placeholders.get(m.group(1), m.group(0))), value or "")


def unresolved_placeholders(value: str) -> list[str]:
    """The ``{tokens}`` still present after :func:`resolve_placeholders`."""
    return _PLACEHOLDER_RE.findall(value or "")


@dataclass(frozen=True)
class IssuesConfig:
    provider: str = "github"
    owner: str = "ferraroroberto"
    assignee: str = "@me"
    sync_minutes: int = 10


@dataclass(frozen=True)
class MirrorConfig:
    dir: str = "{onedrive}/task-os/mirror"
    backup_dir: str = "{onedrive}/task-os/backup"


@dataclass(frozen=True)
class SearchConfig:
    folder_roots: list[str] = field(default_factory=list)
    email_db: str = ""


@dataclass(frozen=True)
class TeamConfig:
    enabled: bool = False
    people: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuthConfig:
    """Non-loopback access (Step 7). ``token`` is the bearer secret
    ``scripts/gen_token.py`` writes; ``password_hash`` the optional memorable
    alternative ``scripts/set_password.py`` stores (PBKDF2, never plaintext).
    Both empty (the committed sample) = only this PC can use the app."""

    token: str = ""
    password_hash: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True)
class AppConfig:
    site: str = "home"
    port: int = DEFAULT_PORT
    issues: IssuesConfig = field(default_factory=IssuesConfig)
    placeholders: dict[str, str] = field(default_factory=dict)
    web_roots: dict[str, str] = field(default_factory=dict)
    mirror: MirrorConfig = field(default_factory=MirrorConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    source_path: Path | None = None


def config_path() -> Path:
    """The config file this process reads: env override → real → sample."""
    override = os.environ.get(CONFIG_PATH_ENV, "").strip()
    if override:
        return Path(override)
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    return CONFIG_SAMPLE_PATH


def _is_sample(src: Path) -> bool:
    """``src`` is the committed sample itself — by any spelling of its path."""
    try:
        return src.resolve() == CONFIG_SAMPLE_PATH.resolve()
    except OSError:
        return src == CONFIG_SAMPLE_PATH


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _flatten_placeholders(raw: dict[str, Any]) -> dict[str, str]:
    """``{"onedrive": "E:/onedrive", "sharepoint": {"docs": "…"}}`` → flat tokens.

    A nested map becomes ``<group>:<name>`` keys (``sharepoint:docs``), which
    is exactly the token spelled inside a folder ref (``{sharepoint:docs}``),
    so :func:`resolve_placeholders` needs no special case. Scalars stay as
    they are.
    """
    flat: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            for sub, sub_value in value.items():
                flat[f"{key}:{sub}"] = str(sub_value)
        else:
            flat[str(key)] = str(value)
    return flat


def load_config(path: Path | None = None) -> AppConfig:
    """Parse ``path`` (default: :func:`config_path`) into an :class:`AppConfig`.

    A missing or unparseable file logs a warning and yields the defaults —
    the webapp must still boot so the failure is visible in the UI/log rather
    than as a dead port.
    """
    src = path or config_path()
    raw: dict[str, Any] = {}
    try:
        raw = _as_dict(json.loads(src.read_text(encoding="utf-8")))
    except FileNotFoundError:
        logger.warning("⚠️ config: %s not found — using built-in defaults", src)
    except (OSError, ValueError) as exc:
        logger.warning("⚠️ config: could not parse %s (%s) — using built-in defaults", src, exc)

    issues = _as_dict(raw.get("issues"))
    mirror = _as_dict(raw.get("mirror"))
    if _is_sample(src):
        # The sample documents the shape; its placeholders resolve to a real
        # synced folder on the developer's machine. A checkout without its own
        # config/config.json (a fresh clone, a git worktree) must therefore
        # never mirror or back up into it: two databases rendering into one
        # folder is how the live one lost data (#126). Everything read-only
        # (search roots, the issue provider) keeps working from the sample.
        mirror = {"dir": "", "backup_dir": ""}
        logger.warning(
            "⚠️ config: no config/config.json — using the committed sample; the markdown mirror and "
            "the backup stay off until you create it (the sample is documentation, never a folder to write into)"
        )
    search = _as_dict(raw.get("search"))
    team = _as_dict(raw.get("team"))
    auth = _as_dict(raw.get("auth"))
    placeholders = _flatten_placeholders(_as_dict(raw.get("placeholders")))
    # same nested-map flattening as placeholders: web_roots.sharepoint.docs → "sharepoint:docs"
    web_roots = _flatten_placeholders(_as_dict(raw.get("web_roots")))

    try:
        port = int(raw.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        logger.warning("⚠️ config: invalid port %r — falling back to %d", raw.get("port"), DEFAULT_PORT)
        port = DEFAULT_PORT

    return AppConfig(
        site=str(raw.get("site", "home")),
        port=port,
        issues=IssuesConfig(
            provider=str(issues.get("provider", "github")),
            owner=str(issues.get("owner", "")),
            assignee=str(issues.get("assignee", "@me")),
            sync_minutes=int(issues.get("sync_minutes", 10) or 10),
        ),
        placeholders=placeholders,
        web_roots=web_roots,
        mirror=MirrorConfig(
            dir=str(mirror.get("dir", MirrorConfig.dir)),
            backup_dir=str(mirror.get("backup_dir", MirrorConfig.backup_dir)),
        ),
        search=SearchConfig(
            folder_roots=_as_str_list(search.get("folder_roots")),
            email_db=str(search.get("email_db", "")),
        ),
        team=TeamConfig(
            enabled=bool(team.get("enabled", False)),
            people=_as_str_list(team.get("people")),
        ),
        auth=AuthConfig(
            token=str(auth.get("token", "") or "").strip(),
            password_hash=str(auth.get("password_hash", "") or "").strip(),
        ),
        source_path=src,
    )


def save_auth(*, token: str | None = None, password_hash: str | None = None, path: Path | None = None) -> Path:
    """Write ``auth.token`` / ``auth.password_hash`` into the **real** config.

    Only the fields passed (non-``None``) change; everything else in the file
    is preserved. A missing ``config/config.json`` is created from the
    committed sample first — the sample itself is never written (it is the
    public twin and must keep both fields empty). Used by ``scripts/gen_token.py``
    and ``scripts/set_password.py``; the running app re-reads config on
    restart only (``tray.bat --restart``).
    """
    target = path or CONFIG_PATH
    if target == CONFIG_SAMPLE_PATH:
        raise ValueError("refusing to write secrets into config.sample.json")
    if target.exists():
        raw = _as_dict(json.loads(target.read_text(encoding="utf-8")))
    else:
        raw = _as_dict(json.loads(CONFIG_SAMPLE_PATH.read_text(encoding="utf-8")))
        logger.info("ℹ️ config: creating %s from the sample", target)
    auth = _as_dict(raw.get("auth"))
    if token is not None:
        auth["token"] = token
    if password_hash is not None:
        auth["password_hash"] = password_hash
    raw["auth"] = {"token": str(auth.get("token", "")), "password_hash": str(auth.get("password_hash", ""))}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
