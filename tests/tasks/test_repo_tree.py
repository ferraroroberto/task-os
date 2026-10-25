"""``src/tasks_repo.py`` â€” the domain rules on a hermetic, seeded database: the
seed, nesting and the cycle guard, blockers, activity and validation."""

from __future__ import annotations

import sqlite3

import pytest

from src import tasks_repo as repo
from tests.fixtures.seed import seed
from tests.tasks._support import (
    _fields,
)

# --------------------------------------------------------- seed / shape

def test_seed_is_deterministic_and_refuses_twice(conn: sqlite3.Connection) -> None:
    r1 = seed(conn)
    assert r1["counts"]["tasks"] >= 40
    assert r1["counts"]["people"] == 3
    assert r1["counts"]["comments"] >= 8
    assert r1["counts"]["issue_refs"] == 1
    assert r1["ids"]["home"] == 1
    with pytest.raises(RuntimeError):
        seed(conn)


# ------------------------------------------------- nesting / tree / crumb

def test_nesting_tree_and_breadcrumb(conn: sqlite3.Connection, seeded: dict) -> None:
    quotes = repo.get_task(conn, seeded["quotes"])
    assert [c["title"] for c in quotes["breadcrumb"]] == ["Home renovation", "Kitchen"]
    home = repo.get_task(conn, seeded["home"])
    assert home["is_project"] and home["child_count"] == 5    # 3 rooms + the dormant task (#101) + the kettle (#102)
    assert [c["title"] for c in home["children"]] == ["Kitchen", "Bathroom", "Garden", "Sort the garage shelves", "Descale the kettle"]

    forest = repo.tree(conn)
    roots = [n["title"] for n in forest]
    assert roots[:4] == ["Home renovation", "Family admin", "Side project: garden-bot", "Learning"]
    kitchen = forest[0]["children"][0]
    assert kitchen["depth"] == 1
    assert [c["title"] for c in kitchen["children"]] == [
        "Get three quotes", "Choose worktop material", "Book installer",
    ]
    assert kitchen["children"][0]["depth"] == 2

    subtree = repo.tree(conn, seeded["bot"])
    assert len(subtree) == 1 and subtree[0]["title"] == "Side project: garden-bot"
    # done leaf pruned by default, kept with include_closed
    sensor = next(c for c in subtree[0]["children"] if c["title"] == "Add moisture sensor")
    assert [c["title"] for c in sensor["children"]] == ["Write sensor driver"]
    sensor_all = next(
        c for c in repo.tree(conn, seeded["bot"], include_closed=True)[0]["children"]
        if c["title"] == "Add moisture sensor"
    )
    assert [c["title"] for c in sensor_all["children"]] == ["Order sensor", "Write sensor driver"]


def test_project_filter_is_descendant_of(conn: sqlite3.Connection, seeded: dict) -> None:
    ids = {t["id"] for t in repo.list_tasks(conn, project=seeded["home"], include_closed=True)}
    assert seeded["quotes"] in ids and seeded["fence"] in ids and seeded["kitchen"] in ids
    assert seeded["home"] not in ids
    assert seeded["family"] not in ids
    assert repo.list_tasks(conn, project=seeded["quotes"]) == []  # a leaf has no descendants


def test_move_and_cycle_guard(conn: sqlite3.Connection, seeded: dict) -> None:
    home, kitchen, quotes = seeded["home"], seeded["kitchen"], seeded["quotes"]
    with pytest.raises(repo.CycleError):
        repo.move(conn, home, quotes)          # under its own grandchild
    with pytest.raises(repo.CycleError):
        repo.move(conn, kitchen, kitchen)      # under itself
    with pytest.raises(repo.NotFound):
        repo.move(conn, kitchen, 9999)
    moved = repo.move(conn, quotes, seeded["family"], actor="tester")
    assert moved["parent_id"] == seeded["family"]
    assert [c["title"] for c in moved["breadcrumb"]] == ["Family admin"]
    assert _fields(moved["activity"])[0] == ("parent", str(kitchen), str(seeded["family"]))
    assert moved["activity"][0]["actor"] == "tester"
    root = repo.move(conn, quotes, None)
    assert root["parent_id"] is None and root["breadcrumb"] == []
    # no-op move writes nothing
    n = len(repo.list_activity(conn, quotes))
    repo.move(conn, quotes, None)
    assert len(repo.list_activity(conn, quotes)) == n


