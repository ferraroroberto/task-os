"""The time tracker (#457): ``src/time_repo.py`` rules and the ``/api/time`` routes.

Every test runs on a temp DB with the process clock pinned (and advanced by
hand where a timer has to run). The people are the sample config's
placeholders, ``p1`` and ``p2`` — never anyone real.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import clock
from src import db as dbmod
from src import time_repo as repo
from src.config import IMPLICIT_TIME_PERSON, load_config
from src.tasks_repo import NotFound, ValidationError
from tests.conftest import write_test_config

TZ = timezone(timedelta(hours=2))
T0 = datetime(2026, 10, 17, 9, 0, tzinfo=TZ)
PEOPLE = ("p1", "p2")


@pytest.fixture
def clk() -> Iterator[dict[str, datetime]]:
    """The pinned clock; tests move it with ``clk["now"] += timedelta(...)``."""
    holder = {"now": T0}
    with clock.use_clock(lambda: holder["now"]):
        yield holder


@pytest.fixture
def conn(tmp_path: Path, clk: dict[str, datetime]) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "tasks.db"
    dbmod.init_db(path)
    c = dbmod.connect(path)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clk: dict[str, datetime]) -> Iterator[TestClient]:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def cat(conn: sqlite3.Connection, slug: str, area: str = "home") -> int:
    cid = repo.category_by_slug(conn, area, slug)
    assert cid is not None
    return cid


def entries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM time_entries ORDER BY id").fetchall()


def timers(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT person FROM time_timers ORDER BY person")]


# ------------------------------------------------------------------ timers


def test_one_timer_per_person_and_two_people_at_once(conn: sqlite3.Connection) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    repo.start_timer(conn, "p2", cat(conn, "laundry"), people=PEOPLE)
    assert timers(conn) == ["p1", "p2"]
    with pytest.raises(repo.TimerRunning):
        repo.start_timer(conn, "p1", cat(conn, "cleaning"), people=PEOPLE)
    # the refused start changed nothing
    assert [t["category_slug"] for t in repo.list_timers(conn) if t["person"] == "p1"] == ["cooking"]
    assert entries(conn) == []


def test_unknown_person_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValidationError):
        repo.start_timer(conn, "nobody", cat(conn, "cooking"), people=PEOPLE)
    with pytest.raises(ValidationError):
        repo.create_entry(conn, person="nobody", category_id=cat(conn, "cooking"), day="2026-10-17",
                          minutes=10, people=PEOPLE)


def test_stop_saves_the_rounded_elapsed_time_with_its_range(conn: sqlite3.Connection, clk: dict) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(minutes=89, seconds=40)
    entry = repo.stop_timer(conn, "p1")
    assert entry["minutes"] == 90 and entry["day"] == "2026-10-17"
    assert entry["started_at"] == "2026-10-17T09:00:00+02:00"
    assert entry["ended_at"] == "2026-10-17T10:30:00+02:00"   # start + minutes, always
    assert timers(conn) == []


def test_a_short_timer_saves_one_minute_and_a_forgotten_one_at_most_a_day(conn: sqlite3.Connection, clk: dict) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(seconds=10)
    assert repo.stop_timer(conn, "p1")["minutes"] == 1
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(hours=30)
    assert repo.stop_timer(conn, "p1")["minutes"] == repo.MAX_MINUTES


def test_the_corrected_minutes_are_what_is_saved(conn: sqlite3.Connection, clk: dict) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(hours=5)
    with pytest.raises(ValidationError):
        repo.stop_timer(conn, "p1", minutes=repo.MAX_MINUTES + 1)
    assert timers(conn) == ["p1"]                      # a refused correction stops nothing
    entry = repo.stop_timer(conn, "p1", minutes=45)
    assert entry["minutes"] == 45 and entry["ended_at"] == "2026-10-17T09:45:00+02:00"


def test_a_double_stop_saves_once(conn: sqlite3.Connection, clk: dict) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(minutes=20)
    repo.stop_timer(conn, "p1")
    with pytest.raises(repo.NoTimer):
        repo.stop_timer(conn, "p1")
    assert len(entries(conn)) == 1


def test_a_stop_interrupted_between_its_two_steps_leaves_the_timer_running(
    conn: sqlite3.Connection, clk: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delete and the insert are one transaction: an insert that fails
    after the timer row is gone rolls the delete back, so nothing is lost and
    nothing is saved twice on the retry."""
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(minutes=20)

    def boom(*args: Any, **kwargs: Any) -> int:
        assert conn.execute("SELECT COUNT(*) FROM time_timers").fetchone()[0] == 0   # step one ran
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repo, "_insert_entry", boom)
    with pytest.raises(sqlite3.OperationalError):
        repo.stop_timer(conn, "p1")
    assert timers(conn) == ["p1"] and entries(conn) == []
    monkeypatch.undo()
    assert repo.stop_timer(conn, "p1")["minutes"] == 20
    assert len(entries(conn)) == 1 and timers(conn) == []


