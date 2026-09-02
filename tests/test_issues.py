"""Issues as tasks (Step 8) — the provider contract, the GitHub ``gh`` wrapper
over a subprocess stub, the sync rules, the routes and the CLI.

Everything is hermetic: the fake provider (``src/issues/fake.py``) over a
temp JSON file stands in for the forge; the GitHub provider is exercised
against a stubbed ``subprocess.run`` with recorded ``gh`` JSON — no test
spawns ``gh``, no test touches the network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import cli
from src import db as dbmod
from src import tasks_repo as repo
from src.config import load_config
from src.issue_sync import (
    SYNC_ACTOR,
    AlreadyLinked,
    IssuesDisabled,
    IssueSyncService,
    issue_from_task,
    sync_once,
)
from src.issues import FAKE_PATH_ENV, PROVIDER_ENV, IssueProviderError, NullProvider, get_provider
from src.issues.fake import FakeProvider
from src.issues.github import GitHubProvider

# ------------------------------------------------------------------ fixtures

ISSUE_A = {"repo": "example/garden-bot", "number": 14, "title": "Add soil-moisture sensor", "state": "open",
           "url": "https://github.com/example/garden-bot/issues/14", "labels": ["enhancement"],
           "updated_at": "2026-08-17T07:00:00Z", "body": "  Read the sensor every 10 min.\r\n\r\n"}
ISSUE_B = {"repo": "example/home-dashboard", "number": 3, "title": "Dark theme contrast", "state": "open",
           "url": "https://github.com/example/home-dashboard/issues/3", "labels": ["bug", "design"], "body": ""}


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db(path)
    c = dbmod.connect(path)
    yield c
    c.close()


@pytest.fixture
def fake(tmp_path: Path) -> FakeProvider:
    return FakeProvider.from_issues(tmp_path / "forge.json", [dict(ISSUE_A), dict(ISSUE_B)])


def _set(fake: FakeProvider, **changes: Any) -> None:
    """Edit one issue in the fake's file: ``_set(fake, number=14, state="closed")``."""
    data = json.loads(fake.path.read_text(encoding="utf-8"))
    for row in data["issues"]:
        if row["number"] == changes["number"] and row["repo"] == changes.get("repo", row["repo"]):
            row.update(changes)
    fake.path.write_text(json.dumps(data), encoding="utf-8")


def _activity(conn, task_id: int) -> list[tuple[str, str | None, str | None, str | None]]:
    return [(a["field"], a["old_value"], a["new_value"], a["actor"]) for a in repo.list_activity(conn, task_id)]


# ------------------------------------------------------------- the sync rules


def test_sync_creates_coding_tasks_in_todo_and_dedupes(conn, fake: FakeProvider) -> None:
    r = sync_once(conn, fake)
    assert (r.listed, r.created, r.unchanged) == (2, 2, 0)
    tasks = repo.list_tasks(conn, type="coding")
    assert len(tasks) == 2
    a = next(t for t in tasks if t["issue_ref"]["number"] == 14)
    assert a["title"] == "Add soil-moisture sensor"
    assert a["code"] == "garden-bot#14"                       # short repo name + number
    assert a["status"] == "todo" and a["type"] == "coding" and a["created_by"] == SYNC_ACTOR
    assert a["issue_ref"]["repo"] == "example/garden-bot" and a["issue_ref"]["state"] == "open"
    assert a["issue_ref"]["url"] == ISSUE_A["url"] and a["issue_ref"]["last_synced"]
    detail = repo.get_task(conn, a["id"])
    assert detail["description"] == "Read the sensor every 10 min."   # trimmed
    assert [(link["kind"], link["label"]) for link in detail["links"]] == [("issue", "example/garden-bot#14")]
    fields = [f for f, *_ in _activity(conn, a["id"])]
    assert fields[-1] == "created" and "issue" in fields and "type" in fields
    assert all(act == SYNC_ACTOR for *_, act in _activity(conn, a["id"]))
    # a second pass is a no-op: same two tasks, nothing new, no extra activity
    before = len(repo.list_activity(conn, a["id"]))
    r2 = sync_once(conn, fake)
    assert (r2.listed, r2.created, r2.unchanged, r2.retitled, r2.closed) == (2, 0, 2, 0, 0)
    assert len(repo.list_tasks(conn, type="coding")) == 2
    assert len(repo.list_activity(conn, a["id"])) == before


