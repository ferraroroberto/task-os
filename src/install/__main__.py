"""``python -m src.install``: the three commands ``.fleet.toml [install]`` runs for ``setup.bat``.

    apply [-WhatIf]          add the keys an existing config lacks that change nothing (after a backup), and
                             register the folder opener when this user has none. This is the install's
                             dependency step; a missing config is created by setup.bat itself.
    startup status|enable    the sign-in start: ``status`` exits 0 when present, 1 when not; ``enable`` adds it.
    check <name>             one personal checklist item: exit 0 ok, 1 missing, 2 unknown, detail on stdout.

Each step prints one ``[status] item`` line. Exit 1 when a step failed or a config could not be read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.install.checklist import CHECKS, EXIT_CODES
from src.install.config_merge import ensure_configs
from src.install.machine import ensure_opener, ensure_startup, startup_dir, startup_entry

REPO_ROOT = Path(__file__).resolve().parents[2]
_BAD = {"failed", "unparseable"}


def _line(status: str, item: str, detail: str = "") -> None:
    print(f"  [{status}] {item}" + (f" - {detail}" if detail else ""))


def apply(root: Path, *, whatif: bool) -> int:
    """The config top-up and the opener for the checkout at ``root``; returns the exit code."""
    statuses: list[str] = []
    for step in ensure_configs(root / "config", whatif=whatif, only_existing=True):
        statuses.append(step.status)
        rel = step.path.relative_to(root).as_posix()
        _line(step.status, rel, step.detail)
        for key in step.added:
            print(f"      {'would add' if whatif else 'added'}: {key}")
        if step.backup is not None:
            print(f"      backup: {step.backup.relative_to(root).as_posix()}")
        for key in step.held_back:
            print(f"      held back (would change what this PC runs; add by hand if wanted): {key}")
    opener = ensure_opener(whatif=whatif)
    statuses.append(opener.status)
    _line(opener.status, opener.item, opener.detail)
    return 1 if _BAD.intersection(statuses) else 0


def startup(root: Path, action: str, *, folder: Path | None = None) -> int:
    """``status``: 0 when a sign-in start exists, 1 when not. ``enable``: add it when absent."""
    if action == "status":
        return 0 if startup_entry(root, folder or startup_dir()) else 1
    step = ensure_startup(root, whatif=False, enable=True, folder=folder)
    _line(step.status, step.item, step.detail)
    return 1 if step.status in _BAD else 0


def check(root: Path, name: str) -> int:
    """One personal checklist item: its detail on stdout, its state as the exit code."""
    result = CHECKS[name](root)
    _line(result.state, result.item, result.detail)
    return EXIT_CODES[result.state]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(prog="python -m src.install", description="the app's part of setup.bat")
    commands = parser.add_subparsers(dest="command", required=True)
    apply_cmd = commands.add_parser("apply", help="config top-up and folder opener")
    apply_cmd.add_argument("-WhatIf", "--whatif", dest="whatif", action="store_true",
                           help="list every change and make none")
    startup_cmd = commands.add_parser("startup", help="the sign-in start")
    startup_cmd.add_argument("action", choices=("status", "enable"))
    check_cmd = commands.add_parser("check", help="one personal checklist item")
    check_cmd.add_argument("name", choices=sorted(CHECKS))
    args = parser.parse_args(argv)
    if args.command == "apply":
        return apply(REPO_ROOT, whatif=args.whatif)
    if args.command == "startup":
        return startup(REPO_ROOT, args.action)
    return check(REPO_ROOT, args.name)


if __name__ == "__main__":
    sys.exit(main())