def test_two_connections_stopping_the_same_timer_save_one_entry(tmp_path: Path, clk: dict) -> None:
    """Two devices: the second stop, on its own connection, finds no timer."""
    path = tmp_path / "tasks.db"
    dbmod.init_db(path)
    a, b = dbmod.connect(path), dbmod.connect(path)
    try:
        repo.start_timer(a, "p1", repo.category_by_slug(a, "home", "cooking"), people=PEOPLE)  # type: ignore[arg-type]
        clk["now"] += timedelta(minutes=5)
        repo.stop_timer(a, "p1")
        with pytest.raises(repo.NoTimer):
            repo.stop_timer(b, "p1")
        assert b.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 1
    finally:
        a.close()
        b.close()


def test_switch_stops_and_starts_in_one_call(conn: sqlite3.Connection, clk: dict) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    clk["now"] += timedelta(minutes=25)
    out = repo.start_timer(conn, "p1", cat(conn, "laundry"), people=PEOPLE, switch=True)
    assert out["entry"]["category_slug"] == "cooking" and out["entry"]["minutes"] == 25
    assert out["timer"]["category_slug"] == "laundry"
    assert out["timer"]["started_at"] == "2026-10-17T09:25:00+02:00"
    assert timers(conn) == ["p1"] and len(entries(conn)) == 1


def test_discard_saves_nothing(conn: sqlite3.Connection, clk: dict) -> None:
    repo.start_timer(conn, "p1", cat(conn, "cooking"), people=PEOPLE)
    repo.discard_timer(conn, "p1")
    assert timers(conn) == [] and entries(conn) == []
    with pytest.raises(repo.NoTimer):
        repo.discard_timer(conn, "p1")


def test_an_entry_crossing_midnight_counts_on_its_start_day(conn: sqlite3.Connection, clk: dict) -> None:
    clk["now"] = datetime(2026, 10, 16, 23, 30, tzinfo=TZ)
    repo.start_timer(conn, "p1", cat(conn, "cleaning"), people=PEOPLE)
    clk["now"] = datetime(2026, 10, 17, 0, 30, tzinfo=TZ)
    entry = repo.stop_timer(conn, "p1")
    assert entry["day"] == "2026-10-16" and entry["minutes"] == 60
    assert entry["ended_at"] == "2026-10-17T00:30:00+02:00"
    assert repo.summary(conn, people=PEOPLE, period="today")["total_minutes"] == 0
    assert repo.summary(conn, people=PEOPLE, period="7")["total_minutes"] == 60


# ----------------------------------------------------------------- entries


def test_a_manual_entry_derives_its_end_and_refuses_the_future(conn: sqlite3.Connection) -> None:
    entry = repo.create_entry(conn, person="p2", category_id=cat(conn, "shopping"), day="2026-10-16",
                              minutes=90, start="17:10", note="  groceries  ", people=PEOPLE)
    assert entry["started_at"] == "2026-10-16T17:10:00+02:00"
    assert entry["ended_at"] == "2026-10-16T18:40:00+02:00"
    assert entry["note"] == "groceries"
    with pytest.raises(ValidationError):    # a future day (the server's today is 2026-10-17)
        repo.create_entry(conn, person="p2", category_id=cat(conn, "shopping"), day="2026-10-18",
                          minutes=10, people=PEOPLE)
    with pytest.raises(ValidationError):    # later today than now (09:00)
        repo.create_entry(conn, person="p2", category_id=cat(conn, "shopping"), day="2026-10-17",
                          minutes=10, start="11:00", people=PEOPLE)
    with pytest.raises(ValidationError):
        repo.create_entry(conn, person="p2", category_id=cat(conn, "shopping"), day="2026-10-17",
                          minutes=0, people=PEOPLE)
    with pytest.raises(ValidationError):
        repo.create_entry(conn, person="p2", category_id=cat(conn, "shopping"), day="2026-10-17",
                          minutes=10, note="x" * 141, people=PEOPLE)


