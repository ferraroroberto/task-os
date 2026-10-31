"""The one way the password setters ask for a new password.

``set_password.py`` (the owner's and each member's sign-in) and
``set_team_password.py`` (the shared team sign-in) read the secret here, with
no echo and never as an argument, so it lands neither in the shell history nor
in a terminal transcript. One length rule, one confirm-twice flow.
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable

MIN_LENGTH = 8


def prompt_new_password(
    label: str, read_secret: Callable[[str], str] = getpass.getpass,
) -> str | None:
    """Ask twice for ``label``'s new password; ``None`` (with the reason on stderr) when it is refused."""
    password = read_secret(f"{label}: ")
    if len(password) < MIN_LENGTH:
        print(f"❌ password too short — at least {MIN_LENGTH} characters", file=sys.stderr)
        return None
    if read_secret("Again: ") != password:
        print("❌ the two entries differ — nothing changed", file=sys.stderr)
        return None
    return password