def test_sync_title_change_lands_on_the_task(conn, fake: FakeProvider) -> None:
    sync_once(conn, fake)
    task = repo.list_tasks(conn, q="soil-moisture")[0]
    _set(fake, number=14, title="Add soil-moisture sensor to the loop")
    r = sync_once(conn, fake)
    assert r.retitled == 1
    assert repo.get_task(conn, task["id"])["title"] == "Add soil-moisture sensor to the loop"
    assert _activity(conn, task["id"])[0] == ("title", "Add soil-moisture sensor", "Add soil-moisture sensor to the loop", SYNC_ACTOR)


def test_sync_closed_issue_marks_task_done_with_sync_activity(conn, fake: FakeProvider) -> None:
    sync_once(conn, fake)
    task = repo.list_tasks(conn, q="soil-moisture")[0]
    repo.update_task(conn, task["id"], actor="me", status="doing")
    _set(fake, number=14, state="closed")
    r = sync_once(conn, fake)
    assert (r.listed, r.checked, r.closed, r.closed_ids) == (1, 1, 1, [task["id"]])
    t = repo.get_task(conn, task["id"])
    assert t["status"] == "done" and t["done_at"] and t["issue_ref"]["state"] == "closed"
    acts = _activity(conn, task["id"])
    assert ("status", "doing", "done", SYNC_ACTOR) in acts[:2]
    assert ("issue_state", "open", "closed", SYNC_ACTOR) in acts[:2]
    # closed refs are not polled again; nothing changes on the next pass
    r2 = sync_once(conn, fake)
    assert (r2.checked, r2.closed) == (0, 0)


def test_sync_closed_issue_skips_a_task_already_closed_locally(conn, fake: FakeProvider) -> None:
    sync_once(conn, fake)
    task = repo.list_tasks(conn, q="soil-moisture")[0]
    repo.update_task(conn, task["id"], actor="me", status="cancelled")
    n = len(repo.list_activity(conn, task["id"]))
    _set(fake, number=14, state="closed")
    r = sync_once(conn, fake)
    assert r.closed == 1 and r.closed_ids == []
    t = repo.get_task(conn, task["id"])
    assert t["status"] == "cancelled" and t["issue_ref"]["state"] == "closed"
    assert len(repo.list_activity(conn, task["id"])) == n + 1     # only the issue_state row


def test_sync_reopened_issue_puts_a_done_task_back_to_todo(conn, fake: FakeProvider) -> None:
    sync_once(conn, fake)
    task = repo.list_tasks(conn, q="soil-moisture")[0]
    _set(fake, number=14, state="closed")
    sync_once(conn, fake)
    assert repo.get_task(conn, task["id"])["status"] == "done"
    _set(fake, number=14, state="open")
    r = sync_once(conn, fake)
    assert r.reopened == 1
    t = repo.get_task(conn, task["id"])
    assert t["status"] == "todo" and t["done_at"] is None and t["issue_ref"]["state"] == "open"
    acts = _activity(conn, task["id"])
    assert ("status", "done", "todo", SYNC_ACTOR) in acts[:2]
    assert ("issue_state", "closed", "open", SYNC_ACTOR) in acts[:2]


def test_sync_missing_from_the_list_but_still_open_is_not_closed(conn, fake: FakeProvider) -> None:
    sync_once(conn, fake)
    task = repo.list_tasks(conn, q="soil-moisture")[0]
    _set(fake, number=14, assigned=False)          # unassigned from me: not listed, but open
    r = sync_once(conn, fake)
    assert (r.listed, r.checked, r.closed, r.unchanged) == (1, 1, 0, 2)
    t = repo.get_task(conn, task["id"])
    assert t["status"] == "todo" and t["issue_ref"]["state"] == "open"


def test_sync_lookup_error_leaves_the_task_alone_and_is_reported(conn, fake: FakeProvider) -> None:
    sync_once(conn, fake)
    task = repo.list_tasks(conn, q="soil-moisture")[0]
    data = json.loads(fake.path.read_text(encoding="utf-8"))
    data["issues"] = [row for row in data["issues"] if row["number"] != 14]   # gone from the forge entirely
    fake.path.write_text(json.dumps(data), encoding="utf-8")
    r = sync_once(conn, fake)
    assert r.checked == 1 and r.closed == 0
    assert r.errors == ["example/garden-bot#14: example/garden-bot#14 not found"]
    assert repo.get_task(conn, task["id"])["status"] == "todo"


