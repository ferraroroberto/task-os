"""``your_name``: the install's own name is the author of what the web app and the CLI write."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import cli
from src import config as cfgmod
from src import db as dbmod
from tests.conftest import write_test_config

LOOPBACK = ("127.0.0.1", 50000)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, your_name: str | None, team_people: list[str]) -> Path:
    path = write_test_config(tmp_path / "config.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["team"] = {"enabled": False, "people": team_people}
    raw.pop("your_name", None)
    if your_name is not None:
        raw["your_name"] = your_name
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
    return path


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    return TestClient(create_app(), client=LOOPBACK)


def _write_comment_and_activity(c: TestClient) -> tuple[str, str]:
    tid = c.post("/api/tasks", json={"title": "Water the plants"}).json()["id"]
    comment = c.post(f"/api/tasks/{tid}/comments", json={"body": "done twice"}).json()
    c.patch(f"/api/tasks/{tid}", json={"priority": "high"})
    top = c.get(f"/api/tasks/{tid}").json()["activity"][0]
    assert top["field"] == "priority"
    return comment["author"], top["actor"]


def test_a_set_name_signs_the_comment_and_the_activity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, monkeypatch, your_name="Ada Example", team_people=["Someone Else"])
    with _client(tmp_path, monkeypatch) as c:
        assert _write_comment_and_activity(c) == ("Ada Example", "Ada Example")


def test_an_explicit_actor_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, monkeypatch, your_name="Ada Example", team_people=[])
    with _client(tmp_path, monkeypatch) as c:
        tid = c.post("/api/tasks", json={"title": "Water the plants"}).json()["id"]
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "x", "author": "cli"}).json()["author"] == "cli"
        hdr = {"X-Actor": "bot"}
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "y"}, headers=hdr).json()["author"] == "bot"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_unset_keeps_the_first_team_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blank: str | None) -> None:
    _config(tmp_path, monkeypatch, your_name=blank, team_people=["Sam Rivera", "Alex Chen"])
    with _client(tmp_path, monkeypatch) as c:
        assert _write_comment_and_activity(c) == ("Sam Rivera", "Sam Rivera")


def test_unset_without_a_team_is_me(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, monkeypatch, your_name=None, team_people=[])
    with _client(tmp_path, monkeypatch) as c:
        assert _write_comment_and_activity(c) == ("me", "me")


def test_the_cli_acts_under_the_set_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, monkeypatch, your_name="Ada Example", team_people=["Someone Else"])
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    backend = cli.pick_backend(argparse.Namespace(actor=None, local=True, server=None))
    assert backend.actor == "Ada Example"
    explicit = cli.pick_backend(argparse.Namespace(actor="bot", local=True, server=None))
    assert explicit.actor == "bot"


def _stored(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_settings_save_signs_the_next_comment_and_survives_a_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _config(tmp_path, monkeypatch, your_name=None, team_people=["Sam Rivera"])
    before = _stored(path)
    with _client(tmp_path, monkeypatch) as c:
        assert c.get("/api/status").json()["author"] == {"your_name": "", "author": "Sam Rivera"}
        saved = c.put("/api/your-name", json={"name": "  Ada   Example "})
        assert saved.status_code == 200
        assert saved.json() == {"your_name": "Ada Example", "author": "Ada Example"}
        assert c.get("/api/status").json()["author"] == saved.json()
        assert _write_comment_and_activity(c) == ("Ada Example", "Ada Example")
        assert _stored(path) == {**before, "your_name": "Ada Example"}
    assert cfgmod.load_config(path).your_name == "Ada Example"


def test_clearing_the_name_restores_the_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _config(tmp_path, monkeypatch, your_name="Ada Example", team_people=["Sam Rivera"])
    with _client(tmp_path, monkeypatch) as c:
        cleared = c.put("/api/your-name", json={"name": "   "})
        assert cleared.json() == {"your_name": "", "author": "Sam Rivera"}
        assert _write_comment_and_activity(c) == ("Sam Rivera", "Sam Rivera")
    assert _stored(path)["your_name"] == ""


def test_the_save_updates_the_mirror_author_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, monkeypatch, your_name=None, team_people=[])
    with _client(tmp_path, monkeypatch) as c:
        assert c.app.state.mirror.owner == "me"
        c.put("/api/your-name", json={"name": "Ada Example"})
        assert c.app.state.mirror.owner == "Ada Example"


@pytest.mark.parametrize("bad", ["x" * 81, "bell\x07", "nul\x00"])
def test_a_bad_name_is_refused_and_nothing_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    path = _config(tmp_path, monkeypatch, your_name="Ada Example", team_people=[])
    before = path.read_text(encoding="utf-8")
    with _client(tmp_path, monkeypatch) as c:
        r = c.put("/api/your-name", json={"name": bad})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"
        assert c.get("/api/status").json()["author"]["your_name"] == "Ada Example"
    assert path.read_text(encoding="utf-8") == before


def test_the_sample_config_is_never_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(cfgmod.CONFIG_SAMPLE_PATH))
    sample_before = cfgmod.CONFIG_SAMPLE_PATH.read_bytes()
    with _client(tmp_path, monkeypatch) as c:
        r = c.put("/api/your-name", json={"name": "Ada Example"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "config_readonly"
        assert c.get("/api/status").json()["author"]["your_name"] == ""
    assert cfgmod.CONFIG_SAMPLE_PATH.read_bytes() == sample_before


def test_a_non_loopback_client_without_a_token_cannot_set_the_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _config(tmp_path, monkeypatch, your_name=None, team_people=[])
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 1)) as c:
        assert c.put("/api/your-name", json={"name": "Mallory"}).status_code in (401, 403)
    assert "your_name" not in _stored(path) or _stored(path)["your_name"] == ""


def test_a_newline_in_the_name_collapses_to_a_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, monkeypatch, your_name=None, team_people=[])
    with _client(tmp_path, monkeypatch) as c:
        assert c.put("/api/your-name", json={"name": "Ada\nExample"}).json()["your_name"] == "Ada Example"
