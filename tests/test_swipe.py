"""``swipe.js`` — when a touch on a task row becomes a swipe, and whether its release commits (#311).

The gesture's rules are the part a desktop browser cannot walk honestly —
slop, direction lock, threshold, flick, the iOS edge zone — so the pure
classifier at the top of the module is held to them here, under node. The DOM
binding below it is walked by story 07 with synthetic touch pointers; the real
feel is the owner's iPhone checklist.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "swipe.js"
NODE = shutil.which("node")

# Reads [[fn, args], …] on stdin, prints each result as one JSON array.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, args]) => mod[fn](...args));
process.stdout.write(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")


def _call_js(calls: list[tuple[str, list]]) -> list:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps(calls), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_a_touch_in_the_edge_zone_is_never_tracked() -> None:
    """The outer 20px of either side belong to iOS's edge-back / edge-forward."""
    got = _call_js([("startAllowed", [x, 390]) for x in (0, 19, 20, 200, 370, 371, 390)])
    assert got == [False, False, True, True, True, False, False]


def test_nothing_happens_inside_the_slop_then_the_direction_locks() -> None:
    got = _call_js([
        ("lockDirection", [6, 6]),       # under 10px of travel
        ("lockDirection", [9, 0]),
        ("lockDirection", [12, 2]),      # clearly sideways
        ("lockDirection", [-30, 10]),
        ("lockDirection", [15, 10]),     # 1.5 ratio exactly: not more, so the scroll's
        ("lockDirection", [3, 40]),      # a scroll
    ])
    assert got == ["pending", "pending", "x", "x", "y", "y"]


def test_the_commit_distance_is_96px_or_35_percent_of_the_row() -> None:
    got = _call_js([("commitDistance", [w]) for w in (200, 274, 390, 1024)])
    assert got == [96, 96, pytest.approx(136.5), pytest.approx(358.4)]


def test_a_release_commits_past_the_distance_or_on_a_flick() -> None:
    got = _call_js([
        ("releaseSide", [140, 390, 0]),       # past 136.5 → right
        ("releaseSide", [-140, 390, 0]),      # → left
        ("releaseSide", [120, 390, 0.2]),     # short and slow → back
        ("releaseSide", [60, 390, 0.8]),      # a flick that travelled 48+ → right
        ("releaseSide", [40, 390, 0.9]),      # a flick under 48px → back
        ("releaseSide", [60, 390, -0.8]),     # flicked the other way → back
        ("releaseSide", [0, 390, 0]),
    ])
    assert got == ["right", "left", None, "right", None, None, None]


def test_armed_is_the_distance_alone() -> None:
    """The reveal arms on distance; a flick commits without ever having armed."""
    got = _call_js([("isArmed", [135, 390]), ("isArmed", [137, 390]), ("isArmed", [-137, 390])])
    assert got == [False, True, True]