def test_sync_a_listing_failure_changes_nothing(conn, tmp_path: Path) -> None:
    fake = FakeProvider.from_issues(tmp_path / "forge.json", [dict(ISSUE_A)], error={"code": "rate_limited", "message": "API rate limit exceeded"})
    with pytest.raises(IssueProviderError) as exc:
        sync_once(conn, fake)
    assert exc.value.code == "rate_limited"
    assert repo.list_tasks(conn, include_closed=True) == []
    # …and the service records it as a state, not a crash, without touching the DB
    service = IssueSyncService(load_config(), provider=fake)
    assert service.enabled
    assert service.run_now(conn) is None
    assert service.last_error == "API rate limit exceeded" and service.last_error_code == "rate_limited"
    st = service.status()
    assert st["enabled"] and st["last_sync"] is None and st["last_error_code"] == "rate_limited"


def test_manually_linked_ref_without_state_is_confirmed_and_filled(conn, fake: FakeProvider) -> None:
    t = repo.create_task(conn, "Track the sensor work")
    repo.set_issue_ref(conn, t["id"], provider="github", repo="example/garden-bot", number=14)   # no url / state
    r = sync_once(conn, fake)
    assert r.created == 1                                    # only home-dashboard#3 is new
    ref = repo.get_task(conn, t["id"])["issue_ref"]
    assert ref["state"] == "open" and ref["url"] == ISSUE_A["url"] and ref["last_synced"]
    assert repo.get_task(conn, t["id"])["title"] == "Add soil-moisture sensor"   # the issue title is canonical


def test_issue_from_task_is_the_one_create_workflow(conn, fake: FakeProvider) -> None:
    """``POST /api/tasks/{id}/issue`` and ``tasks issue create`` run this one
    function (issue #35) — so the CLI path gained the two steps only the route
    used to take: the repo is normalized before it reaches the provider, and
    the sync cache is warmed with the new issue (the drawer panel reads it
    before the next pass). The guards raise the repo's own error family, which
    is what lets each front end keep its own dialect."""
    service = IssueSyncService(load_config(), provider=fake)
    assert service.enabled and service.cache == {}
    t = repo.create_task(conn, "Wire the rain sensor", description="Needs a pull-up.")

    updated = issue_from_task(conn, t["id"], "  example/garden-bot/  ", service=service, actor="tester")
    assert updated["type"] == "coding" and updated["code"] == "garden-bot#15"
    ref = updated["issue_ref"]
    assert ref["repo"] == "example/garden-bot"                       # normalized, not "  example/garden-bot/  "
    assert ref["number"] == 15 and ref["url"] == "https://github.com/example/garden-bot/issues/15"
    assert [link["kind"] for link in updated["links"]] == ["issue"]
    assert service.cache[("github", "example/garden-bot", 15)].title == "Wire the rain sensor"

    with pytest.raises(AlreadyLinked):
        issue_from_task(conn, t["id"], "example/garden-bot", service=service, actor="tester")
    other = repo.create_task(conn, "Something else")
    with pytest.raises(repo.ValidationError):
        issue_from_task(conn, other["id"], "nope", service=service, actor="tester")
    with pytest.raises(IssuesDisabled):
        issue_from_task(conn, other["id"], "example/garden-bot", service=None, actor="tester")
    with pytest.raises(repo.NotFound):
        issue_from_task(conn, other["id"] + 1000, "example/garden-bot", service=service, actor="tester")


# --------------------------------------------------------- service + provider


