"""The Search tab's status filter: open by default, every status once cleared.

Search draws the open statuses ticked, and un-ticking them all means every
status, done and cancelled included. That state is its own ``everyStatus`` flag
(URL word ``status=all``) because ``status: []`` already means "the open tasks"
on Today, Board and the journal, which never read the flag.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.node_js import CALL_RUNNER, call_js, requires_node

MODULE = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "filters.js"
OPEN = ["inbox", "todo", "standby"]

pytestmark = requires_node

_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, search, arg]) => {
  if (fn === 'patch') return mod.searchStatusPatch(search);
  const f = mod.filtersFromSearch(search);
  if (fn === 'kept') return ['inbox', 'todo', 'standby', 'done', 'cancelled'].filter((s) => mod.matchesFilters({ status: s }, f));
  if (fn === 'ticks') return mod.searchStatusTicks(f);
  if (fn === 'coverage') return mod.statusCoverage(f);
  if (fn === 'count') return mod.activeFilterCount(f, [], arg);
  if (fn === 'words') return mod.describeFilters(f, { searchStatus: arg });
  if (fn === 'roundTrip') return mod.filtersToSearch(f);
  if (fn === 'person') return arg.filter((t) => mod.matchesFilters(t, f)).map((t) => t.id);
  if (fn === 'every') return f.everyStatus;
  throw new Error(fn);
});
process.stdout.write(JSON.stringify(out));
"""


def _js(calls: list[list]) -> list:
    return call_js(MODULE, _RUNNER, calls)


def test_the_default_finds_open_tasks_only() -> None:
    assert _js([["kept", ""]]) == [OPEN]


def test_a_cleared_status_filter_finds_every_status() -> None:
    assert _js([["kept", "?status=all"]]) == [OPEN + ["done", "cancelled"]]


def test_a_picked_status_still_narrows_search() -> None:
    assert _js([["kept", "?status=cancelled"], ["kept", "?status=done,todo"]]) == [["cancelled"], ["todo", "done"]]


def test_every_status_survives_the_url_and_is_never_written_by_default() -> None:
    assert _js([["roundTrip", "?status=all"], ["roundTrip", "?status=deferred,all"], ["roundTrip", ""],
                ["every", "?status=all"], ["every", "?status=todo"]]) == ["?status=all", "?status=deferred%2Call", "", True, False]


def test_the_sheet_draws_the_open_statuses_until_cleared() -> None:
    assert _js([["ticks", ""], ["ticks", "?status=all"], ["ticks", "?status=done"], ["ticks", "?status=deferred"]]) == [
        OPEN, [], ["done"], ["deferred"] + OPEN]


def test_ticks_become_the_state_that_search_reads() -> None:
    assert _js([["patch", OPEN], ["patch", []], ["patch", ["deferred"]], ["patch", ["todo"]],
                ["patch", OPEN + ["done"]], ["patch", OPEN + ["blocked"]]]) == [
        {"status": [], "everyStatus": False},
        {"status": [], "everyStatus": True},
        {"status": ["deferred"], "everyStatus": True},
        {"status": ["todo"], "everyStatus": False},
        {"status": OPEN + ["done"], "everyStatus": False},
        {"status": ["blocked"], "everyStatus": False},
    ]


def test_the_coverage_words_say_which_statuses_the_hits_span() -> None:
    assert _js([["coverage", ""], ["coverage", "?status=all"], ["coverage", "?status=done,cancelled"],
                ["coverage", "?status=inbox,todo,standby,done,cancelled"]]) == [
        "open only", "every status", "done, cancelled", "every status"]


def test_every_status_counts_as_a_filter_on_search_only() -> None:
    assert _js([["count", "?status=all", True], ["count", "?status=all", False], ["count", "", True]]) == [1, 0, 0]
    assert _js([["words", "?status=all", True], ["words", "?status=all", False]]) == [["every status"], []]


