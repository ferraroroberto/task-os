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


# ------------------------------------------------ entry document revalidation (#280)

def test_index_carries_a_validator_and_keeps_revalidating(client: TestClient) -> None:
    r = _get(client, "/")
    assert r.headers["etag"].startswith('W/"') and r.headers["etag"].endswith('"')
    assert r.headers["cache-control"] == "no-cache, must-revalidate"


def test_a_repeat_with_the_validator_is_a_bodyless_304(client: TestClient) -> None:
    etag = _get(client, "/").headers["etag"]
    r = client.get("/", headers={"If-None-Match": etag, "Accept-Encoding": "gzip"})
    assert r.status_code == 304
    assert r.content == b""
    assert "content-encoding" not in r.headers
    assert r.headers["etag"] == etag
    assert r.headers["cache-control"] == "no-cache, must-revalidate"


def test_validator_matching_is_tolerant_but_not_loose(client: TestClient) -> None:
    etag = _get(client, "/").headers["etag"]
    bare = etag[2:]
    assert client.get("/", headers={"If-None-Match": bare}).status_code == 304
    assert client.get("/", headers={"If-None-Match": f'"nope", {etag}'}).status_code == 304
    assert client.get("/", headers={"If-None-Match": "*"}).status_code == 304
    assert client.get("/", headers={"If-None-Match": 'W/"stale"'}).status_code == 200


def test_the_validator_moves_when_the_served_page_does(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 304 must never outlive a build: the stamped page names the fleet hash
    of every asset, so a new hash is a new page and a new validator."""
    from app.webapp.routers import misc

    before = _get(client, "/").headers["etag"]
    monkeypatch.setattr(misc.BUILD_INFO, "stamp_html", lambda html: html + "<!-- new build -->")
    after = _get(client, "/")
    assert after.headers["etag"] != before
    stale = client.get("/", headers={"If-None-Match": before})
    assert stale.status_code == 200 and "new build" in stale.text