def test_service_not_configured_states(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = load_config()
    monkeypatch.setenv(PROVIDER_ENV, "none")
    p = get_provider(config)
    assert isinstance(p, NullProvider) and p.is_configured()[0] is False
    service = IssueSyncService(config)
    assert not service.enabled and "TASKOS_ISSUE_PROVIDER=none" in (service.reason or "")
    assert service.run_now() is None and service.status()["enabled"] is False
    service.start()                                            # a disabled service never starts a thread
    assert service.status()["running"] is False
    monkeypatch.setenv(PROVIDER_ENV, "fake")
    monkeypatch.delenv(FAKE_PATH_ENV, raising=False)
    assert isinstance(get_provider(config), NullProvider)
    monkeypatch.setenv(FAKE_PATH_ENV, str(tmp_path / "forge.json"))
    fake = get_provider(config)
    assert isinstance(fake, FakeProvider) and fake.is_configured() == (False, f"fake provider file missing: {tmp_path / 'forge.json'}")
    monkeypatch.delenv(PROVIDER_ENV)
    from src.config import AppConfig, IssuesConfig

    assert isinstance(get_provider(AppConfig(issues=IssuesConfig(provider="gitlab"))), NullProvider)   # not yet
    assert isinstance(get_provider(AppConfig(issues=IssuesConfig(provider=""))), NullProvider)
    gh = get_provider(AppConfig(issues=IssuesConfig(provider="github", owner="")))
    assert isinstance(gh, GitHubProvider) and gh.is_configured() == (False, "issues.owner is not set in config")


def test_service_thread_runs_the_first_pass_after_the_delay(conn, fake: FakeProvider) -> None:
    import time

    service = IssueSyncService(load_config(), provider=fake, initial_delay=0.2, interval_minutes=1)
    service.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and service.last_sync is None:
            time.sleep(0.05)
        assert service.last_sync is not None
        assert service.last_result and service.last_result.created == 2
        assert service.status()["running"] is True and service.status()["repos"] == ["example/garden-bot", "example/home-dashboard"]
        assert service.cached("github", "example/garden-bot", 14).labels == ("enhancement",)
    finally:
        service.stop()
    assert service.status()["running"] is False


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch):
    """Stub ``subprocess.run`` for the ``gh`` wrapper; ``gh.calls`` records argv, ``gh.answer`` scripts replies."""
    calls: list[list[str]] = []
    answers: list[Any] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs["timeout"] == 20.0 and kwargs["capture_output"] and kwargs["encoding"] == "utf-8"
        assert "creationflags" in kwargs
        nxt = answers.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    monkeypatch.setattr("src.issues.github.subprocess.run", fake_run)
    monkeypatch.setattr("src.issues.github.shutil.which", lambda _: "C:/gh.exe")

    class Handle:
        @staticmethod
        def answer(*items: Any) -> None:
            answers.extend(items)

    Handle.calls = calls  # type: ignore[attr-defined]
    return Handle


SEARCH_JSON = json.dumps([
    {"number": 9, "title": "Step 8/13 — issues", "url": "https://github.com/ferraroroberto/task-os/issues/9",
     "state": "open", "labels": [{"name": "enhancement", "color": "a2eeef"}, {"name": "step"}],
     "updatedAt": "2026-08-17T07:56:47Z", "body": "## Summary\n…",
     "repository": {"name": "task-os", "nameWithOwner": "ferraroroberto/task-os"}},
    {"number": 227, "title": "brand: icon", "url": "https://github.com/ferraroroberto/project-scaffolding/issues/227",
     "state": "open", "labels": [], "updatedAt": "2026-08-17T07:00:00Z", "body": None,
     "repository": {"name": "project-scaffolding", "nameWithOwner": "ferraroroberto/project-scaffolding"}},
])
VIEW_JSON = json.dumps({"number": 9, "title": "Step 8/13 — issues", "url": "https://github.com/ferraroroberto/task-os/issues/9",
                        "state": "CLOSED", "labels": [{"name": "enhancement"}], "updatedAt": "2026-08-18T09:00:00Z", "body": "done"})


def test_github_provider_over_recorded_gh_json(gh) -> None:
    p = GitHubProvider("ferraroroberto", "@me")
    assert p.is_configured() == (True, None)
    gh.answer(_Proc(stdout=SEARCH_JSON))
    issues = p.list_open_assigned()
    assert gh.calls[0][:9] == ["gh", "search", "issues", "--assignee", "@me", "--state", "open", "--owner", "ferraroroberto"]
    assert "--json" in gh.calls[0] and "repository" in gh.calls[0][-1]
    assert [i.ref for i in issues] == ["ferraroroberto/task-os#9", "ferraroroberto/project-scaffolding#227"]
    assert issues[0].labels == ("enhancement", "step") and issues[0].state == "open" and issues[0].provider == "github"
    assert issues[1].body is None
    gh.answer(_Proc(stdout=VIEW_JSON))
    got = p.get("ferraroroberto/task-os", 9)
    assert gh.calls[1] == ["gh", "issue", "view", "9", "--repo", "ferraroroberto/task-os", "--json", "number,title,url,state,labels,updatedAt,body"]
    assert got.state == "closed" and got.repo == "ferraroroberto/task-os" and got.labels == ("enhancement",)
    # create: the URL on stdout → number → one read-back
    gh.answer(_Proc(stdout="https://github.com/ferraroroberto/task-os/issues/31\n"), _Proc(stdout=VIEW_JSON.replace('"number": 9', '"number": 31').replace("issues/9", "issues/31")))
    made = p.create("ferraroroberto/task-os", "New from a task", "body text")
    assert gh.calls[2][:5] == ["gh", "issue", "create", "--repo", "ferraroroberto/task-os"]
    assert gh.calls[2][gh.calls[2].index("--title") + 1] == "New from a task" and gh.calls[2][-2:] == ["--assignee", "@me"]
    assert made.number == 31 and made.url.endswith("/issues/31")