def test_the_default_list_read_is_not_touched_by_the_flag() -> None:
    # Today / Board / the journal send `status` to /api/tasks from the real ticks only
    out = call_js(MODULE, CALL_RUNNER, [["listParams", [{"status": [], "everyStatus": True, "person": [], "project": "", "due": "", "q": "", "updated": ""}, None]]])
    assert out[0].get("status") is None


def test_the_person_filter_still_applies_when_every_status_is_asked_for() -> None:
    tasks = [{"id": 1, "status": "todo", "person_id": 1}, {"id": 2, "status": "cancelled", "person_id": 1},
             {"id": 3, "status": "cancelled", "person_id": 2}, {"id": 4, "status": "done", "person_id": None}]
    assert _js([["person", "?status=all&person=1", tasks], ["person", "?person=1", tasks], ["person", "?status=all", tasks]]) == [
        [1, 2], [1], [1, 2, 3, 4]]


def _today_board(calls: list[list]) -> list:
    return call_js(MODULE, CALL_RUNNER, calls)


def _f(q: str = "", status: list[str] | None = None, every: bool = False) -> dict:
    return {"status": status or [], "everyStatus": every, "person": [], "project": "", "due": "", "q": q, "updated": ""}


def test_a_typed_query_reads_the_todo_tasks_until_the_pill_is_removed() -> None:
    out = _today_board([["listParams", [_f("bikes"), None]], ["listParams", [_f(""), None]],
                        ["listParams", [_f("bikes", ["done"]), None]], ["listParams", [_f("bikes", ["deferred"]), None]],
                        ["listParams", [_f("   "), None]], ["listParams", [_f("bikes", every=True), None]]])
    assert [o.get("status") for o in out] == [["todo"], None, ["done"], ["deferred", "todo"], None, None]
    assert [o.get("include_closed") for o in out] == [None, None, None, None, None, True]


def test_the_working_lists_show_closed_tasks_only_for_a_picked_status_or_every_status() -> None:
    out = _today_board([["showsClosed", [_f("")]], ["showsClosed", [_f("x")]], ["showsClosed", [_f("", ["todo"])]],
                        ["showsClosed", [_f("x", ["todo"])]], ["showsClosed", [_f("x", every=True)]],
                        ["showsClosed", [_f("", every=True)]]])
    assert out == [False, False, True, True, True, False]


def test_the_coverage_words_follow_the_pills_on_today_and_board() -> None:
    out = _today_board([["statusCoverage", [_f("x"), "todo"]], ["statusCoverage", [_f("x", every=True), "todo"]],
                        ["statusCoverage", [_f("x", ["cancelled"]), "todo"]], ["statusCoverage", [_f("x")]]])
    assert out == ["todo", "every status", "cancelled", "open only"]


def test_the_pills_are_the_todo_default_until_the_filter_is_touched() -> None:
    out = _today_board([["searchStatusTicks", [_f(), ["todo"]]], ["searchStatusTicks", [_f(every=True), ["todo"]]],
                        ["searchStatusTicks", [_f(status=["inbox", "done"]), ["todo"]]],
                        ["searchStatusTicks", [_f(status=["blocked"]), ["todo"]]]])
    assert out == [["todo"], [], ["inbox", "done"], ["blocked", "todo"]]


def test_removing_pills_widens_one_status_at_a_time() -> None:
    out = _today_board([["searchStatusPatch", [[], ["todo"]]], ["searchStatusPatch", [["todo"], ["todo"]]],
                        ["searchStatusPatch", [["todo", "done"], ["todo"]]], ["searchStatusPatch", [["done"], ["todo"]]],
                        ["searchStatusPatch", [["blocked"], ["todo"]]]])
    assert out == [
        {"status": [], "everyStatus": True},
        {"status": [], "everyStatus": False},
        {"status": ["todo", "done"], "everyStatus": False},
        {"status": ["done"], "everyStatus": False},
        {"status": ["blocked"], "everyStatus": True},
    ]
