"""REST surface under ``/api/`` — shapes, status codes, the JSON error envelope."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.schema import SCHEMA_VERSION
from tests.fixtures.seed import seed_db


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    from app.webapp.server import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "seeded.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    seed_db(path)
    from app.webapp.server import create_app

    with TestClient(create_app()) as c:
        yield c


def test_version_reports_schema_2(client: TestClient) -> None:
    assert client.get("/api/version").json()["schema_version"] == SCHEMA_VERSION == 3


def test_story_02_over_http(client: TestClient) -> None:
    """add → add --parent → comment → tree → due → show (activity old → new)."""
    r = client.post("/api/tasks", json={"title": "Renew passport", "due": "2026-08-21"})
    assert r.status_code == 201
    t1 = r.json()
    assert t1["id"] == 1 and t1["due"] == "2026-08-21" and t1["status"] == "inbox"

    t2 = client.post("/api/tasks", json={"title": "Book appointment", "parent_id": 1}).json()
    assert t2["parent_id"] == 1 and t2["breadcrumb"] == [{"id": 1, "title": "Renew passport"}]

    c = client.post("/api/tasks/2/comments", json={"body": "called the office", "origin": "cli"})
    assert c.status_code == 201 and c.json()["origin"] == "cli"

    tree = client.get("/api/tasks/tree").json()["items"]
    assert tree[0]["title"] == "Renew passport"
    assert [n["title"] for n in tree[0]["children"]] == ["Book appointment"]

    p = client.patch("/api/tasks/2", json={"due": "2026-09-01"}, headers={"X-Actor": "cli-user"})
    assert p.status_code == 200 and p.json()["due"] == "2026-09-01"

    show = client.get("/api/tasks/2").json()
    assert show["comments"][0]["body"] == "called the office"
    top = show["activity"][0]
    assert (top["field"], top["old_value"], top["new_value"], top["actor"]) == (
        "due", None, "2026-09-01", "cli-user",
    )
    assert show["activity"][-1]["field"] == "created"
    act = client.get("/api/activity?task=2").json()["items"]
    assert [a["field"] for a in act] == ["due", "created"]


def test_error_envelope_is_consistent(client: TestClient) -> None:
    nf = client.get("/api/tasks/99")
    assert nf.status_code == 404 and nf.json() == {"error": {"code": "not_found", "message": "task 99 not found"}}
    ve = client.post("/api/tasks", json={"title": ""})
    assert ve.status_code == 422 and ve.json()["error"]["code"] == "validation_error"
    rv = client.post("/api/tasks", json={"nope": 1})
    assert rv.status_code == 422 and rv.json()["error"]["code"] == "validation_error"
    assert rv.json()["error"]["detail"][0]["loc"] == ["body", "title"]
    route = client.get("/api/does-not-exist")
    assert route.status_code == 404 and route.json()["error"]["code"] == "not_found"
    coding = client.post("/api/tasks", json={"title": "x", "type": "coding"})
    assert coding.status_code == 422 and "issue" in coding.json()["error"]["message"]
    bad_date = client.post("/api/tasks", json={"title": "x", "due": "friday"})
    assert bad_date.status_code == 422


def test_move_cycle_done_and_delete(client: TestClient) -> None:
    a = client.post("/api/tasks", json={"title": "A"}).json()["id"]
    b = client.post("/api/tasks", json={"title": "B", "parent_id": a}).json()["id"]
    cyc = client.post(f"/api/tasks/{a}/move", json={"parent_id": b})
    assert cyc.status_code == 409 and cyc.json()["error"]["code"] == "cycle"
    ok = client.post(f"/api/tasks/{b}/move", json={"parent_id": None})
    assert ok.status_code == 200 and ok.json()["parent_id"] is None
    # recurring done rolls; plain done closes
    r = client.post("/api/tasks", json={"title": "R", "recurrence": "monthly", "due": "2026-01-31"}).json()["id"]
    rolled = client.post(f"/api/tasks/{r}/done").json()
    assert rolled["due"] == "2026-02-28" and rolled["status"] == "inbox"
    d = client.post(f"/api/tasks/{b}/done", json={"actor": "x"}).json()
    assert d["status"] == "done" and d["done_at"]
    assert client.get("/api/tasks").json()["count"] == 2            # A + R (B done hidden)
    assert client.get("/api/tasks?include_closed=true").json()["count"] == 3
    assert client.get("/api/tasks?status=done").json()["count"] == 1
    assert client.delete(f"/api/tasks/{a}").json() == {"id": a, "deleted": 1}
    assert client.get(f"/api/tasks/{a}").status_code == 404


def test_list_filters_tree_and_search_on_seed(seeded: TestClient) -> None:
    items = seeded.get("/api/tasks?project=1&status=standby").json()["items"]
    assert [t["title"] for t in items] == ["Plant tomatoes", "Garden"]
    assert seeded.get("/api/tasks?parent=root").json()["count"] >= 8
    assert seeded.get("/api/tasks?parent=2").json()["count"] == 3
    assert seeded.get("/api/tasks?type=coding").json()["items"][0]["issue_ref"]["number"] == 12
    assert seeded.get("/api/tasks?status=todo,doing&due_from=2026-08-17&due_to=2026-08-19").json()["count"] >= 3
    assert seeded.get("/api/tasks?person=1").json()["count"] == 2  # Sam: quotes + plumber
    assert seeded.get("/api/tasks?limit=5").json()["count"] == 5
    sub = seeded.get("/api/tasks/tree?root=20").json()["items"]
    assert sub[0]["title"] == "Side project: garden-bot" and sub[0]["children"]
    s = seeded.get("/api/search?q=washer").json()
    assert s["count"] == 1 and s["items"][0]["matched_in"] == "comment"
    assert seeded.get("/api/search?q=").status_code == 422
    assert seeded.get("/api/tasks?q=balcony").json()["items"][0]["title"] == "Side project: garden-bot"


def test_links_issue_and_people(seeded: TestClient) -> None:
    t = seeded.post("/api/tasks", json={"title": "Linky"}).json()["id"]
    lk = seeded.post(f"/api/tasks/{t}/links", json={"url": "https://example.com", "kind": "web"})
    assert lk.status_code == 201
    assert seeded.get(f"/api/tasks/{t}/links").json()["items"][0]["url"] == "https://example.com"
    assert seeded.delete(f"/api/tasks/{t}/links/{lk.json()['id']}").json()["deleted"] == 1
    assert seeded.delete(f"/api/tasks/{t}/links/{lk.json()['id']}").status_code == 404

    iss = seeded.put(f"/api/tasks/{t}/issue", json={"repo": "example/repo", "number": 3})
    assert iss.status_code == 200 and iss.json()["type"] == "coding"
    assert seeded.patch(f"/api/tasks/{t}", json={"type": "task"}).status_code == 422
    assert seeded.delete(f"/api/tasks/{t}/issue").json()["type"] == "task"
    assert seeded.put(f"/api/tasks/{t}/issue", json={"repo": "r", "number": 0}).status_code == 422

    people = seeded.get("/api/people").json()
    assert people["count"] == 3 and people["items"][0]["name"] == "Alex Chen"
    p = seeded.post("/api/people", json={"name": "New Person"})
    assert p.status_code == 201
    pid = p.json()["id"]
    assert seeded.patch(f"/api/people/{pid}", json={"email": "n@example.com"}).json()["email"] == "n@example.com"
    assert seeded.get(f"/api/people/{pid}").json()["open_tasks"] == 0
    assert seeded.delete(f"/api/people/{pid}").json()["deleted"] == 1
    assert seeded.get(f"/api/people/{pid}").status_code == 404
