"""``board.js`` — the Board's week planner lanes and its header line (#396).

Week mode puts every open task in exactly one lane by its due date: Today
(overdue included) · Tomorrow · This week · This weekend · Next week · Later ·
No date. A week runs Monday to Sunday, and on a Sunday "this week" is the one
tomorrow starts. A lane whose days are all taken by an earlier one is left
out (This week from Thursday, This weekend on a Saturday), and a row dropped
on a lane is re-dated to that lane's own first day, so it always lands in the
lane it was dropped on. The page header names the Inbox arrivals in the accent
and what is overdue or due today in the attention tone, at most two parts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "board.js"
NODE = shutil.which("node")

# Reads [[fn, arg, arg2], …] on stdin and prints each result as one JSON array.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, a, b]) => {
  if (fn === 'laneOf') return mod.laneOf(a, mod.weekLanes(b));
  return mod[fn](a, b);
});
process.stdout.write(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")

MONDAY = date(2026, 10, 12)
WEEK = [MONDAY + timedelta(days=i) for i in range(7)]   # Monday … Sunday


def _call_js(calls: list[list]) -> list:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps(calls), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _lanes(today: date) -> list[dict]:
    return _call_js([["weekLanes", today.isoformat()]])[0]


def test_a_monday_has_all_seven_lanes_with_their_days() -> None:
    lanes = _lanes(MONDAY)
    assert [(lane["key"], lane["from"], lane["to"]) for lane in lanes] == [
        ("today", None, "2026-10-12"),
        ("tomorrow", "2026-10-13", "2026-10-13"),
        ("week", "2026-10-14", "2026-10-16"),        # Wednesday … Friday
        ("weekend", "2026-10-17", "2026-10-18"),
        ("next", "2026-10-19", "2026-10-25"),
        ("later", "2026-10-26", None),
        ("nodate", None, None),
    ]
    assert [lane["label"] for lane in lanes] == [
        "Today", "Tomorrow", "This week", "This weekend", "Next week", "Later", "No date"]


def test_a_lane_whose_days_are_taken_is_left_out() -> None:
    keys = {d.strftime("%a"): [lane["key"] for lane in _lanes(d)] for d in WEEK}
    assert "week" in keys["Wed"] and "week" not in keys["Thu"]          # Friday is tomorrow
    assert keys["Fri"].count("weekend") == 1                             # Sunday alone
    assert "weekend" not in keys["Sat"] and "week" not in keys["Sat"]   # Sunday is tomorrow
    assert keys["Sun"] == ["today", "tomorrow", "week", "weekend", "next", "later", "nodate"]


@pytest.mark.parametrize("today", WEEK, ids=lambda d: d.strftime("%a"))
def test_every_date_has_exactly_one_lane_and_a_drop_lands_in_its_own(today: date) -> None:
    lanes = _lanes(today)
    days = [(today + timedelta(days=n)).isoformat() for n in range(-10, 40)]
    got = _call_js([["laneOf", d, today.isoformat()] for d in days])
    for d, key in zip(days, got, strict=True):
        hits = [lane["key"] for lane in lanes if lane["key"] != "nodate"
                and (lane["from"] is None or d >= lane["from"]) and (lane["to"] is None or d <= lane["to"])]
        assert hits == [key], (d, hits, key)
    assert got[:11] == ["today"] * 11                                     # overdue and today
    drops = _call_js([["laneOf", lane["drop"], today.isoformat()] for lane in lanes])
    assert drops == [lane["key"] for lane in lanes]
    assert lanes[-1]["drop"] is None                                      # No date clears the date


def test_the_header_names_inbox_arrivals_then_what_is_due() -> None:
    assert _call_js([
        ["boardHeadParts", {"inbox": 2, "overdue": 1, "today": 3}],
        ["boardHeadParts", {"inbox": 0, "overdue": 0, "today": 3}],
        ["boardHeadParts", {"inbox": 0, "overdue": 0, "today": 0}],
    ]) == [
        [{"text": "2 in Inbox", "tone": "accent"}, {"text": "1 overdue", "tone": "attention"}],
        [{"text": "3 due today", "tone": "attention"}],
        [{"text": "Nothing due today", "tone": "muted"}],
    ]
