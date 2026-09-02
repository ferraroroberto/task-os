"""``src/tasks_repo.py`` — the domain rules on a hermetic, seeded database."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from src import db as dbmod
from src import tasks_repo as repo
from tests.fixtures.seed import PINNED_ANCHOR, seed

ANCHOR = PINNED_ANCHOR  # 2026-08-17


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
    result = seed(conn, ANCHOR)
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
        ("monthly", "2026-08-31", "2026-09-30"),
        ("quarterly", "2026-11-30", "2027-02-28"),
        ("yearly", "2028-02-29", "2029-02-28"),
    ],
)
def test_done_rolls_recurring_from_due(
    conn: sqlite3.Connection, frozen: None, cadence: str, due: str, expected: str
) -> None:
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


# ------------------------------------------- fixed-day anchors (#112)

def test_done_rolls_to_the_anchored_weekday(conn: sqlite3.Connection, frozen: None) -> None:
    """The story: a Friday task ticked on Monday lands on Friday, not next Monday."""
    t = repo.create_task(conn, "Weekly review", status="todo", due="2026-08-14",
                         recurrence="weekly", recurrence_anchor="fri")
    rolled = repo.done(conn, t["id"], actor="me")
    assert rolled["due"] == "2026-08-21"                        # today is Mon 17 Aug
    assert ("due", "2026-08-14", "2026-08-21") in _fields(rolled["activity"])


def test_done_rolls_an_overdue_plain_recurrence_into_the_future(
    conn: sqlite3.Connection, frozen: None
) -> None:
    """A month-late weekly keeps its weekday and clears today — no second past due."""
    t = repo.create_task(conn, "Water the plants", status="todo",
                         due="2026-07-20", recurrence="weekly")
    assert repo.done(conn, t["id"])["due"] == "2026-08-24"      # a Monday, ahead of today


def test_done_rolls_to_the_anchored_day_of_month(conn: sqlite3.Connection, frozen: None) -> None:
    t = repo.create_task(conn, "Pay water bill", status="todo", due="2026-08-15",
                         recurrence="monthly", recurrence_anchor="day-15")
    assert repo.done(conn, t["id"])["due"] == "2026-09-15"


def test_anchor_is_stored_canonically(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Standup notes", recurrence="weekly",
                         recurrence_anchor=" Friday , mon ")
    assert t["recurrence_anchor"] == "mon,fri"


@pytest.mark.parametrize(
    ("cadence", "anchor"),
    [("daily", "fri"), ("yearly", "day-1"), ("weekly", "funday"), ("monthly", "5-sun")],
)
def test_bad_anchor_is_rejected(conn: sqlite3.Connection, cadence: str, anchor: str) -> None:
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "Nope", recurrence=cadence, recurrence_anchor=anchor)
    t = repo.create_task(conn, "Nope too", recurrence=cadence)
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, t["id"], recurrence_anchor=anchor)


def test_changing_the_cadence_drops_an_anchor_it_cannot_carry(conn: sqlite3.Connection) -> None:
    """Switching Repeat is an edit, not a mistake — the fixed day is cleared and logged."""
    t = repo.create_task(conn, "Weekly review", recurrence="weekly", recurrence_anchor="fri")
    rolled = repo.update_task(conn, t["id"], recurrence="quarterly", actor="me")
    assert rolled["recurrence_anchor"] is None
    assert ("recurrence_anchor", "fri", None) in _fields(rolled["activity"])
    # and clearing the recurrence altogether takes the anchor with it
    back = repo.update_task(conn, t["id"], recurrence="weekly", recurrence_anchor="mon")
    assert repo.update_task(conn, back["id"], recurrence=None)["recurrence_anchor"] is None


def test_done_non_recurring_closes(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "One-off", due="2026-08-20")
    d = repo.done(conn, t["id"], actor="me")
    assert d["status"] == "done" and d["done_at"] and d["due"] == "2026-08-20"
    assert _fields(d["activity"])[0] == ("status", "inbox", "done")
    assert d["id"] not in {x["id"] for x in repo.list_tasks(conn)}
    assert d["id"] in {x["id"] for x in repo.list_tasks(conn, include_closed=True)}


# ------------------------------------------- start date / deferral (#87)

def test_starts_is_a_field_like_due(conn: sqlite3.Connection) -> None:
    """Set, change and clear, each writing its own activity row."""
    t = repo.create_task(conn, "Renew car insurance", due="2026-10-15", starts="2026-10-01")
    assert t["starts"] == "2026-10-01"
    changed = repo.set_starts(conn, t["id"], "2026-09-20", actor="me")
    assert changed["starts"] == "2026-09-20"
    assert ("starts", "2026-10-01", "2026-09-20") in _fields(changed["activity"])
    cleared = repo.set_starts(conn, t["id"], None, actor="me")
    assert cleared["starts"] is None
    assert ("starts", "2026-09-20", None) in _fields(cleared["activity"])
    # "" clears it too — the same contract due has
    assert repo.update_task(conn, t["id"], starts="2026-11-01")["starts"] == "2026-11-01"
    assert repo.update_task(conn, t["id"], starts="")["starts"] is None
    # and the repo layer takes ISO only; phrases are resolved at the edges
    with pytest.raises(repo.ValidationError, match="starts must be an ISO date"):
        repo.create_task(conn, "Bad", starts="next friday")


def test_deferred_hidden_from_lists_but_never_from_tree_or_search(
    conn: sqlite3.Connection, frozen: None
) -> None:
    awake = repo.create_task(conn, "Awake task", status="todo", due="2026-08-18")
    past = repo.create_task(conn, "Started already", status="todo", starts="2026-08-16")
    today_ = repo.create_task(conn, "Starts today", status="todo", starts="2026-08-17")
    asleep = repo.create_task(conn, "Book boiler service", status="todo",
                              due="2026-09-26", starts="2026-09-06")

    def titles(**kw) -> set[str]:
        return {t["title"] for t in repo.list_tasks(conn, **kw)}

    # default: everything whose start day has arrived (today counts), nothing else
    assert titles() == {"Awake task", "Started already", "Starts today"}
    assert titles(deferred="only") == {"Book boiler service"}
    assert titles(deferred="all") == {
        "Awake task", "Started already", "Starts today", "Book boiler service",
    }
    # the Board and Today are projections of the same function, so they inherit it
    board = repo.board(conn)
    assert asleep["id"] not in {t["id"] for c in board["columns"].values() for t in c}
    assert asleep["id"] not in {
        t["id"] for g in repo.today_view(conn)["due"] for t in g["items"]
    }
    # …but the Tree and search read the table directly and keep showing it
    assert asleep["id"] in {n["id"] for n in repo.tree(conn)}
    assert asleep["id"] in {h["id"] for h in repo.search(conn, "boiler")}
    assert repo.get_task(conn, asleep["id"])["starts"] == "2026-09-06"
    assert awake["id"] and past["id"] and today_["id"]  # created, ids handed back

    # `include_closed` means "hide nothing", so it lifts this gate too — a
    # total taken with it must not quietly omit the sleeping tasks
    assert titles(include_closed=True) == {
        "Awake task", "Started already", "Starts today", "Book boiler service",
    }
    # …unless the caller was explicit, which still wins
    assert titles(include_closed=True, deferred="hide") == {
        "Awake task", "Started already", "Starts today",
    }

    with pytest.raises(repo.ValidationError, match="deferred must be"):
        repo.list_tasks(conn, deferred="sometimes")


def test_deferred_intersects_with_a_status_filter(conn: sqlite3.Connection, frozen: None) -> None:
    repo.create_task(conn, "Sleeping todo", status="todo", starts="2026-09-06")
    repo.create_task(conn, "Sleeping doing", status="doing", starts="2026-09-06")
    repo.create_task(conn, "Awake doing", status="doing")
    got = repo.list_tasks(conn, status=["doing"], deferred="only")
    assert [t["title"] for t in got] == ["Sleeping doing"]


def test_updated_before_is_a_strict_stale_boundary(conn: sqlite3.Connection) -> None:
    """#101: ``updated_before`` lists tasks last touched strictly before the
    boundary day — touched ON the boundary (or today) never appears — and any
    later write moves a task out of the window."""
    with repo.use_clock(lambda: datetime(2026, 7, 1, 9, 0, 0).astimezone()):
        old = repo.create_task(conn, "Dormant", status="todo")
    with repo.use_clock(lambda: datetime(2026, 7, 18, 9, 0, 0).astimezone()):
        repo.create_task(conn, "Touched on the boundary", status="todo")
    with repo.use_clock(lambda: datetime(2026, 8, 17, 9, 0, 0).astimezone()):
        repo.create_task(conn, "Touched today", status="todo")

        def titles(**kw) -> set[str]:
            return {t["title"] for t in repo.list_tasks(conn, **kw)}

        # boundary 2026-07-18 = "untouched > 30 days" seen from the anchor
        assert titles(updated_before="2026-07-18") == {"Dormant"}
        assert titles(updated_before="2026-07-01") == set()   # touched ON the boundary: not yet stale
        # composes with the other filters like any WHERE clause
        assert titles(updated_before="2026-07-18", status=["todo"]) == {"Dormant"}
        assert titles(updated_before="2026-07-18", status=["doing"]) == set()
        # ANY write is a touch — the task leaves the window the moment it moves
        repo.set_priority(conn, old["id"], "high", actor="x")
        assert titles(updated_before="2026-07-18") == set()
    with pytest.raises(repo.ValidationError):
        repo.list_tasks(conn, updated_before="someday")


def test_plan_my_day_rules(conn: sqlite3.Connection, frozen: None) -> None:
    """#89: planning appends to the day's ordered plan (activity-logged,
    ``plan_order`` itself never logged), snoozing to a future day un-plans,
    planning wakes a deferred task, and ``plan_reorder`` takes the whole
    permutation or refuses."""
    t = "2026-08-17"
    a = repo.create_task(conn, "Alpha", status="todo", due=t)
    b = repo.create_task(conn, "Beta", status="inbox")
    c = repo.create_task(conn, "Gamma", status="todo", starts="2026-09-01")

    a = repo.plan_task(conn, a["id"], t, actor="me")
    b = repo.plan_task(conn, b["id"], t, actor="me")
    assert (a["planned_on"], a["plan_order"]) == (t, 1)
    assert b["plan_order"] == 2
    assert ("planned_on", None, t) in _fields(a["activity"])
    assert "plan_order" not in {f[0] for f in _fields(a["activity"])}

    # snoozing to a future day un-plans — Later means "not today"
    a = repo.set_starts(conn, a["id"], "2026-09-01", actor="me")
    assert a["planned_on"] is None and a["plan_order"] is None
    assert ("planned_on", t, None) in _fields(a["activity"])

    # planning a deferred task wakes it — the gate is moot once you commit
    c = repo.plan_task(conn, c["id"], t, actor="me")
    assert c["starts"] is None and c["plan_order"] == 3
    assert ("starts", "2026-09-01", None) in _fields(c["activity"])

    # unplanning clears the order too
    c = repo.plan_task(conn, c["id"], None, actor="me")
    assert c["planned_on"] is None and c["plan_order"] is None

    # reorder: a permutation of every task planned today, or a refusal
    c = repo.plan_task(conn, c["id"], t, actor="me")
    assert repo.plan_reorder(conn, [c["id"], b["id"]]) == {"planned": 2}
    view = repo.today_view(conn)
    assert [x["title"] for x in view["plan"]["items"]] == ["Gamma", "Beta"]
    with pytest.raises(repo.ValidationError):
        repo.plan_reorder(conn, [b["id"]])
    with pytest.raises(repo.ValidationError):
        repo.plan_reorder(conn, [b["id"], b["id"]])

    # done planned items stay in the plan group and count as progress; a task
    # planned today leaves the due bucket (it lives in the plan instead)
    repo.done(conn, b["id"], actor="me")
    d = repo.create_task(conn, "Delta", status="todo", due=t)
    repo.plan_task(conn, d["id"], t, actor="me")
    view = repo.today_view(conn)
    assert (view["plan"]["done"], view["plan"]["total"]) == (1, 3)
    due_titles = {x["title"] for g in view["due"] for x in g["items"]}
    assert "Delta" not in due_titles
    with pytest.raises(repo.ValidationError):
        repo.plan_task(conn, d["id"], "someday")


def test_plan_candidates_and_the_seeded_plan(conn: sqlite3.Connection, seeded: dict, frozen: None) -> None:
    """#89 on the fixture: the seed plans the two inbox tasks for the anchor
    day and leaves one task planned the day before — the candidate wearing
    the "planned yesterday" note; already-planned and deferred tasks are
    never offered."""
    view = repo.today_view(conn)
    assert [x["title"] for x in view["plan"]["items"]] == [
        "Look into a standing desk", "Try the new bakery"]
    assert (view["plan"]["done"], view["plan"]["total"]) == (0, 2)
    cands = repo.plan_candidates(conn)
    titles = [x["title"] for x in cands]
    tap = next(x for x in cands if x["title"] == "Fix leaking tap")
    assert tap["planned_on"] == "2026-08-16"          # planned yesterday, unfinished
    assert "Look into a standing desk" not in titles   # already planned today
    assert "Compare phone plans" in titles             # inbox, future due — still a candidate
    assert "Book boiler service" not in titles         # deferred (#87) — not actionable
    # planned YESTERDAY ≠ planned today: the tap stays in the due groups too
    due_titles = {x["title"] for g in view["due"] for x in g["items"]}
    assert "Fix leaking tap" in due_titles


def test_recurrence_roll_leaves_starts_alone(conn: sqlite3.Connection, frozen: None) -> None:
    """A snoozed recurring task wakes on its start day and rolls normally after
    — the gate never chases the due date (see ``repo.done``)."""
    t = repo.create_task(conn, "Pay water bill", status="todo",
                         due="2026-08-20", recurrence="monthly", starts="2026-08-19")
    rolled = repo.done(conn, t["id"], actor="me")
    assert rolled["due"] == "2026-09-20"
    assert rolled["starts"] == "2026-08-19"          # untouched by the roll
    assert "starts" not in {a["field"] for a in rolled["activity"]}
    # once that day arrives the task is back in the working views for good
    with repo.use_clock(lambda: datetime(2026, 8, 19, 9, 0, 0).astimezone()):
        assert t["id"] in {x["id"] for x in repo.list_tasks(conn)}


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


def test_last_comment_follows_thread_order_not_max_id(conn: sqlite3.Connection) -> None:
    """A historical import (``add_comment(..., ts=...)`` — the path the Notion
    importer and ``Mirror._apply_comments`` use) can land a newer id with an
    older ts. ``list_tasks``' ``last_comment`` (via ``_enrich_list``) must
    follow thread order (``ts, id``, the same ordering ``list_comments``
    uses) — not a bare ``MAX(id)``."""

    def _ts_at(dt: datetime) -> str:
        with repo.use_clock(lambda: dt.astimezone()):
            return repo.now_iso()

    t_early = _ts_at(datetime(2026, 8, 17, 9, 0, 0))
    t_mid = _ts_at(datetime(2026, 8, 17, 9, 30, 0))

    t = repo.create_task(conn, "Talk")
    repo.add_comment(conn, t["id"], "early", ts=t_early)  # id=1, ts=t_early
    with repo.use_clock(lambda: datetime(2026, 8, 17, 10, 0, 0).astimezone()):
        repo.add_comment(conn, t["id"], "latest by time", author="b")  # id=2, ts=t_late
    # Historical import lands after "latest by time" in id order, but its ts
    # sits between the other two — this is the newer-id/older-ts case.
    repo.add_comment(conn, t["id"], "historical mid", ts=t_mid)  # id=3, ts=t_mid

    thread = repo.list_comments(conn, t["id"])
    assert [c["body"] for c in thread] == ["early", "historical mid", "latest by time"]

    items = repo.list_tasks(conn)
    item = next(i for i in items if i["id"] == t["id"])
    assert item["last_comment"]["body"] == "latest by time"


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


# ----------------------------------------------------------------- bulk

def test_bulk_update_applies_to_every_id(conn: sqlite3.Connection) -> None:
    ids = [repo.create_task(conn, f"T{n}")["id"] for n in range(3)]
    results = repo.bulk_update(conn, ids, actor="me", status="doing")
    assert [r["id"] for r in results] == ids
    assert all(r["ok"] for r in results)
    assert {r["task"]["status"] for r in results} == {"doing"}
    # the same activity trail a one-by-one edit would leave
    assert _fields(repo.get_task(conn, ids[0])["activity"])[0] == ("status", "inbox", "doing")


def test_bulk_update_reports_the_failed_id_and_applies_the_rest(conn: sqlite3.Connection) -> None:
    good = [repo.create_task(conn, f"T{n}")["id"] for n in range(2)]
    results = repo.bulk_update(conn, [good[0], 4242, good[1]], status="todo")
    assert [(r["id"], r["ok"]) for r in results] == [(good[0], True), (4242, False), (good[1], True)]
    assert results[1]["error"]["code"] == "not_found"
    # the bad id in the middle does NOT stop the batch
    assert [repo.get_task(conn, i)["status"] for i in good] == ["todo", "todo"]


def test_bulk_update_surfaces_a_validation_error_per_id(conn: sqlite3.Connection) -> None:
    ids = [repo.create_task(conn, f"T{n}")["id"] for n in range(2)]
    results = repo.bulk_update(conn, ids, due="not-a-date")
    assert [r["ok"] for r in results] == [False, False]
    assert {r["error"]["code"] for r in results} == {"validation_error"}


def test_bulk_complete_rolls_recurring_and_closes_the_rest(conn: sqlite3.Connection) -> None:
    rolling = repo.create_task(conn, "Weekly", recurrence="weekly", due="2026-08-31", status="todo")["id"]
    oneoff = repo.create_task(conn, "One-off", due="2026-08-31", status="todo")["id"]
    results = repo.bulk_update(conn, [rolling, oneoff], actor="me", complete=True)
    assert all(r["ok"] for r in results)
    # the recurring task rolls and stays open; the plain one closes — exactly
    # what the row select's `complete` does per task (#54)
    assert results[0]["task"]["due"] == "2026-09-07"
    assert results[0]["task"]["status"] == "todo"
    assert results[1]["task"]["status"] == "done" and results[1]["task"]["done_at"]


def test_bulk_update_collapses_duplicate_ids(conn: sqlite3.Connection) -> None:
    rolling = repo.create_task(conn, "Weekly", recurrence="weekly", due="2026-08-31")["id"]
    results = repo.bulk_update(conn, [rolling, rolling, rolling], complete=True)
    assert [r["id"] for r in results] == [rolling]
    assert repo.get_task(conn, rolling)["due"] == "2026-09-07"    # rolled once, not three times


# ------------------------------------------------------------ done journal (#102)


def _at(y: int, mo: int, d: int, h: int = 9, mi: int = 0):
    return repo.use_clock(lambda: datetime(y, mo, d, h, mi, 0).astimezone())


def test_done_window_is_local_midnight_and_newest_first(conn: sqlite3.Connection, seeded: dict) -> None:
    """#102 — ``done_from`` / ``done_to`` bound the closing day at local
    midnight (the ``done_on`` rule), a window flips the order to newest
    closing first, and cancelling stamps the same closed-at column."""
    with _at(2026, 8, 16, 23, 59):
        repo.done(conn, seeded["library"])
    with _at(2026, 8, 17, 0, 0):
        repo.done(conn, seeded["callback"])
    with _at(2026, 8, 17, 12, 0):
        cancelled = repo.set_status(conn, seeded["inbox3"], "cancelled", actor="me")
    assert cancelled["done_at"].startswith("2026-08-17T12:00")
    closed = ["done", "cancelled"]
    day = repo.list_tasks(conn, status=closed, done_from="2026-08-17", done_to="2026-08-17")
    assert [t["id"] for t in day] == [seeded["inbox3"], seeded["callback"]]    # 23:59 the day before is out
    both = repo.list_tasks(conn, status=closed, done_from="2026-08-16", done_to="2026-08-17")
    # …then the 16th: the library book at 23:59, and the seed's two "yesterday" closings
    assert [t["id"] for t in both] == [seeded["inbox3"], seeded["callback"], seeded["library"], seeded["kettle"], seeded["lease"]]
    # the seed's own closed days (anchor−1, −2, −9): a week holds seven, the
    # week before starts with the drill — newest closing first throughout
    week = [t["title"] for t in repo.list_tasks(conn, status=closed, done_from="2026-08-11", done_to="2026-08-17")]
    assert week == [
        "Compare phone plans", "Call the plumber back", "Return library books",
        "Descale the kettle", "Send the lease renewal",
        "Fix the watering timezone bug", "Cancel the unused streaming plan",
    ]
    older = repo.list_tasks(conn, status=closed, done_to="2026-08-10")
    assert older[0]["title"] == "Return the borrowed drill"
    assert "Sell the old bikes" in [t["title"] for t in older]      # created cancelled → stamped too
    # reopening clears the stamp — a reopened task has no closing day
    assert repo.set_status(conn, seeded["inbox3"], "todo")["done_at"] is None
    with pytest.raises(repo.ValidationError):
        repo.list_tasks(conn, done_from="whenever")
