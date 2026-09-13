"""Set or clear the shared team password (``team.password_hash``, Step 12).

Team mode (``team.enabled`` in ``config/config.json``) lets a small team share
one install: a teammate types this password at ``/login``, picks their name
from ``team.people``, and what they write carries that name. Only the PBKDF2
hash is stored — never the password — and it is read here without echo, so it
never lands in the shell history or a terminal transcript either.

Signing in with it hands the browser a team cookie derived from the token and
this hash: changing the password (or rotating the token with
``gen_token.py --force``) signs every teammate out.

Usage:
    .venv/Scripts/python.exe scripts/set_team_password.py           # set / change (prompts twice)
    .venv/Scripts/python.exe scripts/set_team_password.py --clear   # no team sign-in again
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth import hash_password  # noqa: E402
from src.config import CONFIG_PATH, load_config, save_team_password_hash  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIN_LENGTH = 8


def main(argv: list[str] | None = None, read_secret: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description="set / clear the task-os team password")
    parser.add_argument("--clear", action="store_true", help="remove the team password (teammates cannot sign in)")
    args = parser.parse_args(argv)

    if args.clear:
        save_team_password_hash("")
        print(f"🧹 cleared team.password_hash in {CONFIG_PATH} — the team password is no longer accepted")
        print("   restart: tray.bat --restart")
        return 0

    config = load_config(CONFIG_PATH if CONFIG_PATH.exists() else None)
    if not config.auth.token:
        print("❌ no auth.token yet — team sign-in is derived from it; run scripts/gen_token.py first", file=sys.stderr)
        return 1
    password = read_secret("Team password: ")
    if len(password) < MIN_LENGTH:
        print(f"❌ password too short — at least {MIN_LENGTH} characters", file=sys.stderr)
        return 1
    if read_secret("Again: ") != password:
        print("❌ the two entries differ — nothing changed", file=sys.stderr)
        return 1

    save_team_password_hash(hash_password(password))
    print(f"✅ team password set ({len(password)} chars) — hash stored in {CONFIG_PATH}")
    if not config.team.enabled:
        print("⚠️ team.enabled is false — set it to true (and list team.people) before teammates can use it")
    elif not config.team.people:
        print("⚠️ team.people is empty — a teammate would have no name to pick")
    print("   restart: tray.bat --restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
