"""``filters.js`` — the Mine · Issues · All scope (#391, decision 1 of #390).

The scope rides the shared filter state as one URL key, so it survives a
reload, but it is the segmented switch's, not the filter sheet's: it is never
written for the default Mine, never counts as a filter (the sheet's
Clear stays hidden for it), and an unknown value reads back as Mine. A task is
an issue when it carries an ``issue_ref`` — the coding task the forge sync made.
The strip's filter button (#395) counts the settings the sheet's Clear would reset.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "filters.js"
NODE = shutil.which("node")

# Reads [[fn, arg, arg2], …] on stdin and prints each result as one JSON array.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, a, b]) => {
  if (fn === 'roundTrip') return mod.filtersToSearch(mod.filtersFromSearch(a));
  if (fn === 'scopeOf') return mod.filtersFromSearch(a).scope;
  if (fn === 'activeFilterCount') return mod.activeFilterCount(mod.filtersFromSearch(a), b);
  return mod[fn](a, b);
});
process.stdout.write(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH — the JS side cannot be loaded")


def _call_js(calls: list[list]) -> list:
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", _RUNNER, MODULE.as_uri()],
        input=json.dumps(calls), capture_output=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_mine_is_the_default_and_never_written() -> None:
    assert _call_js([["scopeOf", ""], ["roundTrip", ""], ["roundTrip", "?scope=mine"]]) == ["mine", "", ""]


def test_issues_and_all_survive_a_reload_through_the_url_key() -> None:
    assert _call_js([
        ["roundTrip", "?scope=issues"], ["roundTrip", "?scope=all&sort=title"], ["scopeOf", "?scope=bogus"],
    ]) == ["?scope=issues", "?sort=title&scope=all", "mine"]


def test_the_scope_never_makes_the_filters_non_default() -> None:
    assert _call_js([["activeFilterCount", "?scope=all"], ["activeFilterCount", "?scope=issues&due=today"]]) == [0, 1]


def test_a_task_is_an_issue_when_it_carries_an_issue_ref() -> None:
    mine = {"id": 1, "issue_ref": None}
    issue = {"id": 2, "issue_ref": {"provider": "github", "repo": "example/garden-bot", "number": 12}}
    got = _call_js([["matchesScope", t, s] for s in ("mine", "issues", "all") for t in (mine, issue)])
    assert got == [True, False, False, True, True, True]


# ------------------------------------------- the filter button's count (#395)
def _count(search: str, hide: list[str] | None = None) -> int:
    return _call_js([["activeFilterCount", "?" + search, hide]])[0]


def test_the_filter_button_counts_what_clear_would_reset() -> None:
    # the text (the field beside the button shows it) and the scope (the
    # switch's) never count; the default sort is no setting
    assert [_count(s) for s in ("", "q=kitchen", "scope=all", "sort=due")] == [0, 0, 0, 0]
    # one per control that is off its default, a non-default sort included
    assert _count("status=todo,standby&project=12&person=3,5") == 3
    assert _count("due=week&updated=stale30&sort=title") == 3


def test_a_hidden_control_is_not_counted() -> None:
    # the journal hides status · due · modified · sort (#102): what it does not
    # apply, its button does not claim
    assert _count("status=todo&due=today&sort=title&project=12", ["status", "due", "updated", "sort"]) == 1
