"""REST surface under ``/api/`` — shapes, status codes, the JSON error envelope."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.schema import SCHEMA_VERSION
from tests.fixtures.seed import PINNED_ANCHOR, seed_db


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    path = tmp_path / "seeded.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    seed_db(path, PINNED_ANCHOR)   # absolute-date assertions below are written against the pin
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def test_version_reports_schema(client: TestClient) -> None:
    assert client.get("/api/version").json()["schema_version"] == SCHEMA_VERSION == 8


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
    # natural phrases resolve at the API (Step 4); an unknown one is still a 422
    ok_date = client.post("/api/tasks", json={"title": "x", "due": "friday"})
    assert ok_date.status_code == 201 and len(ok_date.json()["due"]) == 10
    bad_date = client.post("/api/tasks", json={"title": "x", "due": "someday"})
    assert bad_date.status_code == 422 and bad_date.json()["error"]["code"] == "validation_error"


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
    tasks = next(g for g in s["groups"] if g["kind"] == "tasks")
    assert tasks["count"] == 1 and tasks["hits"][0]["matched_in"] == "comment"
    assert [g["kind"] for g in s["groups"]] == ["tasks", "folders", "emails", "issues"]
    assert seeded.get("/api/search?q=").status_code == 422
    assert seeded.get("/api/tasks?q=balcony").json()["items"][0]["title"] == "Side project: garden-bot"


def test_updated_before_lists_the_dormant_task(seeded: TestClient) -> None:
    """#101 over HTTP: the stale windows' `updated_before` is a plain date the
    client computed — the seed's dormant task (last touched anchor−45) is the
    one hit at the 30-day boundary and gone at 60."""
    items = seeded.get("/api/tasks?updated_before=2026-07-18").json()["items"]  # anchor−30
    assert [t["title"] for t in items] == ["Sort the garage shelves"]
    assert seeded.get("/api/tasks?updated_before=2026-06-18").json()["count"] == 0  # anchor−60
    # composes with the rest of the filter card
    assert seeded.get("/api/tasks?updated_before=2026-07-18&project=1").json()["count"] == 1
    assert seeded.get("/api/tasks?updated_before=2026-07-18&person=1").json()["count"] == 0
    assert seeded.get("/api/tasks?updated_before=someday").status_code == 422


def test_plan_my_day_over_http(client: TestClient) -> None:
    """#89 over HTTP: `planned_on` takes the same phrases `due` does, the
    /api/today plan group is server-ordered, candidates exclude the planned,
    and reorder takes the full permutation or 422s."""
    t = date.today().isoformat()
    a = client.post("/api/tasks", json={"title": "One", "status": "todo", "due": "today"}).json()
    b = client.post("/api/tasks", json={"title": "Two", "status": "inbox"}).json()
    r = client.patch(f"/api/tasks/{a['id']}", json={"planned_on": "today"})
    assert r.status_code == 200
    assert (r.json()["planned_on"], r.json()["plan_order"]) == (t, 1)
    client.patch(f"/api/tasks/{b['id']}", json={"planned_on": "today"})
    view = client.get("/api/today").json()
    assert [x["title"] for x in view["plan"]["items"]] == ["One", "Two"]
    assert (view["plan"]["done"], view["plan"]["total"]) == (0, 2)
    assert client.get("/api/plan/candidates").json()["count"] == 0

    r = client.post("/api/plan/reorder", json={"ids": [b["id"], a["id"]]})
    assert r.status_code == 200 and r.json() == {"planned": 2}
    view = client.get("/api/today").json()
    assert [x["title"] for x in view["plan"]["items"]] == ["Two", "One"]
    assert client.post("/api/plan/reorder", json={"ids": [a["id"]]}).status_code == 422
    assert client.patch(f"/api/tasks/{a['id']}", json={"planned_on": "someday"}).status_code == 422

    # unplanning with null puts the due-today task back among the candidates
    assert client.patch(f"/api/tasks/{a['id']}", json={"planned_on": None}).json()["planned_on"] is None
    cands = client.get("/api/plan/candidates").json()
    assert [x["title"] for x in cands["items"]] == ["One"]


def test_starts_accepts_phrases_and_the_deferred_filter(client: TestClient) -> None:
    """#87 over HTTP: `starts` takes the same natural phrases `due` does, and
    `status=deferred` is the one URL spelling of "show me the sleeping ones"."""
    # Phrases resolve against the real clock here (the route has no `today`
    # pin), so the expected values are computed, never hardcoded — a literal
    # would start failing the day it went past.
    soon = date.today() + timedelta(days=30)
    later = date.today() + timedelta(days=60)
    created = client.post("/api/tasks", json={
        "title": "Renew insurance", "due": "in 60 days", "starts": "in 30 days", "status": "todo",
    })
    assert created.status_code == 201
    t = created.json()
    assert (t["due"], t["starts"]) == (later.isoformat(), soon.isoformat())

    # sleeping: out of the default list, out of the Board and Today, in the
    # Tree, and back under the Deferred filter
    assert client.get("/api/tasks").json()["count"] == 0
    board = client.get("/api/board").json()["columns"]
    assert all(not col for col in board.values())
    assert client.get("/api/today").json()["counts"] == {"overdue": 0, "today": 0, "week": 0}
    assert client.get("/api/tasks/tree").json()["items"][0]["id"] == t["id"]
    only = client.get("/api/tasks?status=deferred").json()
    assert only["count"] == 1 and only["items"][0]["starts"] == soon.isoformat()
    # it intersects with a real status rather than replacing it
    assert client.get("/api/tasks?status=deferred,todo").json()["count"] == 1
    assert client.get("/api/tasks?status=deferred,doing").json()["count"] == 0

    # clearing wakes it, and every change is in the log
    assert client.patch(f"/api/tasks/{t['id']}", json={"starts": ""}).json()["starts"] is None
    assert client.get("/api/tasks").json()["count"] == 1
    assert client.get("/api/tasks?status=deferred").json()["count"] == 0
    fields = [a["field"] for a in client.get(f"/api/tasks/{t['id']}").json()["activity"]]
    assert "starts" in fields

    # an unparseable phrase is a 422, never a silently unset date
    assert client.patch(f"/api/tasks/{t['id']}", json={"starts": "someday"}).status_code == 422


def test_parse_splits_both_dates(client: TestClient) -> None:
    r = client.post("/api/parse", json={
        "text": "renew insurance due oct 15 starts oct 1", "today": "2026-08-30",
    }).json()
    assert r["title"] == "renew insurance"
    assert (r["due"], r["due_phrase"]) == ("2026-10-15", "due oct 15")
    assert (r["starts"], r["starts_phrase"]) == ("2026-10-01", "starts oct 1")


def test_links_issue_and_people(seeded: TestClient) -> None:
    t = seeded.post("/api/tasks", json={"title": "Linky"}).json()["id"]
    lk = seeded.post(f"/api/tasks/{t}/links", json={"url": "https://example.com", "kind": "web"})
    assert lk.status_code == 201
    assert seeded.get(f"/api/tasks/{t}/links").json()["items"][0]["url"] == "https://example.com"
    assert seeded.delete(f"/api/tasks/{t}/links/{lk.json()['id']}").json()["deleted"] == 1
    assert seeded.delete(f"/api/tasks/{t}/links/{lk.json()['id']}").status_code == 404

    # ai kind (#77): accepted, and the FIRST ai link surfaces on every list
    # summary as ai_url/ai_label — the row's bot chip reads it from there.
    assert seeded.post(f"/api/tasks/{t}/links", json={"url": "x", "kind": "bogus"}).status_code == 422
    ai = seeded.post(
        f"/api/tasks/{t}/links",
        json={"url": "https://claude.ai/code/session_01TestOnly", "label": "drift chat", "kind": "ai"},
    )
    assert ai.status_code == 201 and ai.json()["kind"] == "ai"
    seeded.post(f"/api/tasks/{t}/links", json={"url": "https://chatgpt.com/c/2", "kind": "ai"})
    linky = next(i for i in seeded.get("/api/tasks?q=Linky").json()["items"] if i["id"] == t)
    assert linky["ai_url"] == "https://claude.ai/code/session_01TestOnly"
    assert linky["ai_label"] == "drift chat"

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


# ------------------------------------------------------------- step 4 additions


def test_list_items_carry_breadcrumb_root_and_last_comment(seeded: TestClient) -> None:
    items = seeded.get("/api/tasks?status=doing").json()["items"]
    by_title = {t["title"]: t for t in items}
    quotes = by_title["Get three quotes"]
    assert [b["title"] for b in quotes["breadcrumb"]] == ["Home renovation", "Kitchen"]
    assert quotes["root"] == {"id": quotes["breadcrumb"][0]["id"], "title": "Home renovation"}
    assert quotes["last_comment"]["author"] == "Alex Chen"
    assert "{onedrive}/house/kitchen/plans" in quotes["last_comment"]["body"]
    assert quotes["comment_count"] >= 1                    # the Board renders the count, not the body (#32)
    home = by_title["Home renovation"]
    assert home["breadcrumb"] == [] and home["root"] is None and home["last_comment"] is None
    assert home["comment_count"] == 0


def test_natural_due_on_create_and_update(client: TestClient) -> None:
    r = client.post("/api/tasks", json={"title": "Renew passport", "due": "2026-08-21"})
    tid = r.json()["id"]
    p = client.patch(f"/api/tasks/{tid}", json={"due": "2026-09-01"})
    assert p.status_code == 200 and p.json()["due"] == "2026-09-01"
    # a natural phrase resolves through src.dates (relative to today, so only its shape is asserted)
    p = client.patch(f"/api/tasks/{tid}", json={"due": "in 2 weeks"})
    assert p.status_code == 200 and len(p.json()["due"]) == 10
    bad = client.patch(f"/api/tasks/{tid}", json={"due": "someday"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    cleared = client.patch(f"/api/tasks/{tid}", json={"due": ""})
    assert cleared.status_code == 200 and cleared.json()["due"] is None
    log = [a for a in cleared.json()["activity"] if a["field"] == "due"]
    assert log[0]["old_value"] and log[0]["new_value"] is None


def test_parse_endpoint(seeded: TestClient) -> None:
    r = seeded.post("/api/parse", json={"text": "renew passport next friday", "today": "2026-08-17"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "renew passport" and body["due"] == "2026-08-28"
    assert body["due_phrase"] == "next friday" and body["parent"] is None

    r = seeded.post("/api/parse", json={"text": "order sensor › garden-bot", "today": "2026-08-17"})
    body = r.json()
    assert body["parent"]["title"] == "Side project: garden-bot"
    assert body["parent_ref"] == {"title": "garden-bot"}

    r = seeded.post("/api/parse", json={"text": "x › no such project"})
    assert r.json()["parent"] is None and r.json()["parent_ref"] == {"title": "no such project"}

    r = seeded.post("/api/parse", json={"text": "x", "today": "17/08/2026"})
    assert r.status_code == 422


# ------------------------------------------------- bulk (issue #81)

def _mk(client: TestClient, title: str, **fields: object) -> int:
    return client.post("/api/tasks", json={"title": title, **fields}).json()["id"]


def test_bulk_status_and_due_across_a_selection(client: TestClient) -> None:
    ids = [_mk(client, f"T{n}") for n in range(3)]
    r = client.post("/api/tasks/bulk", json={"ids": ids, "status": "doing"})
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 3 and body["failed"] == 0
    assert {x["task"]["status"] for x in body["results"]} == {"doing"}
    # a natural phrase is resolved once, for the whole selection
    r = client.post("/api/tasks/bulk", json={"ids": ids, "due": "2026-09-01"})
    assert {x["task"]["due"] for x in r.json()["results"]} == {"2026-09-01"}
    # status + due together, and "" clears the date
    r = client.post("/api/tasks/bulk", json={"ids": ids, "status": "todo", "due": ""})
    assert [(x["task"]["status"], x["task"]["due"]) for x in r.json()["results"]] == [("todo", None)] * 3


def test_bulk_partial_failure_is_a_200_that_names_the_id(client: TestClient) -> None:
    ids = [_mk(client, f"T{n}") for n in range(2)]
    r = client.post("/api/tasks/bulk", json={"ids": [ids[0], 4242, ids[1]], "status": "todo"})
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 2 and body["failed"] == 1
    bad = [x for x in body["results"] if not x["ok"]]
    assert bad[0]["id"] == 4242 and bad[0]["error"]["code"] == "not_found"
    assert [client.get(f"/api/tasks/{i}").json()["status"] for i in ids] == ["todo", "todo"]


def test_bulk_complete_rolls_a_recurring_task(client: TestClient) -> None:
    rolling = _mk(client, "Weekly", recurrence="weekly", due="2026-08-31", status="todo")
    oneoff = _mk(client, "One-off", due="2026-08-31", status="todo")
    r = client.post("/api/tasks/bulk", json={"ids": [rolling, oneoff], "status": "complete"})
    assert r.status_code == 200 and r.json()["failed"] == 0
    results = {x["id"]: x["task"] for x in r.json()["results"]}
    assert results[rolling]["due"] == "2026-09-07" and results[rolling]["status"] == "todo"
    assert results[oneoff]["status"] == "done"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"ids": [], "status": "todo"}, 422),                    # nothing selected
        ({"ids": [1]}, 422),                                     # nothing to change
        ({"ids": [1], "status": "complete", "due": "friday"}, 422),  # complete owns the due
        ({"ids": [1], "due": "someday"}, 422),                   # one request-level date error
    ],
)
def test_bulk_refuses_a_malformed_request(client: TestClient, body: dict, status: int) -> None:
    _mk(client, "Present")
    r = client.post("/api/tasks/bulk", json=body)
    assert r.status_code == status and "error" in r.json()
