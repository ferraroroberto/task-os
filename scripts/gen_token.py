"""Generate / rotate / clear the webapp's bearer token (``auth.token``).

Loopback (this PC) never needs it. Any other client — the phone over the
tailnet, a script on another machine, an LLM — must present it: as
``Authorization: Bearer <token>``, or by signing in once at ``/login`` (the
token itself, or the password ``scripts/set_password.py`` sets), which stores
it as a 90-day cookie. With no token configured the app refuses every
non-loopback request — the gate is closed, not open.

Writes ``config/config.json`` (gitignored; created from the sample when
missing). The running app reads config at startup only: ``tray.bat --restart``
afterwards. Rotating (``--force``) signs every device out at once.

Usage:
    .venv/Scripts/python.exe scripts/gen_token.py            # generate iff none set
    .venv/Scripts/python.exe scripts/gen_token.py --force    # rotate
    .venv/Scripts/python.exe scripts/gen_token.py --clear    # loopback-only again
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth import new_token  # noqa: E402
from src.config import CONFIG_PATH, load_config, save_auth  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="generate / rotate / clear the task-os bearer token")
    parser.add_argument("--force", action="store_true", help="rotate even if a token is already set")
    parser.add_argument("--clear", action="store_true", help="remove the token (only loopback can use the app)")
    args = parser.parse_args(argv)

    if args.clear:
        save_auth(token="")
        print(f"🧹 cleared auth.token in {CONFIG_PATH} — only this PC (loopback) can use the app now")
        print("   restart: tray.bat --restart")
        return 0

    current = load_config(CONFIG_PATH if CONFIG_PATH.exists() else None).auth.token
    if current and not args.force:
        print(f"ℹ️ auth.token is already set in {CONFIG_PATH} — re-run with --force to rotate, --clear to remove")
        return 0

    token = new_token()
    save_auth(token=token)
    print(f"✅ wrote a new auth.token to {CONFIG_PATH}")
    print()
    print(f"   {token}")
    print()
    print("Next: tray.bat --restart, then on the phone open https://<your-host>.ts.net:8448,")
    print("paste the token at /login (or set a password: scripts/set_password.py <password>).")
    if args.force:
        print("Rotated: every device is signed out until it signs in again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