def test_moving_an_entry_between_people_moves_exactly_its_minutes(conn: sqlite3.Connection) -> None:
    cooking = cat(conn, "cooking")
    repo.create_entry(conn, person="p1", category_id=cooking, day="2026-10-17", minutes=30, start="07:00", people=PEOPLE)
    moved = repo.create_entry(conn, person="p1", category_id=cooking, day="2026-10-17", minutes=45,
                              start="08:00", people=PEOPLE)
    repo.create_entry(conn, person="p2", category_id=cooking, day="2026-10-17", minutes=20, people=PEOPLE)
    before = repo.summary(conn, people=PEOPLE, period="today")["by_person"]
    repo.update_entry(conn, moved["id"], person="p2", people=PEOPLE)
    after = repo.summary(conn, people=PEOPLE, period="today")["by_person"]
    assert before == {"p1": 75, "p2": 20}
    assert after == {"p1": before["p1"] - 45, "p2": before["p2"] + 45}


def test_editing_a_clocked_entry_moves_its_end(conn: sqlite3.Connection, clk: dict) -> None:
    entry = repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-16",
                              minutes=30, start="18:00", people=PEOPLE)
    e = repo.update_entry(conn, entry["id"], minutes=50, people=PEOPLE)
    assert (e["started_at"], e["ended_at"]) == ("2026-10-16T18:00:00+02:00", "2026-10-16T18:50:00+02:00")
    e = repo.update_entry(conn, entry["id"], start="19:15", people=PEOPLE)
    assert (e["started_at"], e["ended_at"]) == ("2026-10-16T19:15:00+02:00", "2026-10-16T20:05:00+02:00")
    e = repo.update_entry(conn, entry["id"], day="2026-10-15", category_id=cat(conn, "laundry"),
                          note="moved", people=PEOPLE)
    assert e["day"] == "2026-10-15" and e["started_at"] == "2026-10-15T19:15:00+02:00"
    assert e["category_slug"] == "laundry" and e["note"] == "moved"


def test_a_duration_only_entry_never_gains_a_clock_range(conn: sqlite3.Connection) -> None:
    entry = repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-16",
                              minutes=30, people=PEOPLE)
    assert entry["started_at"] is None and entry["ended_at"] is None
    e = repo.update_entry(conn, entry["id"], minutes=40, day="2026-10-15", people=PEOPLE)
    assert e["minutes"] == 40 and e["started_at"] is None and e["ended_at"] is None
    with pytest.raises(ValidationError):
        repo.update_entry(conn, entry["id"], start="10:00", people=PEOPLE)
    assert repo.get_entry(conn, entry["id"])["started_at"] is None


def test_editing_or_deleting_an_entry_deleted_meanwhile_changes_nothing(conn: sqlite3.Connection) -> None:
    entry = repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-16",
                              minutes=30, people=PEOPLE)
    repo.delete_entry(conn, entry["id"])
    with pytest.raises(NotFound):
        repo.update_entry(conn, entry["id"], minutes=10, people=PEOPLE)
    with pytest.raises(NotFound):
        repo.delete_entry(conn, entry["id"])
    assert entries(conn) == []


def test_history_lists_newest_first_and_filters(conn: sqlite3.Connection) -> None:
    names = {"p1": "Person 1", "p2": "Person 2"}
    repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-15", minutes=10, people=PEOPLE)
    repo.create_entry(conn, person="p2", category_id=cat(conn, "laundry"), day="2026-10-17", minutes=20,
                      note="towels", people=PEOPLE)
    repo.create_entry(conn, person="p1", category_id=cat(conn, "general", "work"), day="2026-10-16",
                      minutes=30, people=PEOPLE)
    page = repo.list_entries(conn, names=names)
    assert [e["day"] for e in page["items"]] == ["2026-10-17", "2026-10-16", "2026-10-15"] and page["total"] == 3
    assert [e["note"] for e in repo.list_entries(conn, names=names, q="towel")["items"]] == ["towels"]
    assert repo.list_entries(conn, names=names, q="work")["total"] == 1          # area name
    assert repo.list_entries(conn, names=names, q="person 2")["total"] == 1      # person name
    assert repo.list_entries(conn, names=names, q="10-15")["total"] == 1         # date
    assert [e["day"] for e in repo.list_entries(conn, names=names, limit=1, offset=1)["items"]] == ["2026-10-16"]


def test_recent_is_the_last_five_distinct_categories(conn: sqlite3.Connection, clk: dict) -> None:
    for slug in ("cooking", "laundry", "cooking", "cleaning", "shopping", "home", "planning"):
        clk["now"] += timedelta(minutes=1)
        repo.create_entry(conn, person="p1", category_id=cat(conn, slug), day="2026-10-17", minutes=1, people=PEOPLE)
    repo.create_entry(conn, person="p2", category_id=cat(conn, "other"), day="2026-10-17", minutes=1, people=PEOPLE)
    slugs = {c["id"]: c["slug"] for a in repo.list_areas(conn) for c in a["categories"]}
    assert [slugs[i] for i in repo.recent_categories(conn, "p1")] == [
        "planning", "home", "shopping", "cleaning", "cooking"]


