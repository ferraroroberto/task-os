"""What the app knows about the per-PC folder opener (``opener/``) — Step 9.

The handler itself is ``opener/opener.cmd``, the launcher Windows actually
registers is ``opener/opener.ps1``, and the install one-liner lives in
``opener/install.txt`` (single source: the first non-comment line is the
install command, the second the uninstall command). This module reads them for
``GET /api/status`` → ``opener`` so the Settings *Folder opener* card can show
the command with this server's address filled in, plus an ``opener.env``
template built from **this install's** placeholders (the names the refs use,
with the values this PC resolves them to as a starting point — another PC
edits the paths).

Whether the opener is installed on the machine that runs the server is a
fact the server can establish (``HKCU\\Software\\Classes\\taskos``); for any
other client it is unknown, and the API says so (``installed_here`` only).
The same key also says *which* registration shape is in use (``mode``) —
``launcher`` or the ``fallback`` a locked-down PC falls back to.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENER_DIR = PROJECT_ROOT / "opener"
HANDLER_PATH = OPENER_DIR / "opener.cmd"
LAUNCHER_PATH = OPENER_DIR / "opener.ps1"
INSTALL_TXT = OPENER_DIR / "install.txt"
BASE_URL_TOKEN = "<base-url>"


def install_commands(path: Path = INSTALL_TXT) -> tuple[str, str]:
    """``(install, uninstall)`` from ``install.txt`` — empty strings when missing."""
    try:
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    except OSError as exc:
        logger.warning("⚠️ opener: cannot read %s (%s)", path, exc)
        return "", ""
    commands = [ln for ln in lines if ln and not ln.startswith("#")]
    install = commands[0] if commands else ""
    uninstall = commands[1] if len(commands) > 1 else ""
    return install, uninstall


def env_template(placeholders: Mapping[str, str]) -> str:
    """An ``opener.env`` starting point: every configured placeholder as ``name=path``.

    ``{onedrive}`` / ``{user}`` are commented out (the opener takes them from
    the environment unless overridden); ``sharepoint:<name>`` keys become
    ``<name>=<path>`` lines, which is exactly what ``{sharepoint:<name>}`` reads.
    """
    out = ["# task-os opener placeholders — one name=path line per placeholder, no quotes."]
    for name in sorted(placeholders):
        value = str(placeholders[name] or "").replace("/", "\\")
        if name.startswith("sharepoint:"):
            out.append(f"{name.split(':', 1)[1]}={value}")
        elif name in ("onedrive", "user"):
            out.append(f"# {name}={value}    (uncomment to override the environment on this PC)")
        else:
            out.append(f"{name}={value}")
    if not any(n.startswith("sharepoint:") for n in placeholders):
        out.append("# docs=C:\\Users\\me\\Tenant\\docs - Documents    → {sharepoint:docs}")
    return "\n".join(out) + "\n"


def _registered_command() -> str | None:
    """The registered ``taskos://`` command on **this** machine, or ``None``."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\taskos\shell\open\command") as k:
            value, _ = winreg.QueryValueEx(k, None)
        return str(value)
    except OSError:
        return None


def installed_here() -> bool | None:
    """``True`` / ``False`` on Windows, ``None`` (unknown) elsewhere."""
    if sys.platform != "win32":
        return None
    command = (_registered_command() or "").lower()
    return "opener.ps1" in command or "opener.cmd" in command


def registration_mode() -> str | None:
    """Which shape is registered here: ``"launcher"``, ``"fallback"``, or ``None``.

    ``None`` covers both "not installed" and "not this OS" — the caller already
    has :func:`installed_here` for that distinction. The mode matters because
    the fallback hands the URL to a command interpreter as a string, which
    re-parses it (see ``opener/opener.ps1``); it is reported so a degraded
    install is visible rather than silent.
    """
    command = (_registered_command() or "").lower()
    if "opener.ps1" in command:
        return "launcher"
    if "opener.cmd" in command:
        return "fallback"
    return None


def status(placeholders: Mapping[str, str]) -> dict[str, Any]:
    install, uninstall = install_commands()
    return {
        "handler_available": HANDLER_PATH.exists() and LAUNCHER_PATH.exists(),
        "install": install,
        "uninstall": uninstall,
        "base_url_token": BASE_URL_TOKEN,
        "env_template": env_template(placeholders),
        "installed_here": installed_here(),
        "mode": registration_mode(),
    }
