"""Set or clear the optional login password (``auth.password_hash``) — or, with
``--person <id>``, one member's own (``auth.people.<id>.password_hash``, #474).

The bearer token gates every non-loopback request; a password is a memorable
alternative to type at ``/login`` instead of pasting the token. Only the
PBKDF2 hash is stored (``config/config.json``, gitignored) — never the
password. Signing in with it hands the device the same 90-day token cookie
(the member's own token, with ``--person``), so rotating that token
(``gen_token.py [--person <id>] --force``) still signs those devices out.

Usage:
    .venv/Scripts/python.exe scripts/set_password.py <password>   # set / change
    .venv/Scripts/python.exe scripts/set_password.py --clear      # token only again
    .venv/Scripts/python.exe scripts/set_password.py --person p2 <password>
    .venv/Scripts/python.exe scripts/set_password.py --person p2 --clear
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth import hash_password  # noqa: E402
from src.config import CONFIG_PATH, load_config, save_auth  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIN_LENGTH = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="set / clear the task-os login password")
    parser.add_argument("password", nargs="?", help="the password to set")
    parser.add_argument("--clear", action="store_true", help="remove the password (token-only sign-in)")
    parser.add_argument("--person", metavar="ID", help="a member's own password instead of the owner's")
    args = parser.parse_args(argv)

    config = load_config(CONFIG_PATH if CONFIG_PATH.exists() else None)
    field = f"auth.people.{args.person}.password_hash" if args.person else "auth.password_hash"
    if args.person:
        problem = config.member_secret_problem(args.person)
        if problem:
            print(f"❌ {problem}", file=sys.stderr)
            return 1

    if args.clear:
        save_auth(password_hash="", person=args.person)
        print(f"🧹 cleared {field} in {CONFIG_PATH} — /login accepts the token only")
        print("   restart: tray.bat --restart")
        return 0
    if not args.password:
        parser.error("give the password as the first argument, or --clear")
    if len(args.password) < MIN_LENGTH:
        print(f"❌ password too short — at least {MIN_LENGTH} characters", file=sys.stderr)
        return 1
    token = config.auth.token_of(args.person) if args.person else config.auth.token
    if not token:
        gen = "scripts/gen_token.py" + (f" --person {args.person}" if args.person else "")
        print(f"❌ no token yet — the password only unlocks the token cookie; run {gen} first", file=sys.stderr)
        return 1

    save_auth(password_hash=hash_password(args.password), person=args.person)
    print(f"✅ password set ({len(args.password)} chars) — hash stored in {field} of {CONFIG_PATH}")
    print("   restart: tray.bat --restart, then type it at /login on the phone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