@pytest.mark.parametrize(
    ("answer", "code", "needle"),
    [
        (FileNotFoundError("gh"), "not_installed", "gh not on PATH"),
        (subprocess.TimeoutExpired(cmd="gh", timeout=20), "timeout", "timed out"),
        (_Proc(stderr="To get started with GitHub CLI, please run:  gh auth login\n", returncode=4), "not_authenticated", "gh auth login"),
        (_Proc(stderr="HTTP 403: API rate limit exceeded for user (https://api.github.com/search/issues)\n", returncode=1), "rate_limited", "rate limit"),
        (_Proc(stderr="GraphQL: Could not resolve to an Issue with the number of 999. (repository.issue)\n", returncode=1), "not_found", "Could not resolve"),
        (_Proc(stderr="something else broke\n", returncode=1), "error", "something else"),
    ],
)
def test_github_provider_names_the_failure(gh, answer: Any, code: str, needle: str) -> None:
    p = GitHubProvider("ferraroroberto")
    gh.answer(answer)
    with pytest.raises(IssueProviderError) as exc:
        p.list_open_assigned()
    assert exc.value.code == code and needle in str(exc.value)


def test_github_provider_not_configured_without_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.issues.github.shutil.which", lambda _: None)
    assert GitHubProvider("ferraroroberto").is_configured() == (False, "gh not on PATH — install the GitHub CLI")


