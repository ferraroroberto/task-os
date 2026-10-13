"""The usage log's mount (#412): the vendored ``src/usage_log.py`` router lands
events in a SQLite file beside the task database (so a ``TASKOS_DB_PATH``
instance never writes the real runtime-data folder), behind the one access gate
every ``/api/`` route sits behind. The router's own contract (validation,
retention, summary) is the scaffold's to test; this pins task-os's wiring.
Hermetic — a temp DB and config per test."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from tests.conftest import write_test_config

LOOPBACK = ("127.0.0.1", 50000)
PHONE = ("100.101.102.103", 50000)  # a tailnet client
TOKEN = "t0ken-for-tests-only"
BATCH = {
    "session_id": "0f6c2a8e-4c1b-4d7e-9a35-2b9d1e7c5a10",
    "device_class": "phone",
    "os_class": "android",
    "events": [
        {"kind": "session_start"},
        {"kind": "view", "id": "today"},
        {"kind": "tap", "id": "quick-add", "view": "today"},
        # a URL is never an id: the privacy contract drops it server-side
        {"kind": "tap", "id": "https://example.com/?q=secret", "view": "today"},
    ],
}


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    cfg = write_test_config(tmp_path / "config.json")
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["auth"] = {"token": TOKEN, "password_hash": ""}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(cfg))
    from app.webapp.server import create_app

    return create_app()


def test_owner_events_land_beside_the_task_db(app, tmp_path: Path) -> None:
    usage_db = tmp_path / dbmod.USAGE_DB_NAME
    assert dbmod.usage_db_path() == usage_db
    with TestClient(app, client=LOOPBACK) as c:
        r = c.post("/api/usage/events", json=BATCH)
        assert r.status_code == 200, r.text
        assert r.json() == {"accepted": 3, "rejected": 1}
        summary = c.get("/api/usage/summary").json()
    assert summary  # the read side answers over the same file
    conn = sqlite3.connect(usage_db)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
        rows = conn.execute("SELECT kind, view_id, control_id, device_class, os_class FROM events ORDER BY id").fetchall()
    finally:
        conn.close()
    assert cols == ["id", "ts", "session_id", "kind", "view_id", "control_id", "device_class", "os_class"]
    assert rows == [
        ("session_start", None, None, "phone", "android"),
        ("view", "today", None, "phone", "android"),
        ("tap", "today", "quick-add", "phone", "android"),
    ]


def test_usage_routes_sit_behind_the_gate(app, tmp_path: Path) -> None:
    with TestClient(app, client=PHONE) as c:
        assert c.post("/api/usage/events", json=BATCH).status_code == 401
        assert c.get("/api/usage/summary").status_code == 401
        assert not (tmp_path / dbmod.USAGE_DB_NAME).exists()
        r = c.post("/api/usage/events", json=BATCH, headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200, r.text
