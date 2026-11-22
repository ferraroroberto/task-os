"""The build readout's restart route is mounted behind the sign-in gate.

``src/self_restart.py`` is vendored verbatim and tested in project-scaffolding; this covers the
app-side wiring. No test posts a same-origin restart through the real app, because that would run
the real ``tray.bat --restart``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.webapp.routers._helpers import require_signed_in
from src import config as cfgmod
from src import db as dbmod
from src.self_restart import TRAY_RESTART, RestartTarget, restart_router
from tests.conftest import LOOPBACK, write_test_config

PHONE = ("100.101.102.103", 50000)  # a tailnet client
TOKEN = "t0ken-for-tests-only"
ORIGIN = {"Origin": "http://testserver"}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    path = write_test_config(tmp_path / "config.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["auth"] = {"token": TOKEN, "password_hash": ""}
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
    from app.webapp.server import create_app

    return create_app()


def test_the_app_declares_the_tray_recipe_as_its_only_target(app) -> None:
    with TestClient(app, client=LOOPBACK) as c:
        res = c.get("/api/restart")
    assert res.status_code == 200
    assert [t["id"] for t in res.json()["targets"]] == ["app"]


def test_another_device_needs_its_token_to_read_or_start_a_restart(app) -> None:
    with TestClient(app, client=PHONE) as c:
        assert c.get("/api/restart").status_code == 401
        assert c.post("/api/restart", json={"target": "app"}, headers=ORIGIN).status_code == 401
        signed_in = c.get("/api/restart", headers={"Authorization": f"Bearer {TOKEN}"})
    assert signed_in.status_code == 200


def test_a_cross_origin_post_is_refused_even_with_the_token(app) -> None:
    with TestClient(app, client=PHONE) as c:
        res = c.post(
            "/api/restart", json={"target": "app"},
            headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://elsewhere.example"},
        )
    assert res.status_code == 403


def test_the_route_refuses_when_the_middleware_is_missing(tmp_path: Path) -> None:
    bare = FastAPI()
    bare.include_router(restart_router(
        targets=[RestartTarget("app", "Restart app", TRAY_RESTART)],
        status_dir=tmp_path / "restart", guard=require_signed_in, root=tmp_path,
        spawn=lambda spec, root: pytest.fail("a restart started without auth"),
    ))
    res = TestClient(bare).post("/api/restart", json={"target": "app"}, headers=ORIGIN)
    assert res.status_code == 401


def test_the_recipe_runs_the_repos_own_tray_bat() -> None:
    assert TRAY_RESTART[-2:] == (".\\tray.bat", "--restart")
    assert (ROOT / "tray.bat").is_file()
