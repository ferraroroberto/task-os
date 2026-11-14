"""The Board orders a lane by due day, then project, then title (``rows.js``).

Within one lane: the earliest due day first; inside one day the rows with no
project, then the rest grouped by project name A–Z; inside one project the title
A–Z. A sort the owner picked in the filter sheet (priority, modified, …) is
theirs and is left alone. Loaded bare under node, on synthetic tasks only.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.node_js import call_js, requires_node

pytestmark = requires_node

MODULE = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "rows.js"

# Reads [[fn, [args]], …] on stdin; `board_titles` answers the titles of the
# sorted copy so a case reads as the order it expects.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([items, sort]) =>
  mod.sortBoardItems(items, sort).map((t) => t.title));
process.stdout.write(JSON.stringify(out));
"""

_IDS_RUNNER = _RUNNER.replace("t.title", "t.id")


def _task(tid: int, title: str, due: str | None, project: str | None = None, **extra) -> dict:
    return {
        "id": tid, "title": title, "due": due, "priority": "none",
        "root": {"id": 1000 + tid, "title": project} if project else None, **extra,
    }


def _order(items: list[dict], sort: str = "due") -> list[str]:
    return call_js(MODULE, _RUNNER, [[items, sort]])[0]


def test_the_earlier_day_wins_over_any_project() -> None:
    items = [
        _task(1, "Later task", "2026-11-18", "Alpha"),
        _task(2, "Sooner task", "2026-11-17", "Zulu"),
    ]
    assert _order(items) == ["Sooner task", "Later task"]


def test_within_a_day_no_project_comes_first_then_project_a_to_z() -> None:
    day = "2026-11-17"
    items = [
        _task(1, "In Zulu", day, "Zulu"),
        _task(2, "In Alpha", day, "Alpha"),
        _task(3, "Loose", day),
        _task(4, "In Mike", day, "Mike"),
    ]
    assert _order(items) == ["Loose", "In Alpha", "In Mike", "In Zulu"]


def test_within_a_day_and_project_the_title_runs_a_to_z() -> None:
    day = "2026-11-17"
    items = [
        _task(1, "Charlie", day, "Alpha"),
        _task(2, "alpha", day, "Alpha"),
        _task(3, "Bravo", day, "Alpha"),
        _task(4, "Zed", day),
        _task(5, "Able", day),
    ]
    assert _order(items) == ["Able", "Zed", "alpha", "Bravo", "Charlie"]


def test_a_project_does_not_cluster_across_days() -> None:
    items = [
        _task(1, "Alpha day 3", "2026-11-20", "Alpha"),
        _task(2, "Zulu day 2", "2026-11-19", "Zulu"),
        _task(3, "Alpha day 2", "2026-11-19", "Alpha"),
        _task(4, "Loose day 1", "2026-11-18"),
    ]
    assert _order(items) == ["Loose day 1", "Alpha day 2", "Zulu day 2", "Alpha day 3"]


def test_undated_rows_close_the_list_in_the_same_project_then_title_order() -> None:
    items = [
        _task(1, "Undated in Zulu", None, "Zulu"),
        _task(2, "Dated", "2026-11-17", "Zulu"),
        _task(3, "Undated loose", None),
        _task(4, "Undated in Alpha", None, "Alpha"),
    ]
    assert _order(items) == ["Dated", "Undated loose", "Undated in Alpha", "Undated in Zulu"]


def test_numbers_in_a_title_sort_as_numbers() -> None:
    day = "2026-11-17"
    items = [_task(1, "Step 10", day), _task(2, "Step 2", day)]
    assert _order(items) == ["Step 2", "Step 10"]


def test_equal_rows_keep_a_stable_order_by_id() -> None:
    day = "2026-11-17"
    items = [_task(7, "Same", day, "Alpha"), _task(3, "Same", day, "Alpha")]
    out = call_js(MODULE, _IDS_RUNNER, [[items, "due"]])[0]
    assert out == [3, 7]


def test_an_explicit_sort_other_than_due_is_left_alone() -> None:
    day = "2026-11-17"
    items = [
        _task(1, "Low", day, "Alpha", priority="low"),
        _task(2, "High", day, "Zulu", priority="high"),
    ]
    assert _order(items, "priority") == ["High", "Low"]