# ------------------------------------------------------ areas / categories


def test_an_archived_category_cannot_be_picked_but_still_counts(conn: sqlite3.Connection) -> None:
    laundry = cat(conn, "laundry")
    entry = repo.create_entry(conn, person="p1", category_id=laundry, day="2026-10-17", minutes=30, people=PEOPLE)
    repo.update_category(conn, laundry, archived=True)
    with pytest.raises(ValidationError):
        repo.start_timer(conn, "p1", laundry, people=PEOPLE)
    with pytest.raises(ValidationError):
        repo.create_entry(conn, person="p1", category_id=laundry, day="2026-10-17", minutes=5, people=PEOPLE)
    s = repo.summary(conn, people=PEOPLE, period="today")
    assert s["total_minutes"] == 30 and s["by_category"][0]["slug"] == "laundry"
    assert repo.list_entries(conn, names={})["items"][0]["id"] == entry["id"]
    # the entry is still editable in place (its category is not changed)
    assert repo.update_entry(conn, entry["id"], minutes=35, people=PEOPLE)["minutes"] == 35
    assert laundry not in repo.recent_categories(conn, "p1")
    flagged = {c["slug"]: c["archived"] for c in repo.list_areas(conn)[0]["categories"]}
    assert flagged["laundry"] is True and flagged["cooking"] is False


def test_an_archived_area_blocks_its_categories(conn: sqlite3.Connection) -> None:
    work = next(a for a in repo.list_areas(conn) if a["slug"] == "work")
    repo.update_area(conn, work["id"], archived=True)
    with pytest.raises(ValidationError):
        repo.start_timer(conn, "p1", cat(conn, "general", "work"), people=PEOPLE)
    repo.update_area(conn, work["id"], archived=False)
    repo.start_timer(conn, "p1", cat(conn, "general", "work"), people=PEOPLE)


def test_areas_and_categories_are_added_renamed_moved_and_reordered(conn: sqlite3.Connection) -> None:
    hobby = repo.create_area(conn, "Hobbies")
    assert hobby["slug"] == "hobbies" and hobby["position"] == 4
    with pytest.raises(repo.SlugTaken):
        repo.create_area(conn, "hobbies")
    guitar = repo.create_category(conn, hobby["id"], "Guitar", "practice")
    assert (guitar["slug"], guitar["position"]) == ("guitar", 0)
    repo.update_category(conn, guitar["id"], name="Guitar practice")
    # move a Home category into Hobbies: its entries follow, Home closes the gap
    other = cat(conn, "other")
    repo.create_entry(conn, person="p1", category_id=other, day="2026-10-17", minutes=10, people=PEOPLE)
    repo.update_category(conn, other, area_id=hobby["id"], position=0)
    areas = {a["slug"]: a for a in repo.list_areas(conn)}
    assert [c["slug"] for c in areas["hobbies"]["categories"]] == ["other", "guitar"]
    assert [c["position"] for c in areas["home"]["categories"]] == list(range(9))
    assert repo.summary(conn, people=PEOPLE, period="today", area="hobbies")["total_minutes"] == 10
    # reorder areas
    repo.update_area(conn, hobby["id"], position=0, name="Hobby")
    assert [a["slug"] for a in repo.list_areas(conn)] == ["hobbies", "home", "work", "personal", "health"]
    assert repo.list_areas(conn)[0]["name"] == "Hobby"
    # a move onto a slug the target area already uses is refused
    repo.create_category(conn, hobby["id"], "General")
    with pytest.raises(repo.SlugTaken):
        repo.update_category(conn, cat(conn, "general", "work"), area_id=hobby["id"])


def test_a_category_subtitle_is_set_changed_and_cleared(conn: sqlite3.Connection) -> None:
    home = next(a for a in repo.list_areas(conn) if a["slug"] == "home")
    made = repo.create_category(conn, home["id"], "Garden", "  mowing, weeding  ")
    assert made["hint"] == "mowing, weeding"
    assert repo.update_category(conn, made["id"], hint="mowing")["hint"] == "mowing"
    # a rename alone leaves the subtitle; an empty one clears it
    assert repo.update_category(conn, made["id"], name="Garden work")["hint"] == "mowing"
    assert repo.update_category(conn, made["id"], hint="   ")["hint"] == ""
    with pytest.raises(ValidationError):
        repo.update_category(conn, made["id"], hint="x" * 81)
    with pytest.raises(ValidationError):
        repo.create_category(conn, home["id"], "Pets", "x" * 81)
    assert repo.update_category(conn, made["id"], hint="x" * 80)["hint"] == "x" * 80


