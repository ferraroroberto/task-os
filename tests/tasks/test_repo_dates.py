"""``src/tasks_repo.py`` â€” recurrence (cadence, fixed-day anchors, every-N
intervals) and the start date's deferral rule."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from src import tasks_repo as repo
from tests.tasks._support import (
    _fields,
)

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


# ------------------------------------------- every-N intervals (#229)

def test_done_rolls_every_seven_weeks_on_saturday(conn: sqlite3.Connection, frozen: None) -> None:
    """The story: a Saturday clothes-moth treatment, ticked Monday, lands 7 weeks on — a Saturday."""
    t = repo.create_task(conn, "Treat clothes against moths", status="todo", due="2026-08-15",
                         recurrence="weekly", recurrence_anchor="sat", recurrence_interval=7)
    assert t["recurrence_interval"] == 7
    rolled = repo.done(conn, t["id"], actor="me")
    assert rolled["due"] == "2026-10-03"                        # Sat 15 Aug + 7 weeks
    assert ("due", "2026-08-15", "2026-10-03") in _fields(rolled["activity"])
    again = repo.done(conn, t["id"], actor="me")
    assert again["due"] == "2026-11-21"                         # and 7 more, still a Saturday


def test_interval_is_stored_canonically(conn: sqlite3.Connection) -> None:
    assert repo.create_task(conn, "A", recurrence="daily", recurrence_interval="3")["recurrence_interval"] == 3
    assert repo.create_task(conn, "B", recurrence="daily", recurrence_interval=1)["recurrence_interval"] is None
    t = repo.create_task(conn, "C", recurrence="weekly", recurrence_interval=2)
    # an explicit 1 is "no interval": a change, logged as one
    cleared = repo.update_task(conn, t["id"], recurrence_interval=1, actor="me")
    assert cleared["recurrence_interval"] is None
    assert ("recurrence_interval", "2", None) in _fields(cleared["activity"])
    # setting the value already stored is no change at all
    before = len(cleared["activity"])
    assert len(repo.update_task(conn, t["id"], recurrence_interval=None)["activity"]) == before


@pytest.mark.parametrize(
    ("cadence", "interval"),
    [("weekly", 0), ("weekly", -2), ("monthly", 1000), ("daily", "seven"), (None, 7)],
)
def test_bad_interval_is_rejected(conn: sqlite3.Connection, cadence: str | None, interval: object) -> None:
    with pytest.raises(repo.ValidationError):
        repo.create_task(conn, "Nope", recurrence=cadence, recurrence_interval=interval)
    t = repo.create_task(conn, "Nope too", recurrence=cadence)
    with pytest.raises(repo.ValidationError):
        repo.update_task(conn, t["id"], recurrence_interval=interval)


def test_the_interval_follows_the_cadence_and_leaves_with_it(conn: sqlite3.Connection) -> None:
    """Every cadence takes an interval, so switching keeps it; clearing Repeat drops it, logged."""
    t = repo.create_task(conn, "Moths", recurrence="weekly", recurrence_anchor="sat", recurrence_interval=7)
    switched = repo.update_task(conn, t["id"], recurrence="quarterly", actor="me")
    assert (switched["recurrence_anchor"], switched["recurrence_interval"]) == (None, 7)
    gone = repo.update_task(conn, t["id"], recurrence=None, actor="me")
    assert gone["recurrence_interval"] is None
    assert ("recurrence_interval", "7", None) in _fields(gone["activity"])
    # both halves in one PATCH validate as a pair
    both = repo.update_task(conn, t["id"], recurrence="monthly", recurrence_interval=2)
    assert (both["recurrence"], both["recurrence_interval"]) == ("monthly", 2)


def test_done_non_recurring_closes(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "One-off", due="2026-08-20")
    d = repo.done(conn, t["id"], actor="me")
    assert d["status"] == "done" and d["done_at"] and d["due"] == "2026-08-20"
    assert _fields(d["activity"])[0] == ("status", "todo", "done")
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
    repo.create_task(conn, "Sleeping standby", status="standby", starts="2026-09-06")
    repo.create_task(conn, "Awake standby", status="standby")
    got = repo.list_tasks(conn, status=["standby"], deferred="only")
    assert [t["title"] for t in got] == ["Sleeping standby"]


def test_a_done_task_with_an_open_blocker_stays_in_the_done_journal(
    conn: sqlite3.Connection, frozen: None
) -> None:
    """#263 — ``blocked`` used to default to ``"hide"`` even for a
    closed-status / done-window query, so a task completed while its blocker
    was still open vanished from the done journal and the Board's Done-today
    column. A closed-only view now defaults it (and ``deferred``) to
    ``"all"`` instead, the same as ``include_closed``."""
    blocker = repo.create_task(conn, "Still open", status="todo")
    task = repo.create_task(conn, "Finished but blocked", status="todo")
    repo.add_blocker(conn, task["id"], blocker["id"])
    done = repo.done(conn, task["id"])
    assert done["status"] == "done"
    assert task["id"] in {t["id"] for t in repo.list_tasks(conn, status=["done"])}
    assert task["id"] in {
        t["id"] for t in repo.list_tasks(conn, status=["done"], done_on="2026-08-17")
    }
    assert task["id"] in {t["id"] for t in repo.board(conn)["columns"]["done"]}
    # an explicit override still wins over the closed-view default
    assert task["id"] not in {
        t["id"] for t in repo.list_tasks(conn, status=["done"], blocked="hide")
    }


def test_a_done_task_with_a_future_starts_stays_in_the_done_journal(
    conn: sqlite3.Connection, frozen: None
) -> None:
    """Same #263 slip on the ``deferred`` gate — a task closed before its
    ``starts`` day arrived must not vanish from the closed-status views."""
    task = repo.create_task(conn, "Finished early", status="todo", starts="2026-09-06")
    repo.done(conn, task["id"])
    assert task["id"] in {t["id"] for t in repo.list_tasks(conn, status=["done"])}
    assert task["id"] not in {
        t["id"] for t in repo.list_tasks(conn, status=["done"], deferred="hide")
    }


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
        with pytest.raises(repo.ValidationError):
            titles(updated_before="2026-07-18", status=["doing"])
        # ANY write is a touch — the task leaves the window the moment it moves
        repo.set_priority(conn, old["id"], "high", actor="x")
        assert titles(updated_before="2026-07-18") == set()
    with pytest.raises(repo.ValidationError):
        repo.list_tasks(conn, updated_before="someday")


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
