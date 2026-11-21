"""``python -m src.install [-WhatIf] [--startup]``: install.bat's second half.

install.bat creates the ``.venv`` (when missing) and then runs this module from
it. Each step prints one ``[status] item`` line, and the run ends with the
checklist. Exit 1 when a step failed or a config could not be read, else 0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.install.checklist import build_checklist
from src.install.config_merge import ensure_configs
from src.install.machine import ensure_opener, ensure_startup
from src.install.requirements import ensure_requirements

REPO_ROOT = Path(__file__).resolve().parents[2]
_BAD = {"failed", "unparseable"}


def _line(status: str, item: str, detail: str = "") -> None:
    print(f"  [{status}] {item}" + (f" - {detail}" if detail else ""))


def run(root: Path, *, whatif: bool, startup: bool, startup_folder: Path | None = None,
        probe: bool = True) -> int:
    """Every step for the checkout at ``root``; returns the exit code."""
    print("task-os install" + (" (-WhatIf: nothing is changed)" if whatif else "") + f" in {root}")
    statuses: list[str] = []

    req = ensure_requirements(root, whatif=whatif)
    statuses.append(req.status)
    _line(req.status, "requirements.txt", req.detail or ", ".join(req.packages))

    for step in ensure_configs(root / "config", whatif=whatif):
        statuses.append(step.status)
        rel = step.path.relative_to(root).as_posix()
        _line(step.status, rel, step.detail)
        for key in step.added:
            print(f"      {'would add' if whatif else 'added'}: {key}")
        if step.backup is not None:
            print(f"      backup: {step.backup.relative_to(root).as_posix()}")
        for key in step.held_back:
            print(f"      held back (would change what this PC runs; add by hand if wanted): {key}")

    for machine in (ensure_opener(whatif=whatif),
                    ensure_startup(root, whatif=whatif, enable=startup, folder=startup_folder)):
        statuses.append(machine.status)
        _line(machine.status, machine.item, machine.detail)

    print("\nChecklist:")
    for check in build_checklist(root, startup_folder=startup_folder, probe=probe):
        _line(check.state, check.item, check.detail)
    if whatif:
        print("\n-WhatIf: nothing was changed. Run install.bat without it to apply the steps above.")
    return 1 if _BAD.intersection(statuses) else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(prog="install.bat", description="install or update task-os on this PC")
    parser.add_argument("-WhatIf", "--whatif", dest="whatif", action="store_true",
                        help="list every change and make none")
    parser.add_argument("--startup", action="store_true",
                        help="also start the tray at sign-in (a task-os.bat in the Startup folder)")
    args = parser.parse_args(argv)
    return run(REPO_ROOT, whatif=args.whatif, startup=args.startup)


if __name__ == "__main__":
    sys.exit(main())
