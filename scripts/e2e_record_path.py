"""Where the gate writes the e2e timing record (`.fleet.toml [e2e] junit_xml`).

``data/`` is gitignored, so a record written inside a linked worktree is removed
with that worktree and ``/e2e-audit``, which reads the primary checkout, finds
nothing. The record therefore goes to the primary checkout from every checkout.
``TASKOS_E2E_JUNIT`` names another file, for a run that must write nothing
outside its own tree.

Prints ``E2E_JUNIT=<absolute path>`` for ``verify-before-ship.ps1``, plus
``E2E_JUNIT_NOTE=`` when the primary checkout could not be established and the
record stays in this one.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.no_window import NO_WINDOW  # noqa: E402

OVERRIDE_ENV = "TASKOS_E2E_JUNIT"
# rev-parse reads two small files; one that takes this long is wedged.
GIT_TIMEOUT_S = 60


def primary_root(checkout: Path) -> Path | None:
    """The primary checkout of the repository holding *checkout*, or None if unknown."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=checkout, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    common = Path(done.stdout.strip())
    # Only a `<checkout>/.git` common dir says where the primary is; a bare or
    # separated git dir does not.
    if done.returncode != 0 or common.name != ".git":
        return None
    return common.parent


def record_path(checkout: Path, override: str | None = None) -> tuple[Path, str]:
    """``(file, note)``; the note is empty unless the record fell back to *checkout*."""
    if override:
        return (checkout / override).resolve(), ""
    config = tomllib.loads((checkout / ".fleet.toml").read_text(encoding="utf-8"))
    relative = config["e2e"]["junit_xml"]
    primary = primary_root(checkout)
    if primary is None:
        return checkout / relative, "primary checkout not established; the record stays in this checkout"
    return primary / relative, ""


def main() -> int:
    path, note = record_path(REPO_ROOT, os.environ.get(OVERRIDE_ENV))
    print(f"E2E_JUNIT={path}")
    if note:
        print(f"E2E_JUNIT_NOTE={note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
