"""GitLab issue provider (Step 11) — the ``glab api`` wrapper over a subprocess
stub, its selection from config, and the unchanged sync rules driven by it.

Hermetic like ``tests/test_issues.py``: ``subprocess.run`` is stubbed and
answers with **recorded** ``glab api`` output. The JSON is synthetic — shaped
after GitLab's REST v4 issue / user objects, on an invented host and group —
because no GitLab host or ``glab`` is available where this was built; no test
spawns ``glab`` or touches the network. The GitHub path keeps its own tests,
unchanged, in ``tests/test_issues.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src import db as dbmod
from src import tasks_repo as repo
from src.config import AppConfig, IssuesConfig, load_config
from src.issue_sync import SYNC_ACTOR, sync_once
from src.issues import IssueProviderError, get_provider
from src.issues.github import GitHubProvider
from src.issues.gitlab import GitLabProvider

HOST = "gitlab.example.com"
GROUP = "example-group/platform"


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture
def glab(monkeypatch: pytest.MonkeyPatch):
    """Stub ``subprocess.run`` for the ``glab`` wrapper; ``glab.calls`` records argv, ``glab.answer`` scripts replies."""
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

    monkeypatch.setattr("src.issues.gitlab.subprocess.run", fake_run)
    monkeypatch.setattr("src.issues.gitlab.shutil.which", lambda _: "C:/glab.exe")

    class Handle:
        @staticmethod
        def answer(*items: Any) -> None:
            answers.extend(items)

    Handle.calls = calls  # type: ignore[attr-defined]
    return Handle


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db(path)
    c = dbmod.connect(path)
    yield c
    c.close()


def _issue(project: str, iid: int, title: str, *, state: str = "opened", labels: list[Any] | None = None,
           description: str | None = "", updated_at: str = "2026-09-10T08:00:00.000Z") -> dict[str, Any]:
    """One issue object as ``GET /groups/:id/issues`` / ``GET /projects/:id/issues/:iid`` return it."""
    return {
        "id": 90000 + iid, "iid": iid, "project_id": 700, "title": title, "description": description,
        "state": state, "created_at": "2026-09-01T08:00:00.000Z", "updated_at": updated_at,
        "closed_at": None if state == "opened" else updated_at, "labels": labels or [],
        "assignees": [{"id": 42, "username": "sam.example"}], "author": {"id": 42, "username": "sam.example"},
        "web_url": f"https://{HOST}/{project}/-/issues/{iid}",
        "references": {"short": f"#{iid}", "relative": f"#{iid}", "full": f"{project}#{iid}"},
    }


GARDEN = f"{GROUP}/garden-bot"
DASH = f"{GROUP}/tools/home-dashboard"            # a project in a sub-group: a three-plus-segment path

# `--paginate` prints one JSON document per page, back to back.
PAGE_1 = json.dumps([_issue(GARDEN, 14, "Add soil-moisture sensor", labels=["enhancement", "sensors"],
                            description="Read the sensor every 10 min.\n")])
PAGE_2 = json.dumps([_issue(DASH, 3, "Dark theme contrast", description=None,
                            labels=[{"id": 1, "name": "bug", "color": "#d9534f"}])])
VIEW_CLOSED = json.dumps(_issue(GARDEN, 14, "Add soil-moisture sensor", state="closed",
                                updated_at="2026-09-11T09:00:00.000Z"))
USER_ME = json.dumps({"id": 42, "username": "sam.example", "name": "Sam Example", "state": "active"})


def test_gitlab_provider_over_recorded_glab_json(glab) -> None:
    p = GitLabProvider(GROUP, "@me", HOST)
    assert p.is_configured() == (True, None)

    glab.answer(_Proc(stdout=PAGE_1 + "\n" + PAGE_2 + "\n"))
    issues = p.list_open_assigned()
    argv = glab.calls[0]
    assert argv[:5] == ["glab", "api", "--hostname", HOST, "--paginate"]
    endpoint = argv[-1]
    assert endpoint.startswith("groups/example-group%2Fplatform/issues?")
    assert "state=opened" in endpoint and "scope=assigned_to_me" in endpoint and "per_page=100" in endpoint
    assert [i.ref for i in issues] == [f"{GARDEN}#14", f"{DASH}#3"]
    assert issues[0].provider == "gitlab" and issues[0].state == "open" and issues[0].number == 14
    assert issues[0].labels == ("enhancement", "sensors") and issues[1].labels == ("bug",)
    assert issues[0].url == f"https://{HOST}/{GARDEN}/-/issues/14" and issues[1].body is None

    glab.answer(_Proc(stdout=VIEW_CLOSED))
    got = p.get(GARDEN, 14)
    assert glab.calls[1] == ["glab", "api", "--hostname", HOST, "projects/example-group%2Fplatform%2Fgarden-bot/issues/14"]
    assert got.state == "closed" and got.repo == GARDEN and got.updated_at == "2026-09-11T09:00:00.000Z"

    # create: the assignee's id once (`GET user`), then one POST that answers with the issue — no read-back
    glab.answer(_Proc(stdout=USER_ME), _Proc(stdout=json.dumps(_issue(GARDEN, 31, "New from a task", description="body text"))))
    made = p.create(GARDEN, "New from a task", "body text")
    assert glab.calls[2] == ["glab", "api", "--hostname", HOST, "user"]
    post = glab.calls[3]
    assert post[:6] == ["glab", "api", "--hostname", HOST, "-X", "POST"]
    assert post[-1] == "projects/example-group%2Fplatform%2Fgarden-bot/issues"
    assert "title=New from a task" in post and "description=body text" in post and post[post.index("-F") + 1] == "assignee_id=42"
    assert made.number == 31 and made.state == "open" and made.url.endswith("/-/issues/31")
    glab.answer(_Proc(stdout=json.dumps(_issue(GARDEN, 32, "Second"))))
    p.create(GARDEN, "Second", "")
    assert len(glab.calls) == 5 and glab.calls[4][-1].endswith("/issues")         # the id is cached


def test_gitlab_provider_by_username_and_default_host(glab) -> None:
    p = GitLabProvider("example-group", "sam.example", "")
    assert p.host == "gitlab.com"
    glab.answer(_Proc(stdout="[]"))
    assert p.list_open_assigned() == []
    assert glab.calls[0][3] == "gitlab.com"
    assert "scope=all" in glab.calls[0][-1] and "assignee_username=sam.example" in glab.calls[0][-1]
    glab.answer(_Proc(stdout="[]"))
    with pytest.raises(IssueProviderError) as exc:
        p.create("example-group/garden-bot", "t", "b")
    assert exc.value.code == "not_found" and glab.calls[1][-1] == "users?username=sam.example"


@pytest.mark.parametrize(
    ("answer", "code", "needle"),
    [
        (FileNotFoundError("glab"), "not_installed", "glab not on PATH"),
        (subprocess.TimeoutExpired(cmd="glab", timeout=20), "timeout", "timed out"),
        (_Proc(stderr="glab: 401 Unauthorized (HTTP 401)\n", returncode=1), "not_authenticated", "401 Unauthorized"),
        (_Proc(stderr="glab: 429 Too Many Requests (HTTP 429)\n", returncode=1), "rate_limited", "Too Many Requests"),
        (_Proc(stderr="glab: 404 Group Not Found (HTTP 404)\n", returncode=1), "not_found", "404 Group Not Found"),
        (_Proc(stderr="something else broke\n", returncode=1), "error", "something else"),
        (_Proc(stdout="<html>proxy error</html>"), "error", "unparseable JSON"),
    ],
)
def test_gitlab_provider_names_the_failure(glab, answer: Any, code: str, needle: str) -> None:
    p = GitLabProvider(GROUP, host=HOST)
    glab.answer(answer)
    with pytest.raises(IssueProviderError) as exc:
        p.list_open_assigned()
    assert exc.value.code == code and needle in str(exc.value)


def test_gitlab_provider_not_configured_states(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.issues.gitlab.shutil.which", lambda _: "C:/glab.exe")
    assert GitLabProvider("").is_configured() == (False, "issues.owner (the GitLab group) is not set in config")
    monkeypatch.setattr("src.issues.gitlab.shutil.which", lambda _: None)
    assert GitLabProvider(GROUP).is_configured() == (False, "glab not on PATH — install the GitLab CLI")


def test_config_switches_the_provider_and_github_ignores_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TASKOS_ISSUE_PROVIDER", raising=False)
    second = tmp_path / "config.json"
    second.write_text(json.dumps({"site": "second", "issues": {
        "provider": "gitlab", "host": HOST, "owner": GROUP, "assignee": "@me", "sync_minutes": 15}}), encoding="utf-8")
    cfg = load_config(second)
    assert cfg.site == "second" and cfg.issues.host == HOST
    p = get_provider(cfg)
    assert isinstance(p, GitLabProvider) and (p.group, p.assignee, p.host) == (GROUP, "@me", HOST)

    home = tmp_path / "home.json"
    home.write_text(json.dumps({"issues": {"provider": "github", "owner": "example", "assignee": "@me"}}), encoding="utf-8")
    assert load_config(home).issues.host == ""                      # absent key → blank
    gh = get_provider(AppConfig(issues=IssuesConfig(provider="github", owner="example", host=HOST)))
    assert isinstance(gh, GitHubProvider) and (gh.owner, gh.assignee) == ("example", "@me")


def test_sync_over_gitlab_creates_closes_and_leaves_github_refs_alone(conn, glab) -> None:
    home = repo.create_task(conn, "A GitHub-synced task", actor="test")
    repo.set_issue_ref(conn, home["id"], provider="github", repo="example/garden-bot", number=14,
                       url="https://github.com/example/garden-bot/issues/14", state="open", actor="test")
    p = GitLabProvider(GROUP, "@me", HOST)

    glab.answer(_Proc(stdout=PAGE_1 + PAGE_2))
    first = sync_once(conn, p)
    assert (first.listed, first.created, first.checked) == (2, 2, 0)        # the GitHub ref is not this provider's
    tasks = {repo.get_task(conn, i)["code"]: repo.get_task(conn, i) for i in first.created_ids}
    garden = tasks["garden-bot#14"]
    assert garden["type"] == "coding" and garden["status"] == "todo" and garden["created_by"] == SYNC_ACTOR
    assert garden["issue_ref"]["provider"] == "gitlab" and garden["issue_ref"]["repo"] == GARDEN
    assert garden["issue_ref"]["url"] == f"https://{HOST}/{GARDEN}/-/issues/14"
    assert garden["description"] == "Read the sensor every 10 min."
    assert "home-dashboard#3" in tasks

    # closed on the forge: gone from the list, confirmed with one read → the task is done
    glab.answer(_Proc(stdout=PAGE_2), _Proc(stdout=VIEW_CLOSED))
    second = sync_once(conn, p)
    assert (second.closed, second.closed_ids) == (1, [garden["id"]])
    assert glab.calls[-1][-1] == "projects/example-group%2Fplatform%2Fgarden-bot/issues/14"
    assert repo.get_task(conn, garden["id"])["status"] == "done"
    untouched = repo.get_task(conn, home["id"])
    assert untouched["issue_ref"]["provider"] == "github" and untouched["issue_ref"]["state"] == "open"
    assert len(glab.calls) == 3