def _home(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return next(a for a in repo.list_areas(conn) if a["slug"] == "home")["categories"]


def test_only_a_category_nothing_points_at_can_be_deleted(conn: sqlite3.Connection) -> None:
    home = next(a for a in repo.list_areas(conn) if a["slug"] == "home")
    mistake = repo.create_category(conn, home["id"], "Made by mistake")
    assert mistake["in_use"] is False
    cooking, laundry = cat(conn, "cooking"), cat(conn, "laundry")
    repo.create_entry(conn, person="p1", category_id=cooking, day="2026-10-17", minutes=10, people=PEOPLE)
    repo.start_timer(conn, "p2", laundry, people=PEOPLE)
    flagged = {c["slug"]: c["in_use"] for c in _home(conn)}
    assert flagged["cooking"] is True and flagged["laundry"] is True and flagged["made-by-mistake"] is False
    # an entry or a running timer blocks it, archived or not
    repo.update_category(conn, cooking, archived=True)
    for used in (cooking, laundry):
        with pytest.raises(repo.CategoryInUse):
            repo.delete_category(conn, used)
    # the empty one goes, and the area closes the gap it left
    repo.update_category(conn, mistake["id"], position=0)
    repo.delete_category(conn, mistake["id"])
    assert "made-by-mistake" not in {c["slug"] for c in _home(conn)}
    assert [c["position"] for c in _home(conn)] == list(range(len(_home(conn))))
    with pytest.raises(NotFound):
        repo.delete_category(conn, mistake["id"])
    # once the timer is discarded, laundry has nothing pointing at it
    repo.discard_timer(conn, "p2")
    assert repo.update_category(conn, laundry, name="Laundry")["in_use"] is False
    repo.delete_category(conn, laundry)
    assert repo.category_by_slug(conn, "home", "laundry") is None


# ------------------------------------------------------------------ totals


def test_summary_per_person_area_category_and_coverage(conn: sqlite3.Connection) -> None:
    def add(person: str, slug: str, day: str, minutes: int, area: str = "home") -> None:
        repo.create_entry(conn, person=person, category_id=cat(conn, slug, area), day=day, minutes=minutes, people=PEOPLE)

    add("p1", "cooking", "2026-10-17", 60)
    add("p1", "cooking", "2026-10-15", 30)
    add("p2", "laundry", "2026-10-17", 40)
    add("p2", "general", "2026-10-16", 100, area="work")
    add("p1", "cooking", "2026-09-01", 15)                 # outside 7 / 30 days
    s = repo.summary(conn, people=PEOPLE, period="7", area="home")
    assert s["total_minutes"] == 130 and s["by_person"] == {"p1": 90, "p2": 40}
    assert s["days_logged"] == {"p1": 2, "p2": 1} and s["span_days"] == 7 and s["from"] == "2026-10-11"
    assert [(c["slug"], c["by_person"]) for c in s["by_category"]] == [
        ("cooking", {"p1": 90, "p2": 0}), ("laundry", {"p1": 0, "p2": 40})]
    everything = repo.summary(conn, people=PEOPLE, period="all")
    assert everything["total_minutes"] == 245
    assert everything["span_days"] == 47                    # 2026-09-01 .. 2026-10-17
    assert [a["slug"] for a in everything["by_area"]] == ["home", "work"]
    mine = repo.summary(conn, people=PEOPLE, period="7", person="p2")
    assert mine["by_person"] == {"p2": 140} and mine["total_minutes"] == 140
    with pytest.raises(ValidationError):
        repo.summary(conn, people=PEOPLE, period="14")


def test_totals_count_configured_people_only(conn: sqlite3.Connection) -> None:
    repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-17", minutes=10, people=PEOPLE)
    repo.create_entry(conn, person="p2", category_id=cat(conn, "cooking"), day="2026-10-17", minutes=20, people=PEOPLE)
    # p2 is later dropped from the config: History keeps the row, Totals stop counting it
    s = repo.summary(conn, people=("p1",), period="today")
    assert s["total_minutes"] == 10 and s["by_person"] == {"p1": 10}
    assert repo.list_entries(conn, names={})["total"] == 2


def test_the_csv_holds_exactly_what_the_totals_sum(conn: sqlite3.Connection) -> None:
    names = {"p1": "Person 1", "p2": "Person 2"}
    repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-17", minutes=60,
                      start="07:00", note="soup, bread", people=PEOPLE)
    repo.create_entry(conn, person="p2", category_id=cat(conn, "laundry"), day="2026-10-12", minutes=40, people=PEOPLE)
    repo.create_entry(conn, person="p2", category_id=cat(conn, "general", "work"), day="2026-10-16", minutes=99, people=PEOPLE)
    repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-01", minutes=5, people=PEOPLE)
    start = repo.period_start("7", clock.today())
    text = repo.entries_csv(conn, people=PEOPLE, names=names, from_day=start, area="home")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert tuple(rows[0].keys()) == repo.CSV_COLUMNS
    assert sum(int(r["minutes"]) for r in rows) == repo.summary(conn, people=PEOPLE, period="7", area="home")["total_minutes"]
    assert [(r["day"], r["start"], r["end"], r["person_name"], r["note"]) for r in rows] == [
        ("2026-10-12", "", "", "Person 2", ""), ("2026-10-17", "07:00", "08:00", "Person 1", "soup, bread")]


