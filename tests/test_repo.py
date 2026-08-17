"""``src/tasks_repo.py`` — the domain rules on a hermetic, seeded database."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from src import db as dbmod
from src import tasks_repo as repo
from tests.fixtures.seed import DEFAULT_ANCHOR, seed

ANCHOR = DEFAULT_ANCHOR  # 2026-08-17


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db()
    c = dbmod.connect()
    yield c
    c.close()


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> dict:
    result = seed(conn)
    return result["ids"]


@pytest.fixture
def frozen():
    """Pin the repo clock to the anchor date so 'today' is deterministic."""
    with repo.use_clock(lambda: datetime(2026, 8, 17, 9, 0, 0).astimezone()):
        yield


def _fields(activity: list[dict]) -> list[tuple]:
    return [(a["field"], a["old_value"], a["new_value"]) for a in activity]


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
    assert home["is_project"] and home["child_count"] == 3
    assert [c["title"] for c in home["children"]] == ["Kitchen", "Bathroom", "Garden"]

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


# ------------------------------------------------- activity on every change

def test_activity_on_every_change(conn: sqlite3.Connection, frozen: None) -> None:
    t = repo.create_task(conn, "Renew passport", actor="me")
    tid = t["id"]
    assert _fields(t["activity"]) == [("created", None, "Renew passport")]
    repo.set_due(conn, tid, "2026-09-01", actor="me")
    repo.set_status(conn, tid, "todo", actor="me")
    repo.set_priority(conn, tid, "high", actor="me")
    repo.update_task(conn, tid, title="Renew passports", description="both", actor="me")
    repo.update_task(conn, tid, due="2026-09-01", actor="me")  # unchanged → no row
    log = _fields(repo.list_activity(conn, tid))
    assert log == [
        ("description", "", "both"),
        ("title", "Renew passport", "Renew passports"),
        ("priority", "none", "high"),
        ("status", "inbox", "todo"),
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
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "x", due="next friday")   # repo takes ISO only
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "x", bogus=1)
    with pytest.raises(repo.NotFound):
        repo.create_task(conn, "x", parent_id=42)
    with pytest.raises(repo.NotFound):
        repo.get_task(conn, 42)


# ---------------------------------------------------------- recurrence

@pytest.mark.parametrize(
    ("cadence", "due", "expected"),
    [
        ("daily", "2026-08-31", "2026-09-01"),
        ("weekly", "2026-08-31", "2026-09-07"),
        ("monthly", "2026-01-31", "2026-02-28"),
        ("monthly", "2026-08-31", "2026-09-30"),
        ("quarterly", "2026-11-30", "2027-02-28"),
        ("yearly", "2028-02-29", "2029-02-28"),
    ],
)
def test_done_rolls_recurring_from_due(conn: sqlite3.Connection, cadence: str, due: str, expected: str) -> None:
    t = repo.create_task(conn, "Recurring", recurrence=cadence, due=due, status="todo")
    rolled = repo.done(conn, t["id"], actor="me")
    assert rolled["id"] == t["id"]              # same task
    assert rolled["due"] == expected
    assert rolled["status"] == "todo"           # not closed
    assert rolled["done_at"] is None
    log = _fields(rolled["activity"])
    assert ("done", due, expected) in log
    assert ("due", due, expected) in log


def test_done_recurring_without_due_rolls_from_today(conn: sqlite3.Connection, frozen: None) -> None:
    t = repo.create_task(conn, "Stretch", recurrence="weekly")
    assert repo.done(conn, t["id"])["due"] == "2026-08-24"


def test_done_non_recurring_closes(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "One-off", due="2026-08-20")
    d = repo.done(conn, t["id"], actor="me")
    assert d["status"] == "done" and d["done_at"] and d["due"] == "2026-08-20"
    assert _fields(d["activity"])[0] == ("status", "inbox", "done")
    assert d["id"] not in {x["id"] for x in repo.list_tasks(conn)}
    assert d["id"] in {x["id"] for x in repo.list_tasks(conn, include_closed=True)}


# ------------------------------------------------------------ comments

def test_comments_thread_order_and_origin(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Talk")
    ts = iter([
        datetime(2026, 8, 17, 9, 0), datetime(2026, 8, 17, 9, 5), datetime(2026, 8, 17, 9, 5),
    ])
    with repo.use_clock(lambda: next(ts).astimezone()):
        repo.add_comment(conn, t["id"], "first", author="a", origin="cli")
        repo.add_comment(conn, t["id"], "second", author="b")
        repo.add_comment(conn, t["id"], "third (same second)", author="b", origin="md")
    thread = repo.list_comments(conn, t["id"])
    assert [c["body"] for c in thread] == ["first", "second", "third (same second)"]
    assert [c["origin"] for c in thread] == ["cli", "ui", "md"]
    assert thread[0]["author"] == "a"
    with pytest.raises(repo.ValidationError):
        repo.add_comment(conn, t["id"], "  ")
    with pytest.raises(repo.ValidationError):
        repo.add_comment(conn, t["id"], "x", origin="fax")
    with pytest.raises(repo.NotFound):
        repo.add_comment(conn, 999, "x")


# ---------------------------------------------------------------- links

def test_links_add_list_remove(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Docs")
    lk = repo.add_link(conn, t["id"], "https://example.com", label="site", kind="web")
    repo.add_link(conn, t["id"], "{onedrive}/x", kind="folder")
    assert [x["kind"] for x in repo.list_links(conn, t["id"])] == ["web", "folder"]
    repo.remove_link(conn, t["id"], lk["id"])
    assert len(repo.list_links(conn, t["id"])) == 1
    with pytest.raises(repo.NotFound):
        repo.remove_link(conn, t["id"], lk["id"])
    with pytest.raises(repo.ValidationError):
        repo.add_link(conn, t["id"], "x", kind="carrier-pigeon")


# ------------------------------------------------------- coding / issue

def test_coding_iff_issue_ref(conn: sqlite3.Connection) -> None:
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "Bug", type="coding")
    t = repo.create_task(conn, "Bug")
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, t["id"], type="coding")
    c = repo.set_issue_ref(conn, t["id"], provider="github", repo="example/repo", number=7, actor="me")
    assert c["type"] == "coding" and c["issue_ref"]["number"] == 7
    assert ("type", "task", "coding") in _fields(c["activity"])
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, t["id"], type="note")   # still has an issue
    back = repo.remove_issue_ref(conn, t["id"])
    assert back["type"] == "task" and back["issue_ref"] is None
    with pytest.raises(repo.NotFound):
        repo.remove_issue_ref(conn, t["id"])


# --------------------------------------------------------------- people

def test_people_crud_and_task_pointer(conn: sqlite3.Connection) -> None:
    p = repo.create_person(conn, "Sam", email="s@example.com")
    t = repo.create_task(conn, "Call", person_id=p["id"], status="todo")
    assert t["person"] == {"id": p["id"], "name": "Sam"}
    assert repo.get_person(conn, p["id"])["open_tasks"] == 1
    assert repo.update_person(conn, p["id"], name="Sam R.")["name"] == "Sam R."
    assert [x["id"] for x in repo.list_tasks(conn, person_id=p["id"])] == [t["id"]]
    with pytest.raises(repo.NotFound):
        repo.create_task(conn, "x", person_id=999)
    repo.delete_person(conn, p["id"])
    assert repo.get_task(conn, t["id"])["person_id"] is None
    with pytest.raises(repo.NotFound):
        repo.get_person(conn, p["id"])


# ---------------------------------------------------------- list / due

def test_list_filters(conn: sqlite3.Connection, seeded: dict, frozen: None) -> None:
    today = {t["title"] for t in repo.list_tasks(conn, due="today")}
    assert {"School enrolment forms", "Call the plumber back", "Practice scales"} <= today
    overdue = {t["title"] for t in repo.list_tasks(conn, due="overdue")}
    assert {"Fix leaking tap", "Return library books", "Repair fence"} <= overdue
    assert "Buy a birthday gift" not in overdue          # done → hidden
    week = repo.list_tasks(conn, due="week")
    assert all(ANCHOR.isoformat() <= t["due"] <= "2026-08-24" for t in week)
    assert [t["title"] for t in repo.list_tasks(conn, status="standby", project=seeded["home"])] == [
        "Plant tomatoes", "Garden",
    ]
    assert {t["title"] for t in repo.list_tasks(conn, parent_id="root")} >= {"Home renovation", "Learning"}
    assert [t["type"] for t in repo.list_tasks(conn, type="coding")] == ["coding"]
    assert [t["title"] for t in repo.list_tasks(conn, type="note")] == ["Reading list"]
    with pytest.raises(repo.ValidationError):
        repo.list_tasks(conn, status="later")


def test_delete_cascades_subtree(conn: sqlite3.Connection, seeded: dict) -> None:
    before = repo.counts(conn)
    r = repo.delete_task(conn, seeded["kitchen"])
    assert r["deleted"] == 4                                    # kitchen + 3 children
    after = repo.counts(conn)
    assert before["tasks"] - after["tasks"] == 4
    assert after["links"] == before["links"] - 2               # kitchen's two links
    with pytest.raises(repo.NotFound):
        repo.get_task(conn, seeded["quotes"])


# --------------------------------------------------------------- search

def test_search_title_description_and_comments(conn: sqlite3.Connection, seeded: dict) -> None:
    by_title = repo.search(conn, "worktop")
    assert [h["id"] for h in by_title] == [seeded["worktop"]]
    assert by_title[0]["matched_in"] == "title" and "[worktop]" in by_title[0]["snippet"]
    assert [c["title"] for c in by_title[0]["breadcrumb"]] == ["Home renovation", "Kitchen"]

    by_desc = repo.search(conn, "balcony")
    assert [h["id"] for h in by_desc] == [seeded["bot"]]
    assert by_desc[0]["matched_in"] == "description"

    by_comment = repo.search(conn, "washer")
    assert [h["id"] for h in by_comment] == [seeded["tap"]]
    assert by_comment[0]["matched_in"] == "comment" and "[washer]" in by_comment[0]["snippet"]

    # prefix + punctuation-safe
    assert seeded["watering"] in {h["id"] for h in repo.search(conn, "garden-bot#12")}
    assert seeded["quotes"] in {h["id"] for h in repo.search(conn, "quot")}
    assert repo.search(conn, "") == []
    assert repo.search(conn, "zzzznothing") == []
    # a hit reaches list_tasks via q=
    assert [t["id"] for t in repo.list_tasks(conn, q="washer")] == [seeded["tap"]]


def test_fts_follows_updates_and_deletes(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Alpha", description="first text")
    assert repo.search(conn, "alpha")
    repo.update_task(conn, t["id"], title="Beta")
    assert not repo.search(conn, "alpha") and repo.search(conn, "beta")
    c = repo.add_comment(conn, t["id"], "unique gamma word")
    assert repo.search(conn, "gamma")[0]["matched_in"] == "comment"
    repo.delete_comment(conn, c["id"])
    assert not repo.search(conn, "gamma")
    repo.delete_task(conn, t["id"])
    assert not repo.search(conn, "beta")


def test_dates_stay_iso_and_clock_pinned(conn: sqlite3.Connection, frozen: None) -> None:
    t = repo.create_task(conn, "Clock", due=date(2026, 9, 1))
    assert t["due"] == "2026-09-01"
    assert t["created_at"].startswith("2026-08-17T09:00:00")
