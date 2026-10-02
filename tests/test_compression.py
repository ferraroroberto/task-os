"""Response compression (#280): the app gzips what it serves.

The boot fetches the full task forest on every launch; uncompressed it is
megabytes over a phone link. ``GZipMiddleware`` sits *inside*
``AuthMiddleware`` (added first), so a 401 from the gate is never recompressed
and a bodyless response stays bodyless.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    return path


@pytest.fixture
def client() -> TestClient:
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def _get(client: TestClient, url: str, encoding: str | None = "gzip"):
    headers = {"Accept-Encoding": encoding} if encoding else {"Accept-Encoding": "identity"}
    return client.get(url, headers=headers)


def test_index_is_gzipped_and_still_revalidates(client: TestClient) -> None:
    r = _get(client, "/")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"] == "no-cache, must-revalidate"
    assert "Accept-Encoding" in r.headers["vary"]
    assert "<html" in r.text.lower()


def test_static_js_is_gzipped_and_keeps_its_cache_policy(client: TestClient) -> None:
    r = _get(client, "/static/app.js")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_big_json_body_is_gzipped_and_round_trips(client: TestClient) -> None:
    for i in range(40):
        client.post("/api/tasks", json={"title": f"compression probe task number {i}"})
    plain = _get(client, "/api/tasks/tree?include_closed=true", encoding=None)
    packed = _get(client, "/api/tasks/tree?include_closed=true")
    assert "content-encoding" not in plain.headers
    assert packed.headers["content-encoding"] == "gzip"
    # httpx already decoded the body: the payload is identical either way.
    assert packed.json() == plain.json()
    assert len(packed.content) == len(plain.content)
    assert len(json.dumps(packed.json())) > 1000


def test_identity_clients_get_the_body_untouched(client: TestClient) -> None:
    r = _get(client, "/", encoding=None)
    assert "content-encoding" not in r.headers


def test_small_responses_are_left_alone(client: TestClient) -> None:
    r = _get(client, "/healthz")
    assert r.json() == {"ok": True}
    assert "content-encoding" not in r.headers


def test_the_gate_still_denies_before_anything_is_compressed() -> None:
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 1)) as c:
        r = c.get("/api/tasks/tree", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_the_wire_bytes_really_are_smaller(client: TestClient) -> None:
    for i in range(40):
        client.post("/api/tasks", json={"title": f"compression probe task number {i}"})
    with client.stream(
        "GET", "/api/tasks/tree?include_closed=true", headers={"Accept-Encoding": "gzip"}
    ) as r:
        wire = b"".join(r.iter_raw())
    assert r.headers["content-encoding"] == "gzip"
    assert len(gzip.decompress(wire)) > 3 * len(wire)