# ---------------------------------------------------------- routes + CLI


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeProvider) -> TestClient:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    monkeypatch.setenv(PROVIDER_ENV, "fake")
    monkeypatch.setenv(FAKE_PATH_ENV, str(fake.path))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def test_routes_status_sync_create_link_unlink(client: TestClient, fake: FakeProvider) -> None:
    st = client.get("/api/issues/status").json()
    assert st["provider"] == "github" and st["enabled"] is True and st["last_sync"] is None and st["repos"] == []
    r = client.post("/api/issues/sync")
    assert r.status_code == 200 and r.json()["created"] == 2
    st = client.get("/api/issues/status").json()
    assert st["last_sync"] and st["last_result"]["listed"] == 2 and st["repos"] == ["example/garden-bot", "example/home-dashboard"]
    todo = client.get("/api/tasks?status=todo").json()["items"]
    assert sorted(t["code"] for t in todo) == ["garden-bot#14", "home-dashboard#3"]
    a = next(t for t in todo if t["code"] == "garden-bot#14")
    panel = client.get(f"/api/tasks/{a['id']}/issue").json()
    assert panel["ref"]["state"] == "open" and panel["info"]["labels"] == ["enhancement"]
    # tree nodes carry the ref too (the Tree renders the chip)
    tree = client.get("/api/tasks/tree").json()["items"]
    assert any(n.get("issue_ref") and n["issue_ref"]["number"] == 14 for n in tree)

    # create an issue from a plain task → linked, coding, code set, link row
    plain = client.post("/api/tasks", json={"title": "Wire the rain sensor", "description": "Needs a pull-up."}).json()
    made = client.post(f"/api/tasks/{plain['id']}/issue", json={"repo": "example/garden-bot"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["type"] == "coding" and body["code"] == "garden-bot#15" and body["issue_ref"]["number"] == 15
    assert body["issue_ref"]["url"] == "https://github.com/example/garden-bot/issues/15" and body["issue_ref"]["state"] == "open"
    assert [link["kind"] for link in body["links"]] == ["issue"]
    forge = json.loads(fake.path.read_text(encoding="utf-8"))["issues"]
    assert forge[-1] == {"repo": "example/garden-bot", "number": 15, "title": "Wire the rain sensor", "state": "open",
                         "url": "https://github.com/example/garden-bot/issues/15", "labels": [], "body": "Needs a pull-up.",
                         "updated_at": None, "assigned": True}
    again = client.post(f"/api/tasks/{plain['id']}/issue", json={"repo": "example/garden-bot"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_linked"
    bad = client.post(f"/api/tasks/{a['id'] + 100}/issue", json={"repo": "x/y"})
    assert bad.status_code == 404
    # unlink → plain task again; the issue is untouched on the forge
    un = client.delete(f"/api/tasks/{plain['id']}/issue")
    assert un.status_code == 200 and un.json()["type"] == "task" and un.json()["issue_ref"] is None
    assert json.loads(fake.path.read_text(encoding="utf-8"))["issues"][-1]["state"] == "open"
    # link an existing one → the next sync fills state/url
    lk = client.put(f"/api/tasks/{plain['id']}/issue", json={"repo": "example/garden-bot", "number": 15})
    assert lk.status_code == 200 and lk.json()["type"] == "coding"
    client.post("/api/issues/sync")
    assert client.get(f"/api/tasks/{plain['id']}").json()["issue_ref"]["state"] == "open"


def test_routes_report_not_configured_and_provider_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    monkeypatch.setenv(PROVIDER_ENV, "none")
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        st = c.get("/api/issues/status").json()
        assert st["enabled"] is False and "TASKOS_ISSUE_PROVIDER=none" in st["reason"]
        r = c.post("/api/issues/sync")
        assert r.status_code == 409 and r.json()["error"]["code"] == "issues_disabled"
        t = c.post("/api/tasks", json={"title": "x"}).json()
        r = c.post(f"/api/tasks/{t['id']}/issue", json={"repo": "a/b"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "issues_disabled"
    fake = FakeProvider.from_issues(tmp_path / "forge.json", [], error={"code": "not_authenticated", "message": "gh auth login"})
    monkeypatch.setenv(PROVIDER_ENV, "fake")
    monkeypatch.setenv(FAKE_PATH_ENV, str(fake.path))
    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        r = c.post("/api/issues/sync")
        assert r.status_code == 502 and r.json()["error"] == {"code": "provider_error", "message": "gh auth login", "detail": {"code": "not_authenticated"}}
        st = c.get("/api/issues/status").json()
        assert st["last_error_code"] == "not_authenticated" and st["last_sync"] is None
        t = c.post("/api/tasks", json={"title": "x"}).json()
        r = c.post(f"/api/tasks/{t['id']}/issue", json={"repo": "a/b"})
        assert r.status_code == 502 and r.json()["error"]["detail"] == {"code": "not_authenticated"}
        r = c.post(f"/api/tasks/{t['id']}/issue", json={"repo": "nope"})
        assert r.status_code == 422


def test_cli_issues_sync_status_and_issue_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, fake: FakeProvider) -> None:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    monkeypatch.setenv(PROVIDER_ENV, "fake")
    monkeypatch.setenv(FAKE_PATH_ENV, str(fake.path))
    dbmod.init_db()

    def run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv), backend=cli.LocalBackend(actor="tester"))
        out = capsys.readouterr()
        return code, out.out, out.err

    code, out, _ = run("issues", "status")
    assert code == 0 and out.startswith("issues   github · every 10 min · last sync -")
    code, out, _ = run("issues", "sync")
    assert code == 0 and "2 open issue(s) · 2 new" in out and "new: #1" in out and "new: #2" in out
    code, out, _ = run("issues", "sync", "--json")
    assert code == 0 and json.loads(out)["unchanged"] == 2
    code, out, _ = run("add", "Wire the rain sensor", "--desc", "Needs a pull-up.")
    assert code == 0
    code, out, _ = run("issue", "create", "3", "--repo", "example/garden-bot")
    assert code == 0 and out.strip() == "#3 → example/garden-bot#15 https://github.com/example/garden-bot/issues/15"
    code, out, _ = run("show", "3")
    assert "coding" in out and "example/garden-bot#15" in out
    code, out, err = run("issue", "create", "3", "--repo", "example/garden-bot")
    assert code == 1 and "already linked" in err
    code, out, err = run("issue", "create", "3", "--repo", "nope")
    assert code == 1
    # the CLI runs the route's workflow (issue #35) → it normalizes the repo too
    code, out, _ = run("add", "Sensor housing")
    assert code == 0
    code, out, _ = run("issue", "create", "4", "--repo", "  example/garden-bot/  ")
    assert code == 0 and out.strip() == "#4 → example/garden-bot#16 https://github.com/example/garden-bot/issues/16"
    monkeypatch.setenv(PROVIDER_ENV, "none")
    code, out, err = run("issues", "sync")
    assert code == 1 and "TASKOS_ISSUE_PROVIDER=none" in err
    code, out, _ = run("issues")
    assert code == 0 and out.startswith("issues   none: not configured")
