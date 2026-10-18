"""A task's owner (#476, Step 3/4 of #471): schema v20, the NULL-means-the-
install-owner rule in ``src/tasks_repo.py``, owner on create / PATCH / bulk,
the ``owner`` filter, and the two scripts (``migrate_dry_run.py``,
``assign_owner.py``). Hermetic — temp databases and configs only; every name
and secret here is synthetic."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts import assign_owner, migrate_dry_run
from src import config as cfgmod
from src import db as dbmod
from src import schema
from src import tasks_repo as repo
from tests.conftest import write_test_config

LOOPBACK = ("127.0.0.1", 50000)
PHONE = ("100.101.102.103", 50000)  # a tailnet client
TOKEN = "owner-token-for-tests-only"
P2_TOKEN = "p2-owner-token-for-tests-only"
MEMBERS = [{"id": "p1", "name": "Person 1"}, {"id": "p2", "name": "Person 2"}]


@pytest.fixture
def members() -> Iterator[None]:
    """The two sample members for a repo-level test; the implicit one after."""
    repo.set_members(["p1", "p2"])
    yield
    repo.set_members(None)


@pytest.fixture
def conn(tmp_path: Path, members: None) -> Iterator[sqlite3.Connection]:
    dbmod.init_db(tmp_path / "tasks.db")
    c = dbmod.connect(tmp_path / "tasks.db")
    yield c
    c.close()


@pytest.fixture
def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))

    def _make(people: list | None = None):
        path = write_test_config(tmp_path / "config.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["people"] = MEMBERS if people is None else people
        raw["auth"] = {"token": TOKEN, "password_hash": "", "people": {"p2": {"token": P2_TOKEN}}}
        path.write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
        from app.webapp.server import create_app

        return create_app()

    return _make


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _v19_db(path: Path) -> None:
    """A v19 database holding a little of everything Step 3 must not touch."""
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    for target in range(1, 20):
        c.executescript(schema.MIGRATIONS[target])
    c.execute("INSERT INTO settings(key, value) VALUES ('schema_version', '19')")
    c.execute("INSERT INTO people(id, name) VALUES (1, 'A contact'), (2, 'Another contact')")
    for tid, person in ((1, 1), (2, 2), (3, None), (4, 1)):
        c.execute(
            "INSERT INTO tasks(id, title, person_id, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, 'me', 'c', 'u')", (tid, f"Task {tid}", person),
        )
        c.execute(
            "INSERT INTO activity(task_id, ts, actor, field, old_value, new_value)"
            " VALUES (?, 'ts', 'me', 'created', NULL, 'x')", (tid,),
        )
    cat = c.execute("SELECT id FROM time_categories LIMIT 1").fetchone()[0]
    for person, minutes in (("p1", 30), ("p2", 45)):
        c.execute(
            "INSERT INTO time_entries(person, category_id, day, minutes, created_at, updated_at)"
            " VALUES (?, ?, '2026-10-17', ?, 'c', 'u')", (person, cat, minutes),
        )
    c.commit()
    c.close()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------ schema v20


def test_v19_migrates_to_v20_without_touching_a_row(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    _v19_db(path)
    c = sqlite3.connect(path)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    counts = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    persons = c.execute("SELECT id, person_id FROM tasks ORDER BY id").fetchall()
    entries = c.execute("SELECT id, person, minutes FROM time_entries ORDER BY id").fetchall()
    c.close()

    assert dbmod.init_db(path) == 20
    c = sqlite3.connect(path)
    try:
        assert {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables} == counts
        assert c.execute("SELECT id, person_id FROM tasks ORDER BY id").fetchall() == persons
        assert c.execute("SELECT id, person, minutes FROM time_entries ORDER BY id").fetchall() == entries
        assert {r[0] for r in c.execute("SELECT owner FROM tasks")} == {None}   # nothing rewritten
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_tasks_owner'").fetchone()
    finally:
        c.close()


# --------------------------------------------------------- the repo rule


def test_a_null_owner_is_the_install_owners(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Never given one")
    assert conn.execute("SELECT owner FROM tasks WHERE id = ?", (t["id"],)).fetchone()[0] is None
    assert t["owner"] == "p1"                                         # every shape: the effective owner
    assert repo.list_tasks(conn)[0]["owner"] == "p1"
    assert repo.tree(conn)[0]["owner"] == "p1"
    # naming the owner a NULL already means is no change: nothing written, nothing logged
    again = repo.update_task(conn, t["id"], owner="p1", actor="tester")
    assert again["updated_at"] == t["updated_at"]
    assert [a["field"] for a in again["activity"]] == ["created"]


def test_changing_the_owner_logs_old_to_new(conn: sqlite3.Connection) -> None:
    t = repo.create_task(conn, "Hand me over")
    moved = repo.update_task(conn, t["id"], owner="p2", actor="tester")
    assert moved["owner"] == "p2"
    log = [(a["field"], a["old_value"], a["new_value"]) for a in moved["activity"] if a["field"] == "owner"]
    assert log == [("owner", "p1", "p2")]
    back = repo.update_task(conn, t["id"], owner="p1", actor="tester")
    assert back["owner"] == "p1"
    assert conn.execute("SELECT owner FROM tasks WHERE id = ?", (t["id"],)).fetchone()[0] == "p1"
    # an explicit set on create stores the id, the install owner's included
    mine = repo.create_task(conn, "Mine on purpose", owner="p1")
    assert conn.execute("SELECT owner FROM tasks WHERE id = ?", (mine["id"],)).fetchone()[0] == "p1"


@pytest.mark.parametrize("bad", ["nobody", "", None])
def test_an_owner_must_be_a_member(conn: sqlite3.Connection, bad: str | None) -> None:
    t = repo.create_task(conn, "Keep my owner")
    with pytest.raises(repo.ValidationError, match="owner must be one of p1, p2"):
        repo.update_task(conn, t["id"], owner=bad)
    if bad is not None:
        with pytest.raises(repo.ValidationError):
            repo.create_task(conn, "Refused", owner=bad)


def test_the_owner_filter_counts_null_as_the_install_owners(conn: sqlite3.Connection) -> None:
    nobody = repo.create_task(conn, "Nobody gave me one")
    p1 = repo.create_task(conn, "Given to p1", owner="p1")
    p2 = repo.create_task(conn, "Given to p2", owner="p2")
    ids = lambda **kw: {t["id"] for t in repo.list_tasks(conn, **kw)}  # noqa: E731
    assert ids(owner="p1") == {nobody["id"], p1["id"]}
    assert ids(owner="p2") == {p2["id"]}
    assert ids(owner=["p1", "p2"]) == {nobody["id"], p1["id"], p2["id"]}
    assert ids() == {nobody["id"], p1["id"], p2["id"]}


def test_bulk_sets_the_owner_per_id(conn: sqlite3.Connection) -> None:
    a = repo.create_task(conn, "A")
    b = repo.create_task(conn, "B")
    results = repo.bulk_update(conn, [a["id"], b["id"], 999], owner="p2", actor="tester")
    assert [(r["id"], r["ok"]) for r in results] == [(a["id"], True), (b["id"], True), (999, False)]
    assert {r["task"]["owner"] for r in results if r["ok"]} == {"p2"}


# --------------------------------------------------------------- the API


def test_a_task_is_its_creators_member_or_loopback_owner(make_app) -> None:
    with TestClient(make_app(), client=PHONE) as c:
        made = c.post("/api/tasks", json={"title": "From the second phone"}, headers=_as(P2_TOKEN))
        assert made.status_code == 201 and made.json()["owner"] == "p2"
        mine = c.post("/api/tasks", json={"title": "From the owner's phone"}, headers=_as(TOKEN))
        assert mine.json()["owner"] == "p1"
        explicit = c.post("/api/tasks", json={"title": "For p1", "owner": "p1"}, headers=_as(P2_TOKEN))
        assert explicit.json()["owner"] == "p1"
        # a subtask is its creator's, not its parent's
        child = c.post("/api/tasks", json={"title": "Child", "parent_id": made.json()["id"]}, headers=_as(TOKEN))
        assert child.json()["owner"] == "p1"
    with TestClient(make_app(), client=LOOPBACK) as c:
        t = c.post("/api/tasks", json={"title": "At the PC, no credential"}).json()
        assert t["owner"] == "p1"


def test_patch_bulk_and_the_filter(make_app) -> None:
    with TestClient(make_app(), client=LOOPBACK) as c:
        a = c.post("/api/tasks", json={"title": "A"}).json()
        b = c.post("/api/tasks", json={"title": "B"}).json()
        patched = c.patch(f"/api/tasks/{a['id']}", json={"owner": "p2"})
        assert patched.status_code == 200 and patched.json()["owner"] == "p2"
        assert any(x["field"] == "owner" and (x["old_value"], x["new_value"]) == ("p1", "p2")
                   for x in patched.json()["activity"])
        assert c.get(f"/api/tasks/{a['id']}").json()["owner"] == "p2"            # a reload keeps it

        refused = c.patch(f"/api/tasks/{a['id']}", json={"owner": "nobody"})
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "validation_error"
        assert "owner must be one of" in refused.json()["error"]["message"]

        bulk = c.post("/api/tasks/bulk", json={"ids": [a["id"], b["id"]], "owner": "p1"}).json()
        assert bulk["updated"] == 2 and [r["task"]["owner"] for r in bulk["results"]] == ["p1", "p1"]
        c.post("/api/tasks/bulk", json={"ids": [b["id"]], "owner": "p2"})
        legacy = c.post("/api/tasks", json={"title": "Legacy"}).json()
        raw = dbmod.connect()                       # stands in for a task from before v20
        raw.execute("UPDATE tasks SET owner = NULL WHERE id = ?", (legacy["id"],))
        raw.commit()
        raw.close()
        mine = {t["id"] for t in c.get("/api/tasks?owner=p1").json()["items"]}
        theirs = {t["id"] for t in c.get("/api/tasks?owner=p2").json()["items"]}
        assert mine == {a["id"], legacy["id"]} and theirs == {b["id"]}
        both = {t["id"] for t in c.get("/api/tasks?owner=p1,p2").json()["items"]}
        assert both == {a["id"], b["id"], legacy["id"]}


def test_one_member_changes_nothing_but_the_key(make_app) -> None:
    with TestClient(make_app(people=[{"id": "solo", "name": "Solo"}]), client=LOOPBACK) as c:
        t = c.post("/api/tasks", json={"title": "On my own"}).json()
        assert t["owner"] == "solo"
        assert c.get("/api/me").json()["people"] == [{"id": "solo", "name": "Solo"}]
        assert c.patch(f"/api/tasks/{t['id']}", json={"owner": "p2"}).status_code == 422


# ------------------------------------------------------------ the scripts


def test_migrate_dry_run_never_writes_the_source(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "tasks.db"
    _v19_db(path)
    mtime, digest = path.stat().st_mtime_ns, _sha(path)
    report = migrate_dry_run.dry_run(path)
    assert (path.stat().st_mtime_ns, _sha(path)) == (mtime, digest)
    assert not list(tmp_path.glob("tasks.db-*"))                        # no WAL / shm left beside it
    assert (report["schema_version_before"], report["schema_version_after"]) == (19, 20)
    assert report["row_counts_unchanged"] and report["content_unchanged"] and report["source_mtime_unchanged"]
    assert report["null_owner_tasks"] == 4
    assert all(t.get("content_unchanged", True) for t in report["tables"])
    assert migrate_dry_run.main(["--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "row counts unchanged: yes" in out and "Task " not in out     # counts only, never a title
    assert (path.stat().st_mtime_ns, _sha(path)) == (mtime, digest)
    assert migrate_dry_run.main(["--db", str(tmp_path / "missing.db")]) == 2


def test_assign_owner_dry_runs_by_default(tmp_path: Path, capsys: pytest.CaptureFixture,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "tasks.db"
    _v19_db(path)
    dbmod.init_db(path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    digest = _sha(path)
    assert assign_owner.main(["--db", str(path), "--person-id", "1", "--to", "p2"]) == 0
    assert "to give to p2: 2" in capsys.readouterr().out
    assert _sha(path) == digest                                          # the dry run wrote nothing
    assert assign_owner.main(["--db", str(path), "--person-id", "1", "--to", "nobody"]) == 2
    assert assign_owner.main(["--db", str(path), "--person-id", "1", "--to", "p2", "--apply"]) == 0
    c = sqlite3.connect(path)
    try:
        owners = dict(c.execute("SELECT id, owner FROM tasks").fetchall())
        assert owners == {1: "p2", 2: None, 3: None, 4: "p2"}
        logged = c.execute(
            "SELECT task_id, actor, old_value, new_value FROM activity WHERE field = 'owner' ORDER BY task_id"
        ).fetchall()
        assert logged == [(1, "assign_owner", "p1", "p2"), (4, "assign_owner", "p1", "p2")]
    finally:
        c.close()
    repo.set_members(None)
