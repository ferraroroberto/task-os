"""Federated search (``src/search/``, Step 10) — the four adapters on fixture
indexes, the not-configured states with their reasons, the federated grouping
/ timeout / error handling, the API and the CLI. Hermetic: the seed for
tasks / issues, a temp tree for folders, the synthetic archiver index
(``tests/fixtures/emails_fixture.py``) for emails — never a real mailbox or a
real synced folder."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.config import load_config
from src.folder_index import FolderIndexService
from src.issue_sync import IssueSyncService
from src.issues.base import IssueInfo
from src.issues.fake import FakeProvider
from src.search import KINDS, FederatedSearch, Hit, build_federated, parse_kinds
from src.search.base import fts_query, mark_terms
from src.search.emails_adapter import EmailsAdapter, email_db_uri
from src.search.folders_adapter import FoldersAdapter
from src.search.issues_adapter import IssuesAdapter
from src.search.tasks_adapter import TasksAdapter
from tests.conftest import write_test_config
from tests.fixtures.emails_fixture import EMAILS, build_emails_db
from tests.fixtures.seed import PINNED_ANCHOR, seed_db

# ------------------------------------------------------------------ fixtures


@pytest.fixture
def od(tmp_path: Path) -> Path:
    root = tmp_path / "od"
    for rel in ("house/kitchen/plans", "house/garden", "admin/car"):
        (root / rel).mkdir(parents=True)
    return root


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    seed_db(path, PINNED_ANCHOR)
    return path


@pytest.fixture
def emails_db(tmp_path: Path, od: Path) -> Path:
    path = tmp_path / "emails.db"
    build_emails_db(path, root=od)
    return path


@pytest.fixture
def cfg(tmp_path: Path, od: Path, emails_db: Path) -> Path:
    return write_test_config(
        tmp_path / "config.json", folder_roots=["{onedrive}"],
        placeholders={"onedrive": od.as_posix(), "user": "sam"}, email_db=str(emails_db),
    )


def _folders(cfg: Path, tmp_path: Path) -> FolderIndexService:
    svc = FolderIndexService(load_config(cfg), index_path=tmp_path / "idx.txt")
    svc.reindex()
    return svc


def _issues(tmp_path: Path, extra: list[dict[str, Any]] | None = None) -> IssueSyncService:
    """A sync service over the fake forge with a warm cache (one pass run)."""
    forge = [
        {"repo": "example/garden-bot", "number": 12, "title": "Fix watering schedule drift", "state": "open",
         "url": "https://github.com/example/garden-bot/issues/12", "labels": ["bug"]},
        {"repo": "example/home-dashboard", "number": 3, "title": "Kitchen lights automation", "state": "open",
         "url": "https://github.com/example/home-dashboard/issues/3", "labels": ["enhancement", "kitchen"]},
        *(extra or []),
    ]
    provider = FakeProvider.from_issues(tmp_path / "forge.json", forge)
    svc = IssueSyncService(load_config(), provider=provider)
    svc.run_now()
    return svc


# ------------------------------------------------------------------- helpers


def test_helpers_fts_query_and_marks() -> None:
    assert fts_query('kitchen "quo:tes" x') == '"kitchen"* "\"\"quo:tes\"\""* "x"*'
    assert fts_query("   ") == ""
    assert mark_terms("The Kitchen kit", "kit kitchen") == "The [Kitchen] [kit]"     # longest first, no nesting
    assert mark_terms("plain", "") == "plain" and mark_terms("", "x") == ""
    assert parse_kinds(None) == list(KINDS) and parse_kinds("emails, tasks,bogus") == ["tasks", "emails"]
    assert parse_kinds("") == list(KINDS)
    h = Hit(kind="tasks", title="t", score=1.23456, extra={"task_id": 4}).to_dict()
    assert h["score"] == 1.2346 and h["task_id"] == 4 and set(h) >= {"kind", "title", "subtitle", "snippet", "ref", "url"}


# ------------------------------------------------------------- tasks adapter


def test_tasks_adapter_hits_on_seed(seeded_db: Path) -> None:
    a = TasksAdapter()
    assert a.is_configured() == (True, None)
    hits = a.search("kitchen", 10)
    assert [h.title for h in hits][:2] == ["Kitchen", "Get three quotes"]
    top = hits[0].to_dict()
    assert top["url"] == "#task/2" and top["ref"] == "2" and top["task_id"] == 2 and top["matched_in"] == "title"
    assert top["snippet"] == "[Kitchen]" and "Home renovation" in top["subtitle"] and "doing" in top["subtitle"]
    quotes = hits[1].to_dict()
    assert quotes["matched_in"] == "comment" and "[kitchen]" in quotes["snippet"]
    assert quotes["breadcrumb"][-1]["title"] == "Kitchen"
    assert a.search("nothing-like-this", 10) == []


# ----------------------------------------------------------- folders adapter


def test_folders_adapter_configured_and_not(cfg: Path, tmp_path: Path) -> None:
    svc = _folders(cfg, tmp_path)
    a = FoldersAdapter(svc)
    assert a.is_configured() == (True, None) and a.note() is None
    hits = a.search("kitchen", 10)
    assert [h.ref for h in hits] == ["{onedrive}/house/kitchen", "{onedrive}/house/kitchen/plans"]
    h = hits[0].to_dict()
    assert h["title"] == "kitchen" and h["subtitle"] == "{onedrive}/house/kitchen"
    assert h["url"] == "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"
    assert h["snippet"].endswith("/house/[kitchen]") and h["path"].endswith("/od/house/kitchen")
    assert hits[0].score > hits[1].score

    off = FoldersAdapter(FolderIndexService(load_config(write_test_config(tmp_path / "off.json")), index_path=tmp_path / "x.txt"))
    ok, reason = off.is_configured()
    assert ok is False and "folder_roots not configured" in reason
    assert FoldersAdapter(None).is_configured() == (False, "folder index service not started")
    empty = FoldersAdapter(FolderIndexService(load_config(cfg), index_path=tmp_path / "empty.txt"))
    assert empty.is_configured()[0] and empty.note() == "index empty — reindex from Settings"


# ------------------------------------------------------------ emails adapter


def test_emails_adapter_fts_bm25_and_refs(emails_db: Path, od: Path) -> None:
    a = EmailsAdapter(str(emails_db), {"onedrive": od.as_posix()})
    assert a.is_configured() == (True, None)
    assert email_db_uri(emails_db).endswith("?mode=ro") and email_db_uri(emails_db).startswith("file:")
    hits = a.search("kitchen", 10)
    # subject × 10 beats body × 1: the "Kitchen quotes" mail ranks above the forms mail whose body says kitchen-table
    assert [h.title for h in hits] == ["Kitchen quotes from the installer", "School enrolment forms — deadline Friday"]
    top = hits[0].to_dict()
    assert top["snippet"] == "[Kitchen] quotes from the installer"
    assert top["ref"] == "{onedrive}/mail/house/2026-08-10 Kitchen quotes.msg"      # folded onto the placeholder
    assert top["path"] == od.as_posix() + "/mail/house/2026-08-10 Kitchen quotes.msg"
    assert top["url"].startswith("taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse")
    assert top["subtitle"] == "Sam Rivera <sam@example.com> · 2026-08-10 · house"
    assert top["email_id"] == 1 and top["date"] == "2026-08-10T09:12:00" and top["folder"].endswith("/mail/house")
    assert hits[1].to_dict()["snippet"].startswith("…") or "[kitchen]" in hits[1].to_dict()["snippet"]
    # prefix + AND: "pass" hits passport; two words must both match
    assert [h.title for h in a.search("pass", 10)] == ["Passport renewal appointment confirmed"]
    assert [h.title for h in a.search("fence tuesday", 10)] == ["Fence repair — availability next week"]
    assert a.search("fence passport", 10) == []
    # sender × 3: a query on the sender's name finds the mail
    assert a.search("jordan", 10)[0].title.startswith("School enrolment")
    # a path outside every placeholder stays absolute
    bare = EmailsAdapter(str(emails_db), {})
    assert bare.search("water", 10)[0].ref == od.as_posix() + "/mail/admin/2026-08-05 Water bill.msg"
    # limit + a query of only punctuation
    assert len(a.search("mail", 2)) <= 2 and a.search("   ", 10) == []


def test_emails_adapter_is_read_only(emails_db: Path, od: Path) -> None:
    a = EmailsAdapter(str(emails_db), {})
    conn = a._connect()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO emails(file_path, folder_path, filename, file_mtime) VALUES ('x','y','z',1)")
    conn.close()
    # the file did not gain a WAL/SHM sidecar and still has its 6 rows
    assert not Path(str(emails_db) + "-wal").exists()
    check = sqlite3.connect(str(emails_db))
    assert check.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == len(EMAILS)
    check.close()


def test_emails_adapter_like_fallback_without_fts(tmp_path: Path, od: Path) -> None:
    legacy = tmp_path / "legacy.db"
    build_emails_db(legacy, root=od, fts=False, touch_files=False)
    a = EmailsAdapter(str(legacy), {"onedrive": od.as_posix()})
    assert a.is_configured() == (True, None)
    hits = a.search("kitchen", 10)
    assert {h.title for h in hits} == {"Kitchen quotes from the installer", "School enrolment forms — deadline Friday"}
    assert hits[0].to_dict()["date"] >= hits[1].to_dict()["date"]        # newest first
    assert all("[" in h.snippet for h in hits)                             # mark_terms did the highlighting
    assert [h.title for h in a.search("fence tuesday", 10)] == ["Fence repair — availability next week"]


def test_emails_adapter_not_configured_reasons(tmp_path: Path) -> None:
    ok, reason = EmailsAdapter("", {}).is_configured()
    assert ok is False and reason == "search.email_db not configured"
    ok, reason = EmailsAdapter(str(tmp_path / "missing.db"), {}).is_configured()
    assert ok is False and reason.startswith("email index not found at ")
    other = tmp_path / "other.db"
    sqlite3.connect(str(other)).execute("CREATE TABLE t(x)").connection.commit()
    ok, reason = EmailsAdapter(str(other), {}).is_configured()
    assert ok is False and "no emails table" in reason


# ------------------------------------------------------------ issues adapter


def test_issues_adapter_over_refs_and_cache(seeded_db: Path, tmp_path: Path) -> None:
    svc = _issues(tmp_path)
    a = IssuesAdapter(svc)
    assert a.is_configured() == (True, None)
    # local ref (garden-bot#12 on the seed) merged with the cached labels
    hits = a.search("watering", 10)
    assert len(hits) == 1
    h = hits[0].to_dict()
    assert h["ref"] == "example/garden-bot#12" and h["task_id"] is not None and h["labels"] == ["bug"]
    assert h["url"] == "https://github.com/example/garden-bot/issues/12" and h["state"] == "open"
    assert h["subtitle"] == "example/garden-bot#12 · open · bug" and h["snippet"] == "Fix [watering] schedule drift"
    # the sync made a task for the dashboard issue too, so it is a ref now; label / repo / number all match
    kitchen = a.search("kitchen", 10)
    assert [x.ref for x in kitchen] == ["example/home-dashboard#3"]
    assert [x.ref for x in a.search("home-dashboard", 10)] == ["example/home-dashboard#3"]
    assert [x.ref for x in a.search("#12", 10)] == ["example/garden-bot#12"]
    assert [x.ref for x in a.search("enhancement", 10)] == ["example/home-dashboard#3"]
    assert a.search("kitchen watering", 10) == []                        # AND across words
    # a cached issue with no task yet still surfaces (task_id None)
    svc.cache[("github", "example/garden-bot", 99)] = IssueInfo(
        provider="github", repo="example/garden-bot", number=99, title="Zebra crossing lights",
        url="https://github.com/example/garden-bot/issues/99", state="open", labels=("idea",))
    z = a.search("zebra", 10)
    assert len(z) == 1 and z[0].to_dict()["task_id"] is None and z[0].to_dict()["number"] == 99


def test_issues_adapter_not_configured(seeded_db: Path) -> None:
    off = IssueSyncService(load_config())        # TASKOS_ISSUE_PROVIDER=none in the suite
    ok, reason = IssuesAdapter(off).is_configured()
    assert ok is False and reason
    assert IssuesAdapter(None).is_configured() == (False, "issue service not started")


# ---------------------------------------------------------------- federated


class _Slow:
    name = kind = "emails"

    def __init__(self, delay: float) -> None:
        self.delay = delay

    def is_configured(self) -> tuple[bool, str | None]:
        return True, None

    def search(self, q: str, limit: int) -> list[Hit]:
        time.sleep(self.delay)
        return [Hit(kind="emails", title="late")]


class _Broken:
    name = kind = "issues"

    def is_configured(self) -> tuple[bool, str | None]:
        return True, None

    def search(self, q: str, limit: int) -> list[Hit]:
        raise RuntimeError("index corrupt")


def test_federated_groups_always_four_and_visible_states(seeded_db: Path, cfg: Path, tmp_path: Path) -> None:
    config = load_config(cfg)
    fed = build_federated(config, folders=_folders(cfg, tmp_path), issues=None)
    r = fed.search("kitchen", limit=5)
    assert [g["kind"] for g in r["groups"]] == list(KINDS)
    by = {g["kind"]: g for g in r["groups"]}
    assert by["tasks"]["count"] == 2 and by["folders"]["count"] == 2 and by["emails"]["count"] == 2
    assert by["issues"] == {**by["issues"], "configured": False, "reason": "issue service not started", "hits": [], "count": 0}
    assert all(g["skipped"] is False for g in r["groups"])
    assert isinstance(r["took_ms"], int) and all(g["error"] is None for g in r["groups"])
    # kinds= narrows what runs; the rest are still there, marked skipped
    r2 = fed.search("kitchen", kinds=["tasks"], limit=5)
    by2 = {g["kind"]: g for g in r2["groups"]}
    assert by2["tasks"]["count"] == 2 and by2["emails"]["skipped"] is True and by2["emails"]["configured"] is True
    assert by2["emails"]["hits"] == [] and by2["issues"]["configured"] is False
    # status() = the Settings card
    st = {s["kind"]: s for s in fed.status()}
    assert st["emails"]["configured"] is True and st["issues"]["reason"] == "issue service not started"
    # blank query = the four groups, nothing run
    r3 = fed.search("   ")
    assert r3["q"] == "" and all(g["count"] == 0 for g in r3["groups"])


def test_federated_timeout_and_error_are_group_states(seeded_db: Path) -> None:
    fed = FederatedSearch([TasksAdapter(), _Slow(1.5), _Broken()], timeout_s=0.3)
    t = time.perf_counter()
    r = fed.search("kitchen", limit=5)
    assert time.perf_counter() - t < 1.2                                # the slow one did not hold the answer
    by = {g["kind"]: g for g in r["groups"]}
    assert by["tasks"]["count"] == 2
    assert by["emails"]["configured"] is True and by["emails"]["error"] == "timed out after 0 s" and by["emails"]["hits"] == []
    assert by["issues"]["configured"] is True and by["issues"]["error"] == "RuntimeError: index corrupt"
    assert by["folders"]["configured"] is False and by["folders"]["reason"] == "no adapter"


# ---------------------------------------------------------------- API + CLI


@pytest.fixture
def client(seeded_db: Path, cfg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        c.post("/api/folders/reindex")
        yield c


def test_api_search_grouped_and_status(client: TestClient) -> None:
    r = client.get("/api/search?q=kitchen&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["q"] == "kitchen" and [g["kind"] for g in body["groups"]] == list(KINDS)
    by = {g["kind"]: g for g in body["groups"]}
    assert by["tasks"]["hits"][0]["url"] == "#task/2"
    assert by["folders"]["hits"][0]["ref"] == "{onedrive}/house/kitchen"
    assert by["emails"]["hits"][0]["ref"].endswith("Kitchen quotes.msg") and by["emails"]["hits"][0]["url"].startswith("taskos://")
    assert by["issues"]["configured"] is False and by["issues"]["reason"]
    r = client.get("/api/search?q=kitchen&kinds=tasks,emails")
    by = {g["kind"]: g for g in r.json()["groups"]}
    assert by["folders"]["skipped"] is True and by["tasks"]["skipped"] is False and by["emails"]["count"] == 2
    assert client.get("/api/search?q=").status_code == 422
    assert client.get("/api/search?q=x&limit=0").status_code == 422
    st = client.get("/api/search/status").json()["adapters"]
    assert [a["kind"] for a in st] == list(KINDS) and st[2]["configured"] is True and st[3]["configured"] is False


def test_cli_search_federated_local_and_json(seeded_db: Path, cfg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from src import cli

    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(dbmod, "DEFAULT_DB_PATH", seeded_db)          # the folder index file lands next to it
    FolderIndexService(load_config(cfg)).reindex()
    backend = cli.LocalBackend(actor="tester")
    code = cli.main(["search", "kitchen"], backend=backend)
    out = capsys.readouterr().out
    assert code == 0
    assert "tasks (2" in out and "#2  Kitchen" in out and "folders (2" in out and "{onedrive}/house/kitchen" in out
    assert "emails (2" in out and "Kitchen quotes from the installer" in out and "issues: not configured" in out
    code = cli.main(["search", "kitchen", "--kind", "emails", "--json"], backend=backend)
    out = capsys.readouterr().out
    body = json.loads(out)
    by = {g["kind"]: g for g in body["groups"]}
    assert by["emails"]["count"] == 2 and by["tasks"]["skipped"] is True
    code = cli.main(["search", "kitchen", "--kind", "emails"], backend=backend)
    out = capsys.readouterr().out
    assert "tasks" not in out.split("\n")[0] and out.startswith("emails (2")
