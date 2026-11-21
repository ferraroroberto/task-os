"""``requirements.txt`` into this checkout's ``.venv``, only what is missing.

pip's own resolver answers the question (``--dry-run --report``), so "nothing
to install" is pip's statement, not a guess; a report that cannot be read is
``failed``, never ``unchanged``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.no_window import NO_WINDOW

#: A resolve that downloads nothing still reads every index page it needs.
DRY_RUN_TIMEOUT_S = 600
#: A first install on a fresh PC downloads every wheel.
INSTALL_TIMEOUT_S = 1800


@dataclass(frozen=True)
class RequirementsStep:
    """``unchanged`` · ``installed`` · ``would-install`` · ``failed``."""

    status: str
    packages: tuple[str, ...] = ()
    detail: str = ""


def running_in_venv(repo: Path) -> bool:
    """Is this interpreter the checkout's own ``.venv`` (a junctioned one included)?"""
    try:
        return Path(sys.prefix).resolve() == (repo / ".venv").resolve()
    except OSError:
        return False


def _pip(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pip", *args, "--disable-pip-version-check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False, creationflags=NO_WINDOW,
    )


def missing_packages(requirements: Path) -> tuple[list[str] | None, str]:
    """``name==version`` pip would install, or ``None`` and why it could not tell."""
    try:
        done = _pip(["install", "-r", str(requirements), "--dry-run", "--quiet", "--report", "-"], DRY_RUN_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"pip did not run ({exc})"
    if done.returncode != 0:
        return None, f"pip exit {done.returncode}: {done.stderr.strip()[-300:]}"
    try:
        report = json.loads(done.stdout)
        return [f"{i['metadata']['name']}=={i['metadata']['version']}" for i in report.get("install", [])], ""
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"pip's report was not readable ({exc})"


def ensure_requirements(repo: Path, *, whatif: bool) -> RequirementsStep:
    """Install what ``requirements.txt`` asks for and the venv lacks."""
    requirements = repo / "requirements.txt"
    if not running_in_venv(repo):
        if whatif:
            return RequirementsStep("would-install", detail="everything in requirements.txt, into the new .venv")
        return RequirementsStep("failed", detail=f"not running from {repo / '.venv'} (start through scripts\\install.bat)")
    missing, problem = missing_packages(requirements)
    if missing is None:
        return RequirementsStep("failed", detail=problem)
    if not missing:
        return RequirementsStep("unchanged")
    if whatif:
        return RequirementsStep("would-install", tuple(missing))
    try:
        done = _pip(["install", "--quiet", "-r", str(requirements)], INSTALL_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return RequirementsStep("failed", tuple(missing), f"pip did not run ({exc})")
    if done.returncode != 0:
        return RequirementsStep("failed", tuple(missing), f"pip exit {done.returncode}: {done.stderr.strip()[-300:]}")
    return RequirementsStep("installed", tuple(missing))
