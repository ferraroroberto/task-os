"""``tasks`` CLI — every subcommand, human and ``--json``, local and HTTP backends.

The HTTP backend is exercised through a transport bound to the FastAPI
``TestClient`` (no socket), so both code paths run hermetically against the
same temp database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src import cli
from src import db as dbmod
from tests.fixtures.seed import PINNED_ANCHOR, seed_db

Runner = Callable[..., tuple[int, str, str]]


@pytest.fixture(params=["local", "http"])
def run(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> Runner:
    """``run(*argv) → (exit_code, stdout, stderr)`` against a fresh temp DB, per backend."""
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db()

    if request.param == "local":
        backend = cli.LocalBackend(actor="tester")
    else:
        from app.webapp.server import create_app

        client = TestClient(create_app(), client=("127.0.0.1", 50000))
        client.__enter__()
        request.addfinalizer(lambda: client.__exit__(None, None, None))

        def transport(method: str, url_path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
            res = client.request(method, url_path, json=body, headers={"X-Actor": "tester"})
            return res.status_code, (res.json() if res.content else None)

        backend = cli.HttpBackend("http://testserver", actor="tester", transport=transport)

    def _run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv), backend=backend)
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def _json(text: str) -> Any:
    return json.loads(text)


def test_story_02_add_nest_comment_tree_due_show(run: Runner) -> None:
    code, out, _ = run("add", "Renew passport", "--due", "2026-08-21")
    assert code == 0 and out.startswith("added #1  Renew passport  (due 2026-08-21)")
    code, out, _ = run("add", "Book appointment", "--parent", "1", "--json")
    t2 = _json(out)
    assert code == 0 and t2["id"] == 2 and t2["parent_id"] == 1
    code, out, _ = run("comment", "2", "called the office")
    assert code == 0 and "called the office" in out
    code, out, _ = run("tree")
    assert code == 0
    assert out.splitlines() == ["#1  Renew passport  (due 2026-08-21)", "  #2  Book appointment"]
    code, out, _ = run("due", "2", "2026-09-01")
    assert code == 0 and out.strip() == "#2 due → 2026-09-01"
    code, out, _ = run("show", "2")
    assert code == 0
    assert "in: Renew passport" in out
    assert "(cli): called the office" in out
    assert "tester  due: ∅ → 2026-09-01" in out
    code, out, _ = run("show", "2", "--json")
    show = _json(out)
    assert show["comments"][0]["origin"] == "cli" and show["comments"][0]["author"] == "tester"
    assert (show["activity"][0]["field"], show["activity"][0]["old_value"], show["activity"][0]["new_value"]) == ("due", None, "2026-09-01")


def test_natural_dates_and_clear(run: Runner) -> None:
    today = date.today()
    code, out, _ = run("add", "Soon", "--due", "tomorrow", "--json")
    assert code == 0 and _json(out)["due"] == (today + timedelta(days=1)).isoformat()
    code, out, _ = run("add", "Later", "--due", "in 2 weeks", "--json")
    assert _json(out)["due"] == (today + timedelta(days=14)).isoformat()
    code, out, _ = run("due", "1", "none", "--json")
    assert code == 0 and _json(out)["due"] is None
    code, out, err = run("due", "1", "someday")
    assert code == 1 and "cannot parse date" in err
    code, out, _ = run("due", "1", "someday", "--json")
    assert code == 1 and _json(out)["error"]["code"] == "bad_date"


def test_starts_and_deferred_over_both_backends(run: Runner) -> None:
    """#87 CLI parity: `--starts`, `tasks starts N`, `tasks ls --deferred` —
    identical `--json` whether the app answers or the DB is opened directly."""
    today = date.today()
    soon = (today + timedelta(days=20)).isoformat()
    code, out, _ = run("add", "Book boiler service", "--due", "in 40 days",
                       "--starts", "in 20 days", "--json")
    assert code == 0 and _json(out)["starts"] == soon
    run("add", "Awake")

    # sleeping tasks are out of `ls` and are exactly what `--deferred` lists
    code, out, _ = run("ls", "--json")
    assert code == 0 and [t["title"] for t in _json(out)] == ["Awake"]
    code, out, _ = run("ls", "--deferred", "--json")
    assert code == 0 and [t["title"] for t in _json(out)] == ["Book boiler service"]
    code, out, _ = run("ls", "--status", "all", "--json")     # "all" means all
    assert code == 0 and len(_json(out)) == 2
    # …but `show` always finds it, and says when it starts
    code, out, _ = run("show", "1")
    assert code == 0 and f"starts {soon}" in out

    # `tasks starts` sets and clears, same vocabulary as `tasks due`
    code, out, _ = run("starts", "1", "tomorrow", "--json")
    assert code == 0 and _json(out)["starts"] == (today + timedelta(days=1)).isoformat()
    code, out, _ = run("starts", "1", "none")
    assert code == 0 and out.strip() == "#1 starts → none"
    code, out, _ = run("ls", "--json")
    assert {t["title"] for t in _json(out)} == {"Awake", "Book boiler service"}
    code, out, err = run("starts", "1", "someday", "--json")
    assert code == 1 and _json(out)["error"]["code"] == "bad_date"


def test_ls_filters_done_move_search_people(run: Runner) -> None:
    run("add", "Project")
    run("add", "Child A", "--parent", "1", "--due", "today", "--priority", "high")
    run("add", "Child B", "--parent", "1", "--due", "2020-01-01")
    run("add", "Chore", "--recurrence", "weekly", "--due", "2026-08-31")
    code, out, _ = run("ls", "--json")
    assert code == 0 and [t["title"] for t in _json(out)] == ["Child B", "Child A", "Chore", "Project"]
    code, out, _ = run("ls", "--project", "1", "--json")
    assert {t["title"] for t in _json(out)} == {"Child A", "Child B"}
    code, out, _ = run("ls", "--due", "overdue", "--json")
    assert [t["title"] for t in _json(out)] == ["Child B"]
    code, out, _ = run("ls", "--due", "today")
    assert "Child A" in out and "Child B" not in out
    code, out, _ = run("done", "4")
    assert code == 0 and "next due 2026-09-07" in out
    code, out, _ = run("done", "3")
    assert code == 0 and out.strip() == "#3 done"
    code, out, _ = run("ls", "--status", "done", "--json")
    assert [t["id"] for t in _json(out)] == [3]
    code, out, _ = run("ls", "--status", "all", "--json")
    assert len(_json(out)) == 4
    code, out, _ = run("move", "2", "--parent", "root")
    assert code == 0 and out.strip() == "#2 moved → top level"
    code, out, err = run("move", "1", "--parent", "3", "--json")   # 3 is still under 1
    assert code == 1 and _json(out)["error"]["code"] == "cycle"
    code, out, err = run("move", "1", "--parent", "3")
    assert code == 1 and "cycle" in err
    code, out, _ = run("comment", "2", "note about the archive box")
    code, out, _ = run("search", "archive")
    assert code == 0 and "#2  Child A" in out and "comment: note about the [archive] box" in out
    assert "folders: not configured" in out and "emails: not configured" in out and "issues: not configured" in out
    code, out, _ = run("search", "nothing-here", "--json", "--kind", "tasks")
    assert code == 0
    groups = {g["kind"]: g for g in _json(out)["groups"]}
    assert groups["tasks"]["hits"] == [] and groups["tasks"]["configured"] is True
    assert groups["emails"]["skipped"] is True and groups["emails"]["configured"] is False
    code, out, _ = run("people")
    assert code == 0 and out.strip() == "(no people)"
    code, out, err = run("add", "With person", "--person", "Nobody")
    assert code == 1 and "not found" in err
    code, out, err = run("show", "99")
    assert code == 1 and "task 99 not found" in err
    code, out, err = run("show", "99", "--json")
    assert code == 1 and _json(out)["error"]["code"] == "not_found"


def test_seeded_show_and_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "seed.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    seed_db(path, PINNED_ANCHOR)
    backend = cli.LocalBackend(actor="tester")
    assert cli.main(["tree", "1"], backend=backend) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("#1  Home renovation") and lines[1].startswith("  #2  Kitchen")
    assert cli.main(["show", "3"], backend=backend) == 0
    out = capsys.readouterr().out
    assert "in: Home renovation › Kitchen" in out and "@Sam Rivera" in out and "links:" not in out
    assert cli.main(["show", "2"], backend=backend) == 0
    assert "[folder] Kitchen folder" in capsys.readouterr().out
    assert cli.main(["people", "--json"], backend=backend) == 0
    assert [p["name"] for p in json.loads(capsys.readouterr().out)] == ["Alex Chen", "Jordan Lee", "Sam Rivera"]
    assert cli.main(["add", "Ping", "--person", "sam rivera", "--json"], backend=backend) == 0
    assert json.loads(capsys.readouterr().out)["person"]["name"] == "Sam Rivera"


#: The one shape ``tasks mirror status --json`` emits, whatever the transport.
STATUS_KEYS = {"https", "auth", "mirror", "backup", "folders", "opener", "placeholders"}


def test_status_json_shape_is_identical_on_both_backends(run: Runner) -> None:
    """CLAUDE.md: "both backends return the API's shapes so ``--json`` is identical
    either way" — this runs under both fixture params, so a key the local path
    drops (or the HTTP path grows) fails on one of the two."""
    code, out, _ = run("mirror", "status", "--json")
    assert code == 0
    st = _json(out)
    assert set(st) == STATUS_KEYS
    assert set(st["auth"]) == {"enabled", "password", "client"}
    assert set(st["opener"]) >= {"install", "uninstall", "env_template", "installed_here", "mode"}


def test_local_status_reports_request_only_facts_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline, ``https`` / ``auth.client`` describe a request that does not exist.
    They must say so explicitly — not be omitted, and not be folded into ``False``
    (which would assert plain HTTP, a fact this process never established)."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "t.db"))
    dbmod.init_db()
    st = cli.LocalBackend(actor="tester").status()

    assert set(st) == STATUS_KEYS
    assert st["https"] == cli.UNKNOWN and st["https"] is not False
    assert st["auth"]["client"] == cli.UNKNOWN
    # everything else is a property of the install, so it is answered for real
    assert st["auth"]["enabled"] is False and st["auth"]["password"] is False
    assert isinstance(st["placeholders"], dict)
    assert st["opener"]["install"] and st["opener"]["base_url_token"] == "<base-url>"


def test_no_command_prints_help(capsys: pytest.CaptureFixture) -> None:
    assert cli.main([]) == 2
    assert "usage: tasks" in capsys.readouterr().out


def test_server_probe_false_on_closed_port() -> None:
    assert cli.server_answers("http://127.0.0.1:9", timeout=0.3) is False


def test_pick_backend_falls_back_to_local_when_app_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "t.db"))
    monkeypatch.delenv(cli.SERVER_ENV, raising=False)
    monkeypatch.setattr(cli, "server_answers", lambda base, timeout=0.0: False)
    args = cli.build_parser().parse_args(["ls"])
    assert isinstance(cli.pick_backend(args), cli.LocalBackend)
    # an explicit --server that does not answer is an error, not a silent fallback
    args = cli.build_parser().parse_args(["--server", "http://127.0.0.1:1", "ls"])
    with pytest.raises(cli.CliError):
        cli.pick_backend(args)
    # and when it answers, HTTP wins
    monkeypatch.setattr(cli, "server_answers", lambda base, timeout=0.0: True)
    args = cli.build_parser().parse_args(["ls"])
    be = cli.pick_backend(args)
    assert isinstance(be, cli.HttpBackend) and be.base.startswith("http://127.0.0.1:")