def test_update_task_validates_every_field_before_it_re_parents(
    conn: sqlite3.Connection, seeded: dict
) -> None:
    """A PATCH with a good parent and a bad field changes nothing, not half of it."""
    quotes, family = seeded["quotes"], seeded["family"]
    before = repo.get_task(conn, quotes)
    n = len(repo.list_activity(conn, quotes))
    for bad in ({"title": ""}, {"priority": "nope"}, {"person_id": 9999}):
        with pytest.raises(repo.RepoError):
            repo.update_task(conn, quotes, parent_id=family, **bad)
        assert repo.get_task(conn, quotes)["parent_id"] == before["parent_id"]
        assert len(repo.list_activity(conn, quotes)) == n

    both = repo.update_task(conn, quotes, parent_id=family, title="Quotes v2", actor="tester")
    assert both["parent_id"] == family and both["title"] == "Quotes v2"
    logged = {f for f, _, _ in _fields(both["activity"])}
    assert {"parent", "title"} <= logged


def test_would_cycle_is_exactly_the_verdict_move_enforces(
    conn: sqlite3.Connection, seeded: dict
) -> None:
    """``would_cycle`` is now the single copy of the parent-cycle rule (#185),
    read by ``move`` and by ``src.ai.triage``'s response validator. Its two
    phrasings — "is the proposed parent below me?" (a descendants CTE) and
    "am I above the proposed parent?" (the ancestor walk triage used to do for
    itself) — are only the same question if the direction is right, so assert
    it against ``move`` itself over every ordered pair in the seeded tree
    rather than against a hand-picked example.
    """
    ids = [int(r["id"]) for r in conn.execute("SELECT id FROM tasks ORDER BY id")]
    assert len(ids) >= 40
    for task_id in ids:
        original_parent = repo.get_task(conn, task_id)["parent_id"]
        for parent_id in [*ids, None]:
            predicted = repo.would_cycle(conn, task_id, parent_id)
            try:
                repo.move(conn, task_id, parent_id)
            except repo.CycleError:
                assert predicted is True, f"move refused {task_id}->{parent_id}, would_cycle did not"
            else:
                assert predicted is False, f"move allowed {task_id}->{parent_id}, would_cycle refused"
                repo.move(conn, task_id, original_parent)       # put it back for the next pair


# ---------------------------------------------------------- blocked-by (#100)

def test_seeded_blocked_pair(conn: sqlite3.Connection, seeded: dict) -> None:
    """The seed's one real pair (Release v0.2 blocked on the sensor driver):
    hidden from the default working-view list, present under the ``blocked``
    filter and in the tree, with a lock and the right count."""
    release, driver = seeded["release"], seeded["driver"]
    task = repo.get_task(conn, release)
    assert task["blocked"] is True and task["blocker_count"] == 1
    assert [b["id"] for b in task["blocked_by"]] == [driver]

    open_ids = {t["id"] for t in repo.list_tasks(conn)}
    assert release not in open_ids                       # hidden by default (blocked="hide")
    only_ids = {t["id"] for t in repo.list_tasks(conn, blocked="only")}
    assert only_ids == {release}
    all_ids = {t["id"] for t in repo.list_tasks(conn, blocked="all")}
    assert release in all_ids

    node = next(n for n in repo.tree(conn) if n["title"] == "Side project: garden-bot")
    release_node = next(
        c for c in node["children"] if c["title"] == "Release v0.2"
    )
    assert release_node["blocked"] is True and release_node["blocker_count"] == 1


def test_the_tree_and_a_task_agree_on_its_blockers(conn: sqlite3.Connection, seeded: dict) -> None:
    """The tree's prefetched blocked-by keys are the ones the task itself
    carries — same blockers, same order, same derived facts — however the
    edges were added (the newest, lowest id here goes in last)."""
    release = seeded["release"]
    low, high = sorted((seeded["quotes"], seeded["worktop"]))
    repo.add_blocker(conn, release, high)
    repo.add_blocker(conn, release, low)
    repo.set_status(conn, low, "done")
    task = repo.get_task(conn, release)
    node = repo.tree(conn, release)[0]
    keys = ("blocked_by", "blocked", "blocker_count")
    assert {k: node[k] for k in keys} == {k: task[k] for k in keys}
    assert [b["id"] for b in node["blocked_by"]] == sorted([seeded["driver"], low, high])
    assert node["blocker_count"] == 2                     # the closed one no longer counts


def test_add_blocker_refuses_self_and_cycle(conn: sqlite3.Connection, seeded: dict) -> None:
    quotes, worktop = seeded["quotes"], seeded["worktop"]
    with pytest.raises(repo.CycleError):
        repo.add_blocker(conn, quotes, quotes)            # self-block
    repo.add_blocker(conn, quotes, worktop, actor="tester")  # worktop blocks quotes
    with pytest.raises(repo.CycleError):
        repo.add_blocker(conn, worktop, quotes)            # would close the loop
    with pytest.raises(repo.NotFound):
        repo.add_blocker(conn, quotes, 9999)