# ----------------------------------------------------------------- guesses


def test_the_other_guess_stays_hidden_until_yours_is_in(conn: sqlite3.Connection) -> None:
    repo.set_guess(conn, "p2", 60, people=PEOPLE)
    hidden = repo.get_guesses(conn, "p1", people=PEOPLE)
    assert hidden["mine"] is None and hidden["others"] is None
    shown = repo.set_guess(conn, "p1", 55, people=PEOPLE)
    assert shown["mine"]["pct"] == 55 and shown["others"]["p2"]["pct"] == 60
    assert repo.set_guess(conn, "p1", 50, people=PEOPLE)["mine"]["pct"] == 50     # "Change"
    for bad in (-1, 101):
        with pytest.raises(ValidationError):
            repo.set_guess(conn, "p1", bad, people=PEOPLE)


# ------------------------------------------------------------------ config


def test_time_config_people_and_the_implicit_owner(tmp_path: Path) -> None:
    cfg = load_config(write_test_config(tmp_path / "sample.json"))
    assert cfg.time.ids == ("p1", "p2") and cfg.time.compare_area == "home" and cfg.time.long_timer_minutes == 180
    raw = json.loads((tmp_path / "sample.json").read_text(encoding="utf-8"))
    raw.pop("time")
    (tmp_path / "none.json").write_text(json.dumps(raw), encoding="utf-8")
    assert load_config(tmp_path / "none.json").time.people == (IMPLICIT_TIME_PERSON,)
    raw["time"] = {"people": [{"id": "a", "name": "A"}, {"id": "a", "name": "Dup"}, {"name": "no id"}, "junk"]}
    (tmp_path / "odd.json").write_text(json.dumps(raw), encoding="utf-8")
    odd = load_config(tmp_path / "odd.json").time
    assert odd.ids == ("a",) and odd.name_of("a") == "A" and odd.name_of("gone") == "gone"


# --------------------------------------------------------------------- API


def test_api_meta_takes_today_from_the_server(client: TestClient) -> None:
    meta = client.get("/api/time/meta").json()
    assert meta["today"] == "2026-10-17" and meta["now"] == "2026-10-17T09:00:00+02:00"
    assert [p["id"] for p in meta["people"]] == ["p1", "p2"] and meta["compare_area"] == "home"
    assert [a["slug"] for a in meta["areas"]] == ["home", "work", "personal", "health"]
    assert len(meta["areas"][0]["categories"]) == 10


def test_api_timer_flow_and_its_error_codes(client: TestClient, clk: dict) -> None:
    home = client.get("/api/time/meta").json()["areas"][0]["categories"]
    cooking, laundry = home[3]["id"], home[5]["id"]
    r = client.post("/api/time/timers", json={"person": "p1", "category_id": cooking})
    assert r.status_code == 201 and r.json()["entry"] is None
    assert client.post("/api/time/timers", json={"person": "p2", "category_id": laundry}).status_code == 201
    again = client.post("/api/time/timers", json={"person": "p1", "category_id": laundry})
    assert again.status_code == 409 and again.json()["error"]["code"] == "timer_running"
    clk["now"] += timedelta(minutes=15)
    switched = client.post("/api/time/timers", json={"person": "p1", "category_id": laundry, "switch": True})
    assert switched.status_code == 201 and switched.json()["entry"]["minutes"] == 15
    running = client.get("/api/time/timers").json()
    assert {t["person"] for t in running["items"]} == {"p1", "p2"} and running["now"].startswith("2026-10-17T09:15")
    clk["now"] += timedelta(minutes=10)
    stopped = client.post("/api/time/timers/p1/stop", json={})
    assert stopped.status_code == 200 and stopped.json()["minutes"] == 10
    twice = client.post("/api/time/timers/p1/stop")
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "no_timer"
    assert client.delete("/api/time/timers/p2").status_code == 204
    assert client.get("/api/time/entries").json()["total"] == 2
    assert client.get("/api/time/recent", params={"person": "p1"}).json()["category_ids"] == [laundry, cooking]


