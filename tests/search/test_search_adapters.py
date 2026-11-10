"""Federated search (``src/search/``, Step 10) — the four adapters, the
not-configured and unavailable states with their reasons, the federated grouping
/ timeout / error handling, the API and the CLI. Hermetic: the seed for tasks /
issues, and a fake folder-explorer (``tests/fixtures/folder_explorer_fake.py``)
over a temp tree and the synthetic mails for folders and emails — never a real
mailbox, a real synced folder or the real folder-explorer."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src import tasks_repo as repo
from src.config import load_config
from src.issue_sync import IssueSyncService
from src.issues.base import IssueInfo
from src.issues.fake import FakeProvider
from src.search import KINDS, FederatedSearch, Hit, build_federated, parse_kinds
from src.search.base import mark_terms
from src.search.emails_adapter import EmailsAdapter
from src.search.folder_explorer import FolderExplorerClient, Unavailable
from src.search.folders_adapter import FoldersAdapter
from src.search.issues_adapter import IssuesAdapter
from src.search.tasks_adapter import TasksAdapter
from tests.conftest import write_test_config
from tests.fixtures.folder_explorer_fake import FakeFolderExplorer, fixture_mails, folders_under
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
def fe(od: Path) -> Iterator[FakeFolderExplorer]:
    fake = FakeFolderExplorer(folders=folders_under(od), emails=fixture_mails(od))
    yield fake
    fake.stop()


@pytest.fixture
def client_fe(fe: FakeFolderExplorer) -> FolderExplorerClient:
    return FolderExplorerClient(fe.url)


@pytest.fixture
def cfg(tmp_path: Path, od: Path, fe: FakeFolderExplorer) -> Path:
    return write_test_config(
        tmp_path / "config.json", folder_explorer_url=fe.url,
        placeholders={"onedrive": od.as_posix(), "user": "sam"},
    )


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
    assert repo._fts_query('kitchen "quo:tes" x') == '"kitchen"* "\"\"quo:tes\"\""* "x"*'
    assert repo._fts_query("   ") == ""
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
    assert top["snippet"] == "[Kitchen]" and "Home renovation" in top["subtitle"] and "todo" in top["subtitle"]
    quotes = hits[1].to_dict()
    assert quotes["matched_in"] == "comment" and "[kitchen]" in quotes["snippet"]
    assert quotes["breadcrumb"][-1]["title"] == "Kitchen"
    assert a.search("nothing-like-this", 10) == []


# ----------------------------------------------------------- folders adapter


def test_folders_adapter_hits_from_folder_explorer(client_fe: FolderExplorerClient, od: Path, fe: FakeFolderExplorer) -> None:
    a = FoldersAdapter(client_fe, {"onedrive": od.as_posix()})
    assert a.is_configured() == (True, None)
    hits = a.search("kitchen", 10)
    assert [h.ref for h in hits] == ["{onedrive}/house/kitchen", "{onedrive}/house/kitchen/plans"]
    h = hits[0].to_dict()
    assert h["title"] == "kitchen" and h["subtitle"] == "{onedrive}/house/kitchen"
    assert h["url"] == "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"
    assert h["snippet"].endswith("/house/[kitchen]") and h["path"].endswith("/od/house/kitchen")
    assert a.search("nothing-like-this", 10) == []              # ok + no match is an empty list
    assert a.availability() == ("ok", None, "1 of 1 root(s) scanned")
    assert fe.requests[0].startswith("/api/v1/search/folders?")


def test_folders_adapter_not_configured_without_an_address() -> None:
    off = FoldersAdapter(FolderExplorerClient(""))
    assert off.is_configured() == (False, "search.folder_explorer_url not configured")
    assert FoldersAdapter(None).is_configured() == (False, "search.folder_explorer_url not configured")


# ------------------------------------------------------------ emails adapter


def test_emails_adapter_hits_refs_and_marks(client_fe: FolderExplorerClient, od: Path) -> None:
    a = EmailsAdapter(client_fe, {"onedrive": od.as_posix()})
    assert a.is_configured() == (True, None)
    hits = a.search("kitchen", 10)
    # folder-explorer ranks: the subject match first, then the mail whose body says kitchen-table
    assert [h.title for h in hits] == ["Kitchen quotes from the installer", "School enrolment forms — deadline Friday"]
    top = hits[0].to_dict()
    assert top["snippet"] == "[Kitchen] quotes from the installer"
    assert top["ref"] == "{onedrive}/mail/house/2026-08-10 Kitchen quotes.msg"      # folded onto the placeholder
    assert top["path"] == od.as_posix() + "/mail/house/2026-08-10 Kitchen quotes.msg"
    assert top["url"].startswith("taskos://open?ref=%7Bonedrive%7D%2Fmail%2Fhouse")
    assert top["subtitle"] == "Sam Rivera · 2026-08-10 · house"
    assert top["email_id"] == 1 and top["date"] == "2026-08-10T09:12:00+02:00" and top["folder"].endswith("/mail/house")
    assert hits[0].score > hits[1].score
    assert "[kitchen]" in hits[1].to_dict()["snippet"]
    assert [h.title for h in a.search("fence tuesday", 10)] == ["Fence repair — availability next week"]
    assert a.search("fence passport", 10) == []
    # a path outside every placeholder stays absolute
    bare = EmailsAdapter(client_fe, {})
    assert bare.search("water", 10)[0].ref == od.as_posix() + "/mail/admin/2026-08-05 Water bill.msg"
    assert len(a.search("mail", 2)) <= 2
    assert a.availability() == ("ok", None, "6 mail(s)")


def test_the_emails_group_links_to_folder_explorer_deep_search(client_fe: FolderExplorerClient) -> None:
    """Set, the group carries folder-explorer's email search for the same words; blank, no link."""
    deep = EmailsAdapter(client_fe, {}, "https://explorer.example.invalid:8453/#explore")
    fed = FederatedSearch([deep])
    group = {g["kind"]: g for g in fed.search("boiler service & co")["groups"]}["emails"]
    assert group["deep_link"] == "https://explorer.example.invalid:8453/#search?mode=emails&q=boiler%20service%20%26%20co"
    assert {g["kind"]: g for g in fed.search("")["groups"]}["emails"]["deep_link"] is None
    plain = {g["kind"]: g for g in FederatedSearch([EmailsAdapter(client_fe, {})]).search("boiler")["groups"]}
    assert plain["emails"]["deep_link"] is None and plain["tasks"]["deep_link"] is None


