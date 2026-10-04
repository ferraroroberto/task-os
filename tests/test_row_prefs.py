"""``rowprefs.js`` — Settings → Row actions: what the swipes run and what the ⋯ menu lists (#311).

The choice lives in the browser's storage, so whatever comes back from it —
an old shape, a hand edit, an action id a later build dropped — has to land
on a valid choice, and no choice may cost an action its tap path: an action a
swipe runs is always in the menu (WCAG 2.5.1). Loaded bare under node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "rowprefs.js"
NODE = shutil.which("node")

_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, args]) => fn === 'DEFAULTS' ? mod.DEFAULTS : mod[fn](...args));
process.stdout.write(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")

DEFAULT_MENU = [
    "complete", "reopen", "change-date", "snooze",
    "status-inbox", "status-todo", "status-standby", "status-cancelled", "priority",
]


def _call_js(calls: list[tuple[str, list]]) -> list:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps(calls), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_defaults_are_the_plans_choices() -> None:
    (d,) = _call_js([("DEFAULTS", [])])
    assert d == {"right": "complete", "left": "change-date", "menu": DEFAULT_MENU}


def test_anything_stored_lands_on_a_valid_choice() -> None:
    got = _call_js([
        ("normalizeRowPrefs", [None]),
        ("normalizeRowPrefs", ["garbage"]),
        ("normalizeRowPrefs", [{"right": "launch-rockets", "left": "", "menu": ["snooze", "nope", "snooze", 7, "complete"]}]),
        ("normalizeRowPrefs", [{"right": "priority"}]),
    ])
    assert got[0] == {"right": "complete", "left": "change-date", "menu": DEFAULT_MENU}
    assert got[1] == got[0]
    # an unknown side falls back, '' (nothing) is kept, the list drops unknowns and repeats
    assert got[2] == {"right": "complete", "left": "", "menu": ["snooze", "complete"]}
    assert got[3] == {"right": "priority", "left": "change-date", "menu": DEFAULT_MENU}


def test_a_swipe_action_always_stays_in_the_menu() -> None:
    got = _call_js([
        ("menuOrder", [{"right": "complete", "left": "snooze", "menu": ["priority"]}]),
        ("menuOrder", [{"right": "", "left": "", "menu": []}]),
        ("menuOrder", [{"right": "priority", "left": "priority", "menu": ["priority", "complete"]}]),
    ])
    assert got == [["priority", "complete", "snooze"], [], ["priority", "complete"]]


def test_default_is_only_the_untouched_choice() -> None:
    got = _call_js([
        ("isDefault", [{"right": "complete", "left": "change-date", "menu": DEFAULT_MENU}]),
        ("isDefault", [{"right": "complete", "left": "", "menu": DEFAULT_MENU}]),
        ("isDefault", [{"right": "complete", "left": "change-date", "menu": DEFAULT_MENU[::-1]}]),
    ])
    assert got == [True, False, False]
