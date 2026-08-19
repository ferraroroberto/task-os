"""``tasks_repo.board`` / ``today_view`` — the Board and Today bucketing rules
(done-today boundary at local midnight, recurring first, overdue ordering) and
their routes."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    return seed(conn, ANCHOR)["ids"]


def _at(y: int, mo: int, d: int, h: int = 9, mi: int = 0):
    return repo.use_clock(lambda: datetime(y, mo, d, h, mi, 0).astimezone())


# ------------------------------------------------------------------ board


def test_board_buckets_open_statuses_and_hides_old_done(conn: sqlite3.Connection, seeded: dict) -> None:
    with _at(2026, 8, 17):
        b = repo.board(conn)
    assert b["today"] == "2026-08-17"
    assert list(b["columns"]) == ["inbox", "todo", "doing", "standby", "done"]
    for key in ("inbox", "todo", "doing", "standby"):
        assert b["columns"][key], key
        assert {t["status"] for t in b["columns"][key]} == {key}
    # the seed's done tasks were completed ~30 days ago → never in "Done today"
    assert b["columns"]["done"] == []
    # cancelled never shows anywhere
    assert not any(t["status"] == "cancelled" for col in b["columns"].values() for t in col)
    # enriched like list_tasks: root + last_comment present on a nested card
    quotes = next(t for t in b["columns"]["doing"] if t["id"] == seeded["quotes"])
    assert quotes["root"]["title"] == "Home renovation" and quotes["last_comment"]


def test_board_done_today_boundary_is_local_midnight(conn: sqlite3.Connection, seeded: dict) -> None:
    # done at 23:59 yesterday → not today; done at 00:00 today → today
    with _at(2026, 8, 16, 23, 59):
        repo.done(conn, seeded["library"])
    with _at(2026, 8, 17, 0, 0):
        repo.done(conn, seeded["callback"])
    with _at(2026, 8, 17, 12, 0):
        b = repo.board(conn)
    ids = [t["id"] for t in b["columns"]["done"]]
    assert ids == [seeded["callback"]]
    # the day rolls: tomorrow neither shows
    with _at(2026, 8, 18, 0, 1):
        assert repo.board(conn)["columns"]["done"] == []


def test_board_status_change_moves_the_card(conn: sqlite3.Connection, seeded: dict) -> None:
    with _at(2026, 8, 17):
        repo.set_status(conn, seeded["quotes"], "standby", actor="me")
        b = repo.board(conn)
    assert seeded["quotes"] in [t["id"] for t in b["columns"]["standby"]]
    assert seeded["quotes"] not in [t["id"] for t in b["columns"]["doing"]]
    act = repo.list_activity(conn, seeded["quotes"])[0]
    assert (act["field"], act["old_value"], act["new_value"]) == ("status", "doing", "standby")


def test_board_project_and_person_filters(conn: sqlite3.Connection, seeded: dict) -> None:
    with _at(2026, 8, 17):
        b = repo.board(conn, project=seeded["home"])
        every = [t for col in b["columns"].values() for t in col]
        assert every and all(t["root"] and t["root"]["id"] == seeded["home"] for t in every)
        people = repo.list_people(conn)
        sam = next(p for p in people if p["name"] == "Sam Rivera")["id"]
        b2 = repo.board(conn, person_id=sam)
        every2 = [t for col in b2["columns"].values() for t in col]
        assert every2 and all(t["person"]["id"] == sam for t in every2)


# ------------------------------------------------------------------ today


def _titles(groups: list[dict]) -> dict[str, list[str]]:
    return {(g["root"] or {}).get("title", "—"): [t["title"] for t in g["items"]] for g in groups}


def test_today_groups_by_root_recurring_first_overdue_first(conn: sqlite3.Connection, seeded: dict) -> None:
    with _at(2026, 8, 17):
        v = repo.today_view(conn)
    assert v["today"] == "2026-08-17"
    every = [t for g in v["due"] for t in g["items"]]
    assert every and all(t["due"] <= "2026-08-17" for t in every)
    assert all(t["status"] not in ("done", "cancelled") for t in every)
    # groups ordered by earliest due: Home renovation (fence −10d) first, the
    # loose group (library −3d) before Family admin (today) and Learning (today)
    order = [(g["root"] or {}).get("title", "—") for g in v["due"]]
    assert order.index("Home renovation") < order.index("—") < order.index("Family admin")
    groups = _titles(v["due"])
    # inside Family admin the recurring dentist comes before the non-recurring form
    fam = groups["Family admin"]
    assert fam.index("Dentist check-up") < fam.index("School enrolment forms")
    # inside Learning both today's items are recurring (weekly + daily) — both first
    assert groups["Learning"] == ["Vocabulary review", "Practice scales"]
    # overdue before today inside a group (Home renovation: fence −10, tap −4)
    assert groups["Home renovation"] == ["Repair fence", "Fix leaking tap"]
    assert v["counts"]["overdue"] == 3 and v["counts"]["today"] == 5
    # later this week: tomorrow … +7, never today or overdue
    week = [t for g in v["week"] for t in g["items"]]
    assert week and all("2026-08-17" < t["due"] <= "2026-08-24" for t in week)
    assert v["counts"]["week"] == len(week)


def test_today_done_on_recurring_rolls_and_leaves_the_bucket(conn: sqlite3.Connection, seeded: dict) -> None:
    with _at(2026, 8, 17):
        before = {t["id"] for g in repo.today_view(conn)["due"] for t in g["items"]}
        assert seeded["vocab"] in before
        rolled = repo.done(conn, seeded["vocab"])
        assert rolled["due"] == "2026-08-24" and rolled["status"] == "todo"
        after = repo.today_view(conn)
    assert seeded["vocab"] not in {t["id"] for g in after["due"] for t in g["items"]}
    assert seeded["vocab"] in {t["id"] for g in after["week"] for t in g["items"]}


# ------------------------------------------------------------------ routes


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "seeded.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db(path)
    c = dbmod.connect(path)
    seed(c)
    c.close()
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as tc:
        yield tc


def test_routes_shape(client: TestClient) -> None:
    b = client.get("/api/board").json()
    assert set(b["columns"]) == {"inbox", "todo", "doing", "standby", "done"}
    home = next(t for t in b["columns"]["doing"] if t["title"] == "Home renovation")
    filtered = client.get(f"/api/board?project={home['id']}").json()
    assert all(t["root"]["id"] == home["id"] for col in filtered["columns"].values() for t in col)
    t = client.get("/api/today").json()
    assert set(t) == {"today", "due", "week", "counts"}
    assert t["due"] and "root" in t["due"][0] and "items" in t["due"][0]
