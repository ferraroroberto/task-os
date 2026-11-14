"""Set or clear one member's own login password (``auth.people.<id>.password_hash``).

The install owner's password is the app password every fleet app shares:
``python -m src.password set`` (the vendored ``src/password.py``). This script
is for the other members. The bearer token gates every non-loopback request; a
password is a memorable alternative to type at ``/login`` instead of pasting the
token. Only the PBKDF2 hash is stored (``config/config.json``, gitignored) —
never the password. Signing in with it hands the device the member's own
90-day token cookie, so rotating that token (``gen_token.py --person <id>
--force``) still signs those devices out.

The password is read without echo and asked for twice, never taken as an
argument, so it lands neither in the shell history nor in a terminal transcript.

Usage:
    .venv/Scripts/python.exe scripts/set_password.py --person p2
    .venv/Scripts/python.exe scripts/set_password.py --person p2 --clear
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._password_prompt import prompt_new_password  # noqa: E402
from src.config import CONFIG_PATH, load_config, save_auth  # noqa: E402
from src.password import hash_password  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None, read_secret: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(
        description="set / clear a member's task-os login password (the owner's: python -m src.password set)"
    )
    parser.add_argument("--clear", action="store_true", help="remove the password (token-only sign-in)")
    parser.add_argument("--person", metavar="ID", required=True, help="the member whose password this is")
    args = parser.parse_args(argv)

    config = load_config(CONFIG_PATH if CONFIG_PATH.exists() else None)
    field = f"auth.people.{args.person}.password_hash"
    problem = config.member_secret_problem(args.person)
    if problem:
        print(f"❌ {problem}", file=sys.stderr)
        return 1

    if args.clear:
        save_auth(password_hash="", person=args.person)
        print(f"🧹 cleared {field} in {CONFIG_PATH} — /login accepts the token only")
        print("   restart: tray.bat --restart")
        return 0
    if not config.auth.token_of(args.person):
        gen = f"scripts/gen_token.py --person {args.person}"
        print(f"❌ no token yet — the password only unlocks the token cookie; run {gen} first", file=sys.stderr)
        return 1
    password = prompt_new_password("New password", read_secret)
    if password is None:
        return 1

    save_auth(password_hash=hash_password(password), person=args.person)
    print(f"✅ password set ({len(password)} chars) — hash stored in {field} of {CONFIG_PATH}")
    print("   restart: tray.bat --restart, then type it at /login on the phone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
