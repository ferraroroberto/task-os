"""``filters.js`` — the Tasks · Issues · All scope (#391, decision 1 of #390)
and the Mine · Everyone whose switch (#477, Step 4/4 of #471).

The scope rides the shared filter state as one URL key, so it survives a
reload, but it is the segmented switch's, not the filter sheet's: it is never
written for the default Tasks (its id stays ``mine``), never counts as a filter
(the sheet's Clear stays hidden for it), and an unknown value reads back as the
default. A task is an issue when it carries an ``issue_ref`` — the coding task
the forge sync made. ``whose`` is a separate axis with the same standing: one
URL key written only for Everyone, an explicit URL value beating the device's
remembered pick, and the owner it narrows to sent to the server, never applied
to a Search hit. The strip's filter button (#395) counts the settings the
sheet's Clear would reset.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.node_js import call_js, requires_node

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "filters.js"

# Reads [[fn, arg, arg2], …] on stdin and prints each result as one JSON array.
_RUNNER = """
const mod = await import(process.argv[1]);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(([fn, a, b]) => {
  if (fn === 'roundTrip') return mod.filtersToSearch(mod.filtersFromSearch(a));
  if (fn === 'scopeOf') return mod.filtersFromSearch(a).scope;
  if (fn === 'whoseOf') return mod.filtersFromSearch(a, b).whose;
  if (fn === 'storedWhose') return mod.storedWhose(
    b === 'none' ? null : b === 'throws' ? { getItem() { throw new Error('private mode'); } } : { getItem: () => a });
  if (fn === 'ownerOf') return mod.ownerOf(mod.filtersFromSearch(a.search), a.viewer, a.members);
  if (fn === 'ownerParam') return mod.listParams(mod.filtersFromSearch(a.search), a.owner).owner ?? null;
  if (fn === 'toggle') return mod.toggleOwner(mod.filtersFromSearch(a.search), a.id, a.viewer);
  if (fn === 'picked') return mod.pickedOwners(mod.filtersFromSearch(a.search), a.viewer);
  if (fn === 'names') return mod.showsAssignees(mod.filtersFromSearch(a.search), a.members);
  if (fn === 'visible') {
    const v = mod.visibleOwners(a.members, a.viewer, a.picked, a.recent);
    return { shown: v.shown.map((m) => m.id), more: v.more, ordered: v.ordered.map((m) => m.id) };
  }
  if (fn === 'labels') return mod.SCOPES.map((s) => s[1]).concat(mod.WHOSE.map((w) => w[1]));
  if (fn === 'activeFilterCount') return mod.activeFilterCount(mod.filtersFromSearch(a), b);
  return mod[fn](a, b);
});
process.stdout.write(JSON.stringify(out));
"""

pytestmark = requires_node


def _call_js(calls: list[list]) -> list:
    return call_js(MODULE, _RUNNER, calls)


def test_mine_is_the_default_and_never_written() -> None:
    assert _call_js([["scopeOf", ""], ["roundTrip", ""], ["roundTrip", "?scope=mine"]]) == ["mine", "", ""]


def test_issues_and_all_survive_a_reload_through_the_url_key() -> None:
    assert _call_js([
        ["roundTrip", "?scope=issues"], ["roundTrip", "?scope=all&sort=title"], ["scopeOf", "?scope=bogus"],
    ]) == ["?scope=issues", "?sort=title&scope=all", "mine"]


def test_the_scope_never_makes_the_filters_non_default() -> None:
    assert _call_js([["activeFilterCount", "?scope=all"], ["activeFilterCount", "?scope=issues&due=today"]]) == [0, 1]


def test_the_scope_reads_tasks_issues_all_and_keeps_its_ids() -> None:
    # #477: "Mine" now names the whose axis; the scope's first label is Tasks
    # and its id (so every saved ``?scope=`` link) is unchanged
    assert _call_js([["labels"]]) == [["Tasks", "Issues", "All", "Mine", "Everyone"]]
    assert _call_js([["scopeOf", "?scope=mine"], ["scopeOf", "?scope=issues"]]) == ["mine", "issues"]


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


# ------------------------------------------------- whose (#477, Step 4/4 of #471)
def test_mine_is_the_default_whose_and_only_everyone_is_written() -> None:
    assert _call_js([
        ["whoseOf", ""], ["roundTrip", ""], ["roundTrip", "?whose=mine"],
        ["roundTrip", "?whose=everyone"], ["roundTrip", "?scope=all&whose=everyone&sort=title"],
    ]) == ["mine", "", "", "?whose=everyone", "?sort=title&scope=all&whose=everyone"]


def test_an_explicit_url_value_beats_the_stored_pick() -> None:
    assert _call_js([
        ["whoseOf", "", "everyone"],               # no key: the device's pick
        ["whoseOf", "?whose=mine", "everyone"],    # an explicit Mine wins over a stored Everyone
        ["whoseOf", "?whose=everyone", "mine"],    # …and an explicit Everyone over a stored Mine
        ["whoseOf", "?whose=bogus", "everyone"],   # an unknown value is no value: the stored pick
        ["whoseOf", "", None],
    ]) == ["everyone", "mine", "everyone", "everyone", "mine"]


def test_the_stored_pick_is_everyone_only_when_it_says_so() -> None:
    assert _call_js([
        ["storedWhose", "everyone"], ["storedWhose", "mine"], ["storedWhose", "garbage"],
        ["storedWhose", "", "none"], ["storedWhose", "", "throws"],
    ]) == ["everyone", "mine", "mine", "mine", "mine"]


def test_whose_never_makes_the_filters_non_default() -> None:
    # like the scope it is the switch's, so Clear has nothing to reset for it
    assert _call_js([
        ["activeFilterCount", "?whose=everyone"], ["activeFilterCount", "?whose=everyone&due=today"],
    ]) == [0, 1]


def test_mine_narrows_to_the_viewer_only_with_two_members_and_a_known_viewer() -> None:
    def owner(search: str, viewer: str | None, members: int) -> list:
        return ["ownerOf", {"search": search, "viewer": viewer, "members": members}]

    assert _call_js([
        owner("", "p2", 2),                  # Mine, two members: the viewer's tasks
        owner("?whose=everyone", "p2", 2),   # Everyone: nothing narrows
        owner("", "p2", 1),                  # one member: no switch, nothing to narrow
        owner("", None, 2),                  # unknown viewer: an unknown never hides a task
        owner("", "p1", 3),
    ]) == ["p2", None, None, None, "p1"]


def test_the_list_query_carries_the_owner_the_switch_narrows_to() -> None:
    assert _call_js([
        ["ownerParam", {"search": "", "owner": "p2"}],
        ["ownerParam", {"search": "", "owner": None}],
        ["ownerParam", {"search": "?whose=everyone", "owner": None}],
    ]) == ["p2", None, None]


def test_owner_is_its_own_url_key_and_person_stays_the_contact_filter() -> None:
    assert _call_js([
        ["roundTrip", "?owner=p2,p3"], ["roundTrip", "?owner=p2&whose=everyone"],
        ["roundTrip", "?person=3,5&owner=p2"], ["roundTrip", "?owner=bad id,p2"],
    ]) == ["?owner=p2%2Cp3", "?owner=p2", "?person=3%2C5&owner=p2", "?owner=p2"]


def test_picked_people_narrow_the_list_in_place_of_mine_and_everyone() -> None:
    def owner(search: str, viewer: str | None, members: int) -> list:
        return ["ownerOf", {"search": search, "viewer": viewer, "members": members}]

    assert _call_js([
        owner("?owner=p2", "p1", 3),
        owner("?owner=p1,p3", "p1", 3),
        owner("?owner=p2&whose=everyone", "p1", 3),
        owner("?owner=p2", "p1", 1),        # one member: no row, nothing to narrow
        owner("?owner=p2", None, 3),        # picked people need no known viewer
    ]) == ["p2", "p1,p3", "p2", None, "p2"]


def test_the_row_presses_the_picked_people_or_the_viewer_under_mine() -> None:
    def picked(search: str, viewer: str | None) -> list:
        return ["picked", {"search": search, "viewer": viewer}]

    assert _call_js([
        picked("", "p1"), picked("?whose=everyone", "p1"), picked("?owner=p2,p3", "p1"), picked("", None),
    ]) == [["p1"], [], ["p2", "p3"], []]


def test_a_tap_toggles_one_person_and_an_empty_set_falls_back_to_mine() -> None:
    def tap(search: str, person: str) -> list:
        return ["toggle", {"search": search, "id": person, "viewer": "p1"}]

    mine = {"owners": [], "whose": "mine"}
    assert _call_js([
        tap("", "p2"),                          # Mine + Person 2
        tap("?owner=p1,p2", "p1"),              # off again: Person 2 alone
        tap("?owner=p2", "p2"),                 # the last one off: back to Mine
        tap("?owner=p2,p3", "p3"),
        tap("?whose=everyone", "p2"),           # from Everyone: that person alone
        tap("?whose=everyone", "p1"),           # Mine from Everyone: Mine, no key
        tap("?owner=p2", "p1"),                 # Mine added to a pick
    ]) == [
        {"owners": ["p1", "p2"], "whose": "mine"}, {"owners": ["p2"], "whose": "mine"}, mine,
        {"owners": ["p2"], "whose": "mine"}, {"owners": ["p2"], "whose": "mine"}, mine,
        {"owners": ["p2", "p1"], "whose": "mine"},
    ]


def test_rows_name_their_assignee_once_two_or_more_people_are_on() -> None:
    def names(search: str, members: int = 3) -> list:
        return ["names", {"search": search, "members": members}]

    assert _call_js([
        names(""), names("?whose=everyone"), names("?owner=p2"), names("?owner=p2,p3"),
        names("?whose=everyone", 1),
    ]) == [False, True, False, True, False]


def _roster(n: int) -> list[dict]:
    return [{"id": f"p{i}", "name": f"Person {i}"} for i in range(1, n + 1)]


def test_a_small_install_shows_every_member_and_a_large_one_folds_the_rest() -> None:
    def visible(n: int, picked: list[str], recent: list[str]) -> list:
        return ["visible", {"members": _roster(n), "viewer": "p1", "picked": picked, "recent": recent}]

    small, big, front, held = _call_js([
        visible(6, [], []),                    # five besides the viewer: all in the row
        visible(9, [], []),                    # eight besides: five and "+3 more"
        visible(9, [], ["p8", "p7"]),          # the recently picked move to the front
        visible(9, ["p9"], ["p8"]),            # a picked one is always in the row
    ])
    assert small == {"shown": ["p2", "p3", "p4", "p5", "p6"], "more": 0, "ordered": ["p2", "p3", "p4", "p5", "p6"]}
    assert big["shown"] == ["p2", "p3", "p4", "p5", "p6"] and big["more"] == 3
    assert front["shown"] == ["p8", "p7", "p2", "p3", "p4"] and front["more"] == 3
    assert front["ordered"][:2] == ["p8", "p7"] and len(front["ordered"]) == 8
    assert held["shown"][:2] == ["p9", "p8"] and held["more"] == 3


def test_the_recent_picks_keep_the_newest_first_and_survive_a_bad_store() -> None:
    assert _call_js([
        ["bumpRecentOwner", ["p2", "p3"], "p3"], ["bumpRecentOwner", [], "p2"],
        ["bumpRecentOwner", ["a", "b", "c", "d", "e", "f", "g", "h"], "z"],
    ]) == [["p3", "p2"], ["p2"], ["z", "a", "b", "c", "d", "e", "f", "g"]]
