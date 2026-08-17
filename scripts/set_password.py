"""Set or clear the optional login password (``auth.password_hash``).

The bearer token gates every non-loopback request; a password is a memorable
alternative to type at ``/login`` instead of pasting the token. Only the
PBKDF2 hash is stored (``config/config.json``, gitignored) — never the
password. Signing in with it hands the device the same 90-day token cookie,
so rotating the token (``gen_token.py --force``) still signs everyone out.

Usage:
    .venv/Scripts/python.exe scripts/set_password.py <password>   # set / change
    .venv/Scripts/python.exe scripts/set_password.py --clear      # token only again
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
    args = parser.parse_args(argv)

    if args.clear:
        save_auth(password_hash="")
        print(f"🧹 cleared auth.password_hash in {CONFIG_PATH} — /login accepts the token only")
        print("   restart: tray.bat --restart")
        return 0
    if not args.password:
        parser.error("give the password as the first argument, or --clear")
    if len(args.password) < MIN_LENGTH:
        print(f"❌ password too short — at least {MIN_LENGTH} characters", file=sys.stderr)
        return 1
    if not load_config(CONFIG_PATH if CONFIG_PATH.exists() else None).auth.token:
        print("❌ no auth.token yet — the password only unlocks the token cookie; run scripts/gen_token.py first", file=sys.stderr)
        return 1

    save_auth(password_hash=hash_password(args.password))
    print(f"✅ password set ({len(args.password)} chars) — hash stored in {CONFIG_PATH}")
    print("   restart: tray.bat --restart, then type it at /login on the phone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