def test_api_entries_edit_delete_summary_csv_guesses(client: TestClient) -> None:
    cooking = client.get("/api/time/meta").json()["areas"][0]["categories"][3]["id"]
    r = client.post("/api/time/entries", json={"person": "p1", "category_id": cooking, "day": "2026-10-17",
                                               "minutes": 30, "start": "08:00"})
    assert r.status_code == 201 and r.json()["ended_at"] == "2026-10-17T08:30:00+02:00"
    eid = r.json()["id"]
    future = client.post("/api/time/entries", json={"person": "p1", "category_id": cooking,
                                                    "day": "2026-10-18", "minutes": 5})
    assert future.status_code == 422 and future.json()["error"]["code"] == "validation_error"
    assert client.patch(f"/api/time/entries/{eid}", json={"person": "p2"}).json()["person"] == "p2"
    s = client.get("/api/time/summary", params={"period": "today", "area": "home"}).json()
    assert s["by_person"] == {"p1": 0, "p2": 30}
    text = client.get("/api/time/entries.csv", params={"period": "today", "area": "home"})
    assert text.headers["content-type"].startswith("text/csv")
    assert text.text.splitlines()[1].startswith("2026-10-17,08:00,08:30,30,p2,Person 2,Home,Cooking and dishes")
    assert client.put("/api/time/guesses/p1", json={"pct": 40}).json()["others"] == {}
    assert client.get("/api/time/guesses/p2").json()["others"] is None
    assert client.delete(f"/api/time/entries/{eid}").status_code == 204
    gone = client.patch(f"/api/time/entries/{eid}", json={"minutes": 10})
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "not_found"


SRC = "usage:app-launcher:2026-10-14"


def _push(client: TestClient, source_id: str = SRC, **over: Any) -> Any:
    cid = client.get("/api/time/meta").json()["areas"][0]["categories"][3]["id"]
    body = {"person": "p1", "category_id": cid, "day": "2026-10-14", "minutes": 42, **over}
    return client.put(f"/api/time/entries/by-source/{source_id}", json=body)


def test_api_put_by_source_creates_then_replaces_then_is_a_no_op(client: TestClient, clk: dict) -> None:
    first = _push(client, note="  screen time ")
    assert first.status_code == 201
    entry = first.json()
    assert entry["source_id"] == SRC and entry["minutes"] == 42 and entry["note"] == "screen time"
    assert entry["started_at"] is None and entry["ended_at"] is None     # duration-only

    clk["now"] += timedelta(hours=1)
    changed = _push(client, minutes=50)
    assert changed.status_code == 200 and changed.json()["id"] == entry["id"]
    assert changed.json()["minutes"] == 50 and changed.json()["note"] == ""   # a replace, not a merge
    assert changed.json()["created_at"] == entry["created_at"] and changed.json()["updated_at"] != entry["updated_at"]

    clk["now"] += timedelta(hours=1)
    again = _push(client, minutes=50)
    assert again.status_code == 200 and again.json() == changed.json()    # updated_at untouched too
    assert client.get("/api/time/entries").json()["total"] == 1


def test_api_put_by_source_replaces_every_field_it_carries(client: TestClient) -> None:
    other = client.get("/api/time/meta").json()["areas"][0]["categories"][5]["id"]
    entry = _push(client).json()
    moved = _push(client, person="p2", category_id=other, day="2026-10-13").json()
    assert (moved["id"], moved["person"], moved["category_id"], moved["day"]) == (entry["id"], "p2", other, "2026-10-13")


def test_api_put_by_source_validates_like_a_hand_entry(client: TestClient) -> None:
    meta = client.get("/api/time/meta").json()
    laundry = next(c for c in meta["areas"][0]["categories"] if c["slug"] == "laundry")["id"]
    client.patch(f"/api/time/categories/{laundry}", json={"archived": True})
    refused = {
        "unknown person": _push(client, person="nobody"),
        "no minutes": _push(client, minutes=0),
        "over a day": _push(client, minutes=1441),
        "future day": _push(client, day="2026-10-18"),
        "bad day": _push(client, day="yesterday"),
        "archived category": _push(client, category_id=laundry),
        "long note": _push(client, note="x" * 141),
        "a start": _push(client, start="09:00"),
        "no namespace": _push(client, source_id="2026-10-14"),
        "upper-case namespace": _push(client, source_id="Usage:x"),
        "empty id": _push(client, source_id="usage:"),
        "id too long": _push(client, source_id="usage:" + "a" * 121),
    }
    for what, r in refused.items():
        assert r.status_code == 422, what
        assert r.json()["error"]["code"] == "validation_error", what
    assert _push(client, category_id=9999).status_code == 404    # as POST /entries: no such category
    assert client.get("/api/time/entries").json()["total"] == 0


