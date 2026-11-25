"""The History feed: one person's own changes, newest first, by day then task, filterable by kind."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src import tasks_repo as repo
from src.tasks.history import classify, group_changes, history
from tests.conftest import write_test_config
from tests.tasks._support import _at

ME = ["me"]


def _task(conn: sqlite3.Connection, title: str) -> int:
    with _at(2026, 8, 16, 8):
        return repo.create_task(conn, title=title, actor="me")["id"]


def test_classify_names_each_kind() -> None:
    assert classify("due", "2026-08-17", "2026-08-20") == "dates"
    assert classify("starts", None, "2026-08-20") == "dates"
    assert classify("status", "todo", "done") == "closed"
    assert classify("status", "done", "todo") == "closed"
    assert classify("status", "todo", "waiting") == "status"
    assert classify("done", "2026-08-17", "2026-08-24") == "closed"
    assert classify("priority", "normal", "high") == "priority"
    assert classify("parent", None, "3") == "moved"
    assert classify("comment", None, "hi") == "comment"
    assert classify("title", "a", "b") == "other"


def test_today_newest_first_grouped_per_task(conn: sqlite3.Connection) -> None:
    a, b = _task(conn, "Fix the gate"), _task(conn, "Book the dentist")
    with _at(2026, 8, 17, 9):
        repo.update_task(conn, a, actor="me", due="2026-08-20")
    with _at(2026, 8, 17, 10):
        repo.update_task(conn, a, actor="me", priority="high")
    with _at(2026, 8, 17, 11):
        repo.update_task(conn, b, actor="me", status="done")
    with _at(2026, 8, 17, 12):
        repo.add_comment(conn, a, "called the smith", author="me")
        feed = history(conn, ME)
    assert feed["from"] == feed["to"] == "2026-08-17"
    [day] = feed["days"]
    assert day["day"] == "2026-08-17" and day["count"] == 4
    # a, then b, then a again: only *consecutive* changes fold together
    assert [(g["task_id"], [e["kind"] for e in g["entries"]]) for g in day["groups"]] == [
        (a, ["comment"]), (b, ["closed"]), (a, ["priority", "dates"]),
    ]
    assert day["groups"][0]["title"] == "Fix the gate"
    assert feed["counts"]["all"] == 4 and feed["counts"]["dates"] == 1
    # yesterday's creations are older than the window
    assert feed["older"] is True


def test_the_kind_filter_narrows_and_regroups(conn: sqlite3.Connection) -> None:
    a = _task(conn, "Fix the gate")
    with _at(2026, 8, 17, 9):
        repo.update_task(conn, a, actor="me", due="2026-08-20", priority="high")
    with _at(2026, 8, 17, 10):
        feed = history(conn, ME, kind="dates")
        everything = history(conn, ME, kind="all")
    assert feed["kind"] == "dates"
    assert [e["field"] for g in feed["days"][0]["groups"] for e in g["entries"]] == ["due"]
    # the counts describe the window, not the filtered list
    assert feed["counts"] == everything["counts"]
    assert sum(len(g["entries"]) for g in everything["days"][0]["groups"]) == 2


def test_only_the_actors_own_changes(conn: sqlite3.Connection) -> None:
    a = _task(conn, "Fix the gate")
    with _at(2026, 8, 17, 9):
        repo.update_task(conn, a, actor="md", title="Fix the garden gate")
        repo.add_comment(conn, a, "from the mirror", author="md")
        feed = history(conn, ME)
    assert feed["days"] == [] and feed["counts"]["all"] == 0


def test_an_empty_day_and_the_window(conn: sqlite3.Connection) -> None:
    with _at(2026, 8, 17, 9):
        assert history(conn, ME) == {
            "from": "2026-08-17", "to": "2026-08-17", "actors": ME, "kind": "all",
            "counts": {"all": 0, "dates": 0, "closed": 0, "status": 0, "priority": 0,
                       "moved": 0, "comment": 0, "other": 0},
            "older": False, "days": [],
        }
    a = _task(conn, "Fix the gate")
    with _at(2026, 8, 17, 9):
        repo.update_task(conn, a, actor="me", priority="high")
        two = history(conn, ME, day_from="2026-08-16")
    assert [d["day"] for d in two["days"]] == ["2026-08-17", "2026-08-16"]
    assert two["older"] is False


def test_a_moved_task_names_its_parents(conn: sqlite3.Connection) -> None:
    home, a = _task(conn, "Home"), _task(conn, "Fix the gate")
    with _at(2026, 8, 17, 9):
        repo.move(conn, a, home, actor="me")
        [entry] = history(conn, ME, kind="moved")["days"][0]["groups"][0]["entries"]
    assert entry["new_label"] == "Home" and entry["old_label"] is None


@pytest.mark.parametrize("args", [
    {"kind": "nope"}, {"day_from": "yesterday"}, {"day_from": "2026-08-18", "day_to": "2026-08-17"},
    {"day_from": "2026-01-01", "day_to": "2026-08-17"},
])
def test_a_bad_window_or_kind_is_refused(conn: sqlite3.Connection, args: dict) -> None:
    with pytest.raises(repo.ValidationError):
        history(conn, ME, **args)


def test_group_changes_starts_a_day_per_local_day() -> None:
    rows = [
        {"id": 2, "task_id": 1, "ts": "2026-08-17T00:10:00+02:00", "actor": "me", "field": "title",
         "old_value": "a", "new_value": "b", "title": "b", "status": "todo"},
        {"id": 1, "task_id": 1, "ts": "2026-08-16T23:50:00+02:00", "actor": "me", "field": "title",
         "old_value": "", "new_value": "a", "title": "b", "status": "todo"},
    ]
    assert [d["day"] for d in group_changes(rows)] == ["2026-08-17", "2026-08-16"]


def test_the_endpoint_reads_the_viewers_own_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_test_config(tmp_path / "config.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["your_name"] = "Ada Example"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        tid = c.post("/api/tasks", json={"title": "Water the plants"}).json()["id"]
        c.patch(f"/api/tasks/{tid}", json={"priority": "high"})
        c.patch(f"/api/tasks/{tid}", json={"priority": "low"}, headers={"X-Actor": "someone"})
        feed = c.get("/api/history").json()
        assert feed["actors"] == ["Ada Example", "me"]
        [group] = feed["days"][0]["groups"]
        assert [e["field"] for e in group["entries"]] == ["priority", "created"]
        assert c.get("/api/history", params={"kind": "priority"}).json()["counts"]["priority"] == 1
        bad = c.get("/api/history", params={"kind": "nope"})
        assert bad.status_code == 422 and bad.json()["error"]["code"]
