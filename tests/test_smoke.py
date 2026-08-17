"""Hermetic unit smoke: config, db lifecycle, the FastAPI app via TestClient.

Every test points ``TASKOS_DB_PATH`` at a temp file (autouse fixture) so no
run ever touches ``data/tasks.db``; the app module is imported after that
override so its ``get_db`` resolves the temp path per request.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.config import AppConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    return path


@pytest.fixture
def client() -> TestClient:
    from app.webapp.server import create_app

    with TestClient(create_app()) as c:
        yield c


# ------------------------------------------------------------------ config

def test_sample_config_parses_to_defaults_shape() -> None:
    cfg = load_config(REPO_ROOT / "config" / "config.sample.json")
    assert isinstance(cfg, AppConfig)
    assert cfg.port == 8448
    assert cfg.site == "home"
    assert cfg.issues.provider == "github"
    assert "onedrive" in cfg.placeholders
    assert cfg.team.enabled is False


def test_missing_config_falls_back_to_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.json")
    assert cfg.port == 8448
    assert cfg.site == "home"


def test_bad_port_falls_back(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"port": "not-a-number"}), encoding="utf-8")
    assert load_config(p).port == 8448


# ---------------------------------------------------------------------- db

def test_init_db_creates_settings_and_stamps_version(_temp_db: Path) -> None:
    assert dbmod.init_db() == dbmod.SCHEMA_VERSION
    conn = dbmod.connect()
    try:
        assert dbmod.schema_version(conn) == dbmod.SCHEMA_VERSION
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()
    # idempotent
    assert dbmod.init_db() == dbmod.SCHEMA_VERSION


def test_schema_version_is_none_without_table(_temp_db: Path) -> None:
    conn = sqlite3.connect(_temp_db)
    conn.row_factory = sqlite3.Row
    try:
        assert dbmod.schema_version(conn) is None
    finally:
        conn.close()


def test_get_db_yields_and_closes(_temp_db: Path) -> None:
    dbmod.init_db()
    gen = dbmod.get_db()
    conn = next(gen)
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(StopIteration):
        next(gen)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


# --------------------------------------------------------------------- app

def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_version_shape(client: TestClient) -> None:
    body = client.get("/api/version").json()
    assert set(body) >= {"git_sha", "built_at", "asset_hash", "schema_version"}
    assert body["git_sha"]
    assert body["schema_version"] == dbmod.SCHEMA_VERSION


def test_index_is_stamped_and_no_cache(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "no-cache" in r.headers["cache-control"]
    html = r.text
    assert "Add your first task" not in html  # rendered by JS, not baked in
    assert 'href="/static/styles.css?v=' in html
    assert 'src="/static/app.js?v=' in html


def test_static_js_is_import_stamped_and_immutable(client: TestClient) -> None:
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    assert "./_vendored/nav/nav-tabs.js?v=" in r.text


def test_static_icons_are_present_and_day_cached(client: TestClient) -> None:
    for name in ("favicon.ico", "icon-180.png", "icon-192.png", "icon-512.png", "icon-512-maskable.png"):
        r = client.get(f"/static/icons/{name}")
        assert r.status_code == 200, name
        assert "max-age=86400" in r.headers["cache-control"], name
    m = client.get("/static/manifest.webmanifest")
    assert m.status_code == 200
    assert "/static/icons/icon-512-maskable.png" in m.text
