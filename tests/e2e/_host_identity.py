"""Keep the machine that runs the suite out of the gallery it writes (#351).

task-os is a public repo and ``docs/screenshots/`` is committed. Every e2e
instance lives under ``E2E_WORK_ROOT`` in the system temp dir (#134), which on
Windows sits inside the user profile, so a story that puts one of its own
paths on screen (a folder placeholder, a resolved folder ref) photographs the
account name of whoever ran it. ``shot()`` asks this module what the page
renders before it captures anything, and refuses a page that shows the home
directory or the account name.

What counts as "the page renders": the body's visible text plus the value of
every text field, which ``innerText`` leaves out. Tooltips (``title``) are not
painted, so they are not checked.

The needles are the host's own facts, read here, never written down: the home
directory in both slash forms, the account name as a profile-path segment, and
the bare account name as a whole word when it is long enough not to collide
with ordinary words (a three-letter name would match the fixture's own
people). Matching ignores case, as Windows paths do.

Stdlib only, so the unit leg can prove the matcher without a browser.
"""

from __future__ import annotations

import getpass
import re
from collections.abc import Iterable
from pathlib import Path

#: Shorter account names are not matched as a bare word (see the module doc).
MIN_BARE_NAME = 4


def _account_name() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no name to establish means no name to leak
        return ""


Needle = tuple[str, re.Pattern[str]]


def host_needles(home: str | None = None, user: str | None = None) -> list[Needle]:
    """``(kind, pattern)`` for everything that would identify this host on screen."""
    home = str(Path.home()) if home is None else home
    user = _account_name() if user is None else user
    needles: list[Needle] = []
    if home:
        fwd = home.replace("\\", "/").rstrip("/")
        for form in sorted({fwd, fwd.replace("/", "\\")}):
            needles.append(("home directory", re.compile(re.escape(form), re.IGNORECASE)))
    if user:
        name = re.escape(user)
        needles.append(("home directory", re.compile(rf"(?:users|home)[\\/]+{name}(?!\w)", re.IGNORECASE)))
        if len(user) >= MIN_BARE_NAME:
            needles.append(("account name", re.compile(rf"(?<!\w){name}(?!\w)", re.IGNORECASE)))
    return needles


def leaks(texts: Iterable[str], needles: list[Needle] | None = None) -> list[str]:
    """The kinds of host fact found in *texts*, never the matched text itself.

    The caller's failure message must not print what it found: that would put
    the account name in a test log someone pastes into an issue.
    """
    needles = host_needles() if needles is None else needles
    blob = "\n".join(t for t in texts if t)
    return sorted({kind for kind, pattern in needles if pattern.search(blob)})


#: The page's painted text plus every text field's value.
RENDERED_TEXT_JS = """
() => [document.body ? document.body.innerText : '',
       ...Array.from(document.querySelectorAll('input, textarea'))
         .filter(el => el.type !== 'hidden' && el.type !== 'password')
         .map(el => el.value || '')]
"""


def describe(found: list[str]) -> str:
    """A failure message that names the kind of leak without repeating it."""
    return (f"the page renders this machine's {' and '.join(found)}; "
            "point the story's fixture at a synthetic path before capturing it (#351)")