def test_api_delete_by_source_is_204_then_404(client: TestClient) -> None:
    _push(client)
    assert client.delete(f"/api/time/entries/by-source/{SRC}").status_code == 204
    repeat = client.delete(f"/api/time/entries/by-source/{SRC}")
    assert repeat.status_code == 404 and repeat.json()["error"]["code"] == "not_found"
    assert client.delete("/api/time/entries/by-source/usage:never-sent").status_code == 404
    assert client.delete("/api/time/entries/by-source/no-namespace").status_code == 422
    assert _push(client).status_code == 201     # a delete frees the key: the next push recreates


def test_by_source_leaves_entries_without_a_source_untouched(conn: sqlite3.Connection) -> None:
    hand = repo.create_entry(conn, person="p1", category_id=cat(conn, "cooking"), day="2026-10-14",
                             minutes=42, start="08:00", people=PEOPLE)
    repo.import_rows(conn, [{"source_id": "protodoc1", "person": "p1", "category_id": cat(conn, "cooking"),
                             "day": "2026-10-14", "minutes": 42, "note": "", "created_at": "2026-10-01T00:00:00+02:00"}], [])
    before = [dict(r) for r in entries(conn)]
    pushed, created = repo.upsert_by_source(conn, SRC, person="p1", category_id=cat(conn, "cooking"),
                                            day="2026-10-14", minutes=42, people=PEOPLE)
    assert created and pushed["id"] not in {r["id"] for r in before}
    repo.upsert_by_source(conn, SRC, person="p1", category_id=cat(conn, "cooking"), day="2026-10-14",
                          minutes=60, people=PEOPLE)
    repo.delete_by_source(conn, SRC)
    assert [dict(r) for r in entries(conn)] == before
    assert repo.get_entry(conn, hand["id"])["started_at"] == hand["started_at"]
    with pytest.raises(ValidationError):    # the importer's ids are not in the pushed key space
        repo.delete_by_source(conn, "protodoc1")
    with pytest.raises(NotFound):
        repo.delete_by_source(conn, SRC)


def test_api_area_and_category_admin(client: TestClient) -> None:
    area = client.post("/api/time/areas", json={"name": "Study"})
    assert area.status_code == 201 and area.json()["slug"] == "study"
    dup = client.post("/api/time/areas", json={"name": "study"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "slug_taken"
    c = client.post("/api/time/categories", json={"area_id": area.json()["id"], "name": "Reading"})
    assert c.status_code == 201
    archived = client.patch(f"/api/time/categories/{c.json()['id']}", json={"archived": True})
    assert archived.json()["archived"] is True
    assert client.patch(f"/api/time/areas/{area.json()['id']}", json={"name": "Learning"}).json()["name"] == "Learning"
    hinted = client.patch(f"/api/time/categories/{c.json()['id']}", json={"hint": "books"})
    assert hinted.json()["hint"] == "books"
    too_long = client.patch(f"/api/time/categories/{c.json()['id']}", json={"hint": "x" * 81})
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "validation_error"
    # delete: an empty category goes (204), a used one is refused with its own code, a gone one is 404
    assert client.delete(f"/api/time/categories/{c.json()['id']}").status_code == 204
    assert client.delete(f"/api/time/categories/{c.json()['id']}").status_code == 404
    used = client.get("/api/time/meta").json()["areas"][0]["categories"][0]
    day = client.get("/api/time/meta").json()["today"]
    client.post("/api/time/entries", json={"person": "p1", "category_id": used["id"], "day": day, "minutes": 5})
    assert next(x for x in client.get("/api/time/meta").json()["areas"][0]["categories"]
                if x["id"] == used["id"])["in_use"] is True
    refused = client.delete(f"/api/time/categories/{used['id']}")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "category_in_use"


def test_api_time_routes_are_gated_off_loopback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 50000)) as c:
        assert c.get("/api/time/meta").status_code == 401
        assert c.post("/api/time/timers", json={"person": "p1", "category_id": 1}).status_code == 401
        body = {"person": "p1", "category_id": 1, "day": "2026-10-14", "minutes": 5}
        assert c.put(f"/api/time/entries/by-source/{SRC}", json=body).status_code == 401
        assert c.delete(f"/api/time/entries/by-source/{SRC}").status_code == 401