def test_add_and_remove_blocker_logs_both_sides_and_is_idempotent(
    conn: sqlite3.Connection, seeded: dict
) -> None:
    quotes, worktop = seeded["quotes"], seeded["worktop"]
    n_quotes = len(repo.list_activity(conn, quotes))
    n_worktop = len(repo.list_activity(conn, worktop))
    blocked = repo.add_blocker(conn, quotes, worktop, actor="tester")
    assert blocked["blocked"] is True and blocked["blocker_count"] == 1
    assert _fields(repo.list_activity(conn, quotes))[0] == ("blocked_by", None, str(worktop))
    assert _fields(repo.list_activity(conn, worktop))[0] == ("blocks", None, str(quotes))
    # duplicate add is a no-op: no new activity rows
    repo.add_blocker(conn, quotes, worktop, actor="tester")
    assert len(repo.list_activity(conn, quotes)) == n_quotes + 1
    assert len(repo.list_activity(conn, worktop)) == n_worktop + 1

    unblocked = repo.remove_blocker(conn, quotes, worktop, actor="tester")
    assert unblocked["blocked"] is False and unblocked["blocker_count"] == 0
    assert _fields(repo.list_activity(conn, quotes))[0] == ("blocked_by", str(worktop), None)
    assert _fields(repo.list_activity(conn, worktop))[0] == ("blocks", str(quotes), None)
    with pytest.raises(repo.NotFound):
        repo.remove_blocker(conn, quotes, worktop)


def test_a_closed_blocker_does_not_block(conn: sqlite3.Connection, seeded: dict) -> None:
    """Only OPEN blockers gate a task — closing the last one unblocks it,
    and re-listing without ``blocked`` shows it again."""
    release, driver = seeded["release"], seeded["driver"]
    repo.set_status(conn, driver, "done", actor="tester")
    task = repo.get_task(conn, release)
    assert task["blocked"] is False and task["blocker_count"] == 0
    assert [b["id"] for b in task["blocked_by"]] == [driver]   # the edge itself is untouched
    assert release in {t["id"] for t in repo.list_tasks(conn)}


def test_delete_a_blocker_logs_unblock_on_the_survivor(conn: sqlite3.Connection, seeded: dict) -> None:
    release, driver = seeded["release"], seeded["driver"]
    n = len(repo.list_activity(conn, release))
    repo.delete_task(conn, driver, actor="tester")
    log = _fields(repo.list_activity(conn, release))
    assert log[0] == ("blocked_by", str(driver), None)
    assert len(log) == n + 1
    task = repo.get_task(conn, release)
    assert task["blocked"] is False and task["blocked_by"] == []


# ------------------------------------------------- activity on every change

def test_activity_on_every_change(conn: sqlite3.Connection, frozen: None) -> None:
    t = repo.create_task(conn, "Renew passport", actor="me")
    tid = t["id"]
    assert _fields(t["activity"]) == [("created", None, "Renew passport")]
    repo.set_due(conn, tid, "2026-09-01", actor="me")
    repo.set_status(conn, tid, "standby", actor="me")   # a real move: create already made it todo
    repo.set_priority(conn, tid, "high", actor="me")
    repo.update_task(conn, tid, title="Renew passports", description="both", actor="me")
    repo.update_task(conn, tid, due="2026-09-01", actor="me")  # unchanged → no row
    log = _fields(repo.list_activity(conn, tid))
    assert log == [
        ("description", "", "both"),
        ("title", "Renew passport", "Renew passports"),
        ("priority", "none", "high"),
        ("status", "todo", "standby"),
        ("due", None, "2026-09-01"),
        ("created", None, "Renew passport"),
    ]
    assert all(a["actor"] == "me" for a in repo.list_activity(conn, tid))
    # done via status stamps done_at; leaving done clears it
    done = repo.set_status(conn, tid, "done")
    assert done["done_at"]
    assert repo.set_status(conn, tid, "todo")["done_at"] is None


def test_validation_errors(conn: sqlite3.Connection) -> None:
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "   ")
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "x", status="later")
    with pytest.raises(repo.ValidationError, match="status must be one of"):
        repo.create_task(conn, "x", status="doing")
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "x", due="next friday")   # repo takes ISO only
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "x", bogus=1)
    with pytest.raises(repo.NotFound):
        repo.create_task(conn, "x", parent_id=42)
    with pytest.raises(repo.NotFound):
        repo.get_task(conn, 42)
