"""``today.js`` — Today's header line and its horizons agree (#393).

The page header names Today's exceptions (overdue, due today) off the very
counts the horizons are drawn from, so the header and the list can never say
two different numbers; with neither, it states the plain fact in the muted
tone. The horizons still hold every task exactly once.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "today.js"
NODE = shutil.which("node")

# Reads [items, today] on stdin, buckets them, and prints the counts with the
# header line those counts produce.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const [items, today] = JSON.parse(input);
const data = mod.bucketToday(items, today);
const rows = n => data[n].reduce((s, g) => s + g.items.length, 0);
process.stdout.write(JSON.stringify({
  counts: data.counts, line: mod.headLine(data.counts),
  rows: {due: rows('due'), week: rows('week'), later: rows('later'), nodate: rows('nodate')},
}));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")

TODAY = "2026-10-10"


def _today(items: list[dict]) -> dict:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps([items, TODAY]), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _task(i: int, due: str | None) -> dict:
    return {"id": i, "title": f"task {i}", "due": due, "priority": "medium", "root": None}


def test_header_names_overdue_and_due_today_from_the_drawn_counts() -> None:
    out = _today([_task(1, "2026-10-08"), _task(2, "2026-10-10"), _task(3, "2026-10-10"),
                  _task(4, "2026-10-12"), _task(5, "2027-01-01"), _task(6, None)])
    assert out["line"] == {"text": "1 overdue · 2 due today", "attention": True}
    # the header's two numbers are exactly the rows of the due horizon
    assert out["counts"]["overdue"] + out["counts"]["today"] == out["rows"]["due"] == 3
    assert out["rows"] == {"due": 3, "week": 1, "later": 1, "nodate": 1}


def test_header_names_only_the_exception_there_is() -> None:
    assert _today([_task(1, "2026-10-10")])["line"] == {"text": "1 due today", "attention": True}
    assert _today([_task(1, "2026-10-01")])["line"] == {"text": "1 overdue", "attention": True}


def test_nothing_due_is_a_plain_fact_not_an_exception() -> None:
    out = _today([_task(1, "2026-10-11"), _task(2, None)])
    assert out["line"] == {"text": "Nothing due today", "attention": False}
    assert out["rows"]["due"] == 0
