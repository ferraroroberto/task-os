"""The per-user registrations task-os uses, added only where none exists.

Two, both under the current user (no admin):

* **the folder opener** — the ``taskos://`` URL scheme (``HKCU\\Software\\Classes``)
  that opens a task's folder link on this PC. Registered by the same code as
  ``assets/opener/install_opener.py``, and only when the scheme is not
  registered at all: an existing registration, ours or another tool's, is
  ``kept`` untouched.
* **the sign-in start** — a ``task-os.bat`` in the user's Startup folder that
  calls this checkout's ``tray.bat``. Opt-in (``--startup``): another launcher
  may already start the tray at sign-in, and a second start is not this
  installer's call to make. Any Startup entry already naming task-os or this
  checkout's ``tray.bat`` counts as present and is ``kept``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from src.runtime import files as runtime_files

SCHEME = "taskos"
STARTUP_FILE_NAME = "task-os.bat"
_OPENER_INSTALLER = Path(__file__).resolve().parents[2] / "assets" / "opener" / "install_opener.py"


@dataclass(frozen=True)
class MachineStep:
    """One registration: ``kept`` · ``registered`` · ``would-register`` · ``not-registered`` ·
    ``skipped`` (not this OS) · ``failed``."""

    item: str
    status: str
    detail: str = ""


def opener_state(scheme: str = SCHEME) -> bool | None:
    """Is ``scheme://`` registered for this user? ``None`` when that cannot be read."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{scheme}\shell\open\command") as key:
            value, _ = winreg.QueryValueEx(key, None)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return bool(str(value).strip())


def _opener_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("install_opener", _OPENER_INSTALLER)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {_OPENER_INSTALLER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_opener(*, whatif: bool, scheme: str = SCHEME, dest: Path | None = None) -> MachineStep:
    """Register the folder opener when ``scheme://`` has no handler for this user."""
    item = f"folder opener ({scheme}://)"
    state = opener_state(scheme)
    if state is None:
        reason = "not Windows" if sys.platform != "win32" else "the registry could not be read"
        return MachineStep(item, "skipped", reason)
    if state:
        return MachineStep(item, "kept", "already registered for this user")
    if whatif:
        return MachineStep(item, "would-register", "HKCU, per user, no admin")
    try:
        installer = _opener_installer()
        target = dest or installer.default_dest()
        used_launcher = installer.install(target, scheme)
    except (OSError, ImportError, SystemExit) as exc:
        return MachineStep(item, "failed", str(exc))
    mode = "launcher" if used_launcher else "fallback: this PC cannot run the launcher (assets/opener/README.md)"
    return MachineStep(item, "registered", f"handler in {target}; {mode}")


def startup_dir() -> Path:
    """This user's Startup folder."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_entry(repo: Path, folder: Path) -> Path | None:
    """An existing Startup entry for task-os: named for it, or a script naming this ``tray.bat``."""
    if not folder.is_dir():
        return None
    tray = str(repo.resolve() / "tray.bat").lower()
    for entry in sorted(folder.iterdir()):
        if entry.name.lower().startswith("task-os"):
            return entry
        if entry.suffix.lower() in (".bat", ".cmd"):
            try:
                text = entry.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            if tray in text:
                return entry
    return None


def startup_script(repo: Path) -> str:
    """The Startup entry's text: start this checkout's tray (idempotent: a running tray is a no-op)."""
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "REM Starts the task-os tray at sign-in (written by setup.bat -Startup). Delete this file to stop it.\r\n"
        f'call "{repo.resolve() / "tray.bat"}"\r\n'
    )


def ensure_startup(repo: Path, *, whatif: bool, enable: bool, folder: Path | None = None) -> MachineStep:
    """Add the sign-in start when asked for and none exists."""
    item = "start at sign-in"
    where = folder or startup_dir()
    existing = startup_entry(repo, where)
    if existing is not None:
        return MachineStep(item, "kept", f"already present: {existing.name}")
    if not enable:
        return MachineStep(item, "not-registered", "opt-in: setup.bat -Startup")
    target = where / STARTUP_FILE_NAME
    if whatif:
        return MachineStep(item, "would-register", str(target))
    runtime_files.make_dir(where)
    runtime_files.save_text(target, startup_script(repo), newline="")
    return MachineStep(item, "registered", str(target))
