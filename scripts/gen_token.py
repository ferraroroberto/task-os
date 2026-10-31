"""Generate / rotate / clear the webapp's bearer token (``auth.token``) — or,
with ``--person <id>``, one member's own token (``auth.people.<id>.token``, #474).

Loopback (this PC) never needs it. Any other client — the phone over the
tailnet, a script on another machine, an LLM — must present it: as
``Authorization: Bearer <token>``, or by signing in once at ``/login`` (the
token itself, or the password ``scripts/set_password.py`` sets), which stores
it as a 90-day cookie. With no token configured the app refuses every
non-loopback request — the gate is closed, not open.

``auth.token`` is the install owner's (the first member). Another member gets
their own with ``--person``: their phone signs in with it, and the app knows
it is them. Rotating or clearing one member's token signs only that member out.

Writes ``config/config.json`` (gitignored; created from the sample when
missing). The running app reads config at startup only: ``tray.bat --restart``
afterwards. Only a newly generated token is ever printed — never one already set.

Usage:
    .venv/Scripts/python.exe scripts/gen_token.py            # generate iff none set
    .venv/Scripts/python.exe scripts/gen_token.py --force    # rotate
    .venv/Scripts/python.exe scripts/gen_token.py --clear    # loopback-only again
    .venv/Scripts/python.exe scripts/gen_token.py --person p2          # p2's own token
    .venv/Scripts/python.exe scripts/gen_token.py --person p2 --force  # rotate p2's
    .venv/Scripts/python.exe scripts/gen_token.py --person p2 --clear  # sign p2 out
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
    parser.add_argument("--person", metavar="ID", help="a member's own token instead of the owner's")
    args = parser.parse_args(argv)

    config = load_config(CONFIG_PATH if CONFIG_PATH.exists() else None)
    field = f"auth.people.{args.person}.token" if args.person else "auth.token"
    if args.person:
        problem = config.member_secret_problem(args.person)
        if problem:
            print(f"❌ {problem}", file=sys.stderr)
            return 1

    if args.clear:
        save_auth(token="", person=args.person)
        if args.person:
            print(f"🧹 cleared {field} in {CONFIG_PATH} — {args.person} is signed out everywhere")
        else:
            print(f"🧹 cleared {field} in {CONFIG_PATH} — only this PC (loopback) can use the app now")
        print("   restart: tray.bat --restart")
        return 0

    current = config.auth.token_of(args.person) if args.person else config.auth.token
    if current and not args.force:
        print(f"ℹ️ {field} is already set in {CONFIG_PATH} — re-run with --force to rotate, --clear to remove")
        return 0

    token = new_token()
    save_auth(token=token, person=args.person)
    print(f"✅ wrote a new {field} to {CONFIG_PATH}")
    print()
    print(f"   {token}")
    print()
    who = f"{args.person}'s phone" if args.person else "the phone"
    print(f"Next: tray.bat --restart, then on {who} open https://<your-host>.ts.net:8448,")
    print("paste the token at /login (or set a password: scripts/set_password.py"
          + (f" --person {args.person}" if args.person else "") + ", which prompts for it).")
    if args.force:
        print("Rotated: " + (f"{args.person}'s devices are" if args.person else "every device signed in with it is")
              + " signed out until they sign in again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