def test_emails_adapter_not_configured_without_an_address() -> None:
    assert EmailsAdapter(FolderExplorerClient(""), {}).is_configured() == (False, "search.folder_explorer_url not configured")


# --------------------------------------------- folder-explorer's five states


@pytest.mark.parametrize(("part", "state", "reason", "expected"), [
    ("folders", "not-configured", "no root has a finished scan yet", "not-configured"),
    ("folders", "indexing", "the first scan is running", "indexing"),
    ("emails", "error", "the email index could not be read: disk I/O error", "failed"),
    ("emails", "failed", "the first email build died", "failed"),
])
def test_a_part_that_cannot_answer_is_its_state_never_an_empty_list(
    fe: FakeFolderExplorer, client_fe: FolderExplorerClient, part: str, state: str, reason: str, expected: str,
) -> None:
    fe.set_state(part, state, reason)
    adapter = FoldersAdapter(client_fe) if part == "folders" else EmailsAdapter(client_fe)
    with pytest.raises(Unavailable) as caught:
        adapter.search("kitchen", 10)
    assert (caught.value.state, caught.value.reason) == (expected, reason)
    assert adapter.availability()[:2] == (expected, reason)
    # the federated group carries it as `unavailable`, with no hits and no error
    fed = FederatedSearch([adapter])
    g = {x["kind"]: x for x in fed.search("kitchen")["groups"]}[part]
    assert g["unavailable"] == {"state": expected, "reason": reason}
    assert g["configured"] is True and g["hits"] == [] and g["count"] == 0 and g["error"] is None


def test_folder_explorer_down_is_unreachable_not_zero_results(fe: FakeFolderExplorer, client_fe: FolderExplorerClient) -> None:
    fe.stop()
    fed = FederatedSearch([FoldersAdapter(client_fe), EmailsAdapter(client_fe)])
    by = {g["kind"]: g for g in fed.search("kitchen")["groups"]}
    for kind in ("folders", "emails"):
        assert by[kind]["unavailable"]["state"] == "unreachable" and by[kind]["hits"] == []
        assert "did not answer" in by[kind]["unavailable"]["reason"]
    st = {s["kind"]: s for s in fed.status()}
    assert st["folders"]["configured"] is True and st["folders"]["state"] == "unreachable"


def test_a_configured_address_nobody_answers_on_is_unavailable_never_empty(tmp_path: Path) -> None:
    """An address read from the config (here a port with no listener) reaches the groups as ``unreachable``."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg = load_config(write_test_config(tmp_path / "config.json", folder_explorer_url=f"https://127.0.0.1:{port}"))
    client = FolderExplorerClient(cfg.search.folder_explorer_url)
    by = {g["kind"]: g for g in FederatedSearch([FoldersAdapter(client), EmailsAdapter(client, {})]).search("kitchen")["groups"]}
    for kind in ("folders", "emails"):
        assert by[kind]["unavailable"]["state"] == "unreachable" and by[kind]["hits"] == [] and by[kind]["count"] == 0


@pytest.mark.parametrize(("mode", "needle"), [
    ("garbled", "without a v1 envelope"), ("bare422", "HTTP 422 without a v1 envelope"),
    ("v2", "schema_version 2"), ("mystery", "unknown state 'melting'"),
])
def test_an_answer_that_is_not_the_contract_is_failed(
    fe: FakeFolderExplorer, client_fe: FolderExplorerClient, mode: str, needle: str,
) -> None:
    fe.mode = mode
    with pytest.raises(Unavailable) as caught:
        client_fe.folders("kitchen", 5)
    assert caught.value.state == "failed" and needle in caught.value.reason


def test_a_blank_address_is_not_configured_with_no_request() -> None:
    client = FolderExplorerClient("")
    assert client.summary() == {"enabled": False, "reason": "search.folder_explorer_url not configured", "url": None}
    with pytest.raises(Unavailable) as caught:
        client.folders("x", 5)
    assert caught.value.state == "not-configured"


def test_summary_reports_the_address_without_a_request(fe: FakeFolderExplorer) -> None:
    client = FolderExplorerClient(fe.url + "/")
    assert client.summary() == {"enabled": True, "reason": None, "url": fe.url}
    assert fe.requests == []


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


def test_federated_groups_always_four_and_visible_states(seeded_db: Path, cfg: Path) -> None:
    config = load_config(cfg)
    fed = build_federated(config, folder_explorer=FolderExplorerClient(config.search.folder_explorer_url), issues=None)
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
    assert st["emails"]["configured"] is True and st["emails"]["state"] == "ok" and st["issues"]["reason"] == "issue service not started"
    assert st["issues"]["state"] == "not-configured"
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
    assert by["emails"]["unavailable"] is None and by["issues"]["unavailable"] is None


# ---------------------------------------------------------------- API + CLI


@pytest.fixture
def client(seeded_db: Path, cfg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
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
