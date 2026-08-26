"""Folder refs ↔ absolute paths (``src/placeholders.py``, Step 9) + the API's
``/api/resolve`` and the ``folder_resolved`` / ``folder_url`` fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.config import load_config
from src.placeholders import is_ref, normalize_path, opener_url, resolve, to_ref, web_url
from tests.conftest import write_test_config

PH = {"onedrive": "E:/onedrive", "user": "rober", "sharepoint:docs": "E:/onedrive/Tenant/docs - Documents"}
WR = {"onedrive": "https://cloud.example/od/", "sharepoint:docs": "https://tenant.example/sites/docs"}


def test_resolve_known_tokens() -> None:
    r = resolve("{onedrive}/house/kitchen", PH)
    assert r.resolved and r.path == "E:/onedrive/house/kitchen" and r.unresolved == []
    assert r.href == "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"
    assert resolve("{sharepoint:docs}/plans", PH).path == "E:/onedrive/Tenant/docs - Documents/plans"
    assert resolve("{user}/code/garden-bot", PH).path == "rober/code/garden-bot"


def test_resolve_unknown_token_is_flagged_not_guessed() -> None:
    r = resolve("{sharepoint:other}/x", PH)
    assert not r.resolved
    assert r.unresolved == ["sharepoint:other"]
    assert r.path == "{sharepoint:other}/x"       # left as-is, visibly


def test_resolve_plain_path_and_backslashes() -> None:
    r = resolve("E:\\onedrive\\house\\", PH)
    assert r.resolved and r.path == "E:/onedrive/house"
    assert resolve("", PH).path == "" and not resolve("", PH).resolved


def test_to_ref_longest_prefix_wins_and_segment_boundary() -> None:
    assert to_ref("E:/onedrive/house/kitchen", PH) == "{onedrive}/house/kitchen"
    assert to_ref("E:\\onedrive\\Tenant\\docs - Documents\\plans", PH) == "{sharepoint:docs}/plans"
    assert to_ref("e:/ONEDRIVE/house", PH) == "{onedrive}/house"          # case-insensitive
    assert to_ref("E:/onedrive2/house", PH) == "E:/onedrive2/house"       # not a segment match
    assert to_ref("E:/onedrive", PH) == "{onedrive}"                      # exact = the token alone
    assert to_ref("D:/elsewhere/x", PH) == "D:/elsewhere/x"               # no placeholder → path stays
    assert to_ref("{onedrive}\\already\\a\\ref", PH) == "{onedrive}/already/a/ref"
    assert to_ref("", PH) == ""


def test_normalize_and_is_ref_and_url() -> None:
    assert normalize_path("E:\\\\x\\\\y\\") == "E:/x/y"
    assert normalize_path("E:") == "E:/" and normalize_path("E:/") == "E:/"
    assert is_ref("{onedrive}/x") and not is_ref("E:/x")
    assert opener_url("{onedrive}/a b/c#d") == "taskos://open?ref=%7Bonedrive%7D%2Fa%20b%2Fc%23d"


def test_web_url_derives_the_cloud_twin() -> None:
    # trailing slash on the root is tolerated; segments are percent-encoded
    assert web_url("{onedrive}/house/kitchen", WR) == "https://cloud.example/od/house/kitchen"
    assert web_url("{onedrive}/a b/c#d", WR) == "https://cloud.example/od/a%20b/c%23d"
    assert web_url("{sharepoint:docs}/plans", WR) == "https://tenant.example/sites/docs/plans"
    assert web_url("{onedrive}", WR) == "https://cloud.example/od"  # the root itself
    assert web_url("{onedrive}\\back\\slashes", WR) == "https://cloud.example/od/back/slashes"


def test_web_url_never_guesses() -> None:
    assert web_url("{user}/code", WR) is None                  # token without a web root
    assert web_url("E:/onedrive/house", WR) is None            # absolute path, no leading token
    assert web_url("{onedrive}/x/{user}/y", WR) is None        # token left in the remainder
    assert web_url("", WR) is None
    assert web_url("{onedrive}/house", {}) is None
    assert web_url("{onedrive}/house", {"onedrive": "  "}) is None


def test_resolve_carries_web_url_only_when_roots_given() -> None:
    assert resolve("{onedrive}/house", PH).web_url is None
    r = resolve("{onedrive}/house", PH, WR)
    assert r.web_url == "https://cloud.example/od/house"
    assert r.as_dict()["web_url"] == "https://cloud.example/od/house"
    assert resolve("{user}/code", PH, WR).web_url is None


def test_config_flattens_nested_sharepoint_map(tmp_path: Path) -> None:
    cfg = write_test_config(tmp_path / "c.json")
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["placeholders"] = {"onedrive": "E:/od", "user": "me", "sharepoint": {"docs": "E:/od/T/docs", "hr": "E:/od/T/hr"}}
    raw["web_roots"] = {"onedrive": "https://c.example/od", "sharepoint": {"hr": "https://t.example/hr"}}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_config(cfg)
    ph = loaded.placeholders
    assert ph == {"onedrive": "E:/od", "user": "me", "sharepoint:docs": "E:/od/T/docs", "sharepoint:hr": "E:/od/T/hr"}
    assert resolve("{sharepoint:hr}/x", ph).path == "E:/od/T/hr/x"
    # web_roots flattens the same way, and a missing key is just the empty map
    assert loaded.web_roots == {"onedrive": "https://c.example/od", "sharepoint:hr": "https://t.example/hr"}
    assert web_url("{sharepoint:hr}/x", loaded.web_roots) == "https://t.example/hr/x"


# ------------------------------------------------------------------ API


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    cfg = write_test_config(
        tmp_path / "config.json",
        placeholders={"onedrive": "E:/onedrive", "user": "rober"},
        web_roots={"onedrive": "https://cloud.example/od"},
    )
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def test_api_resolve_ref_and_path(client: TestClient) -> None:
    r = client.post("/api/resolve", json={"ref": "{onedrive}/house"}).json()
    assert r == {"ref": "{onedrive}/house", "path": "E:/onedrive/house", "resolved": True, "unresolved": [],
                 "href": "taskos://open?ref=%7Bonedrive%7D%2Fhouse",
                 "web_url": "https://cloud.example/od/house"}
    # {user} has no web root → web_url is null, never a guess
    assert client.post("/api/resolve", json={"ref": "{user}/code"}).json()["web_url"] is None
    # an absolute path folds back onto the placeholder — the portable form the drawer stores
    r = client.post("/api/resolve", json={"ref": "E:\\onedrive\\house\\kitchen"}).json()
    assert r["ref"] == "{onedrive}/house/kitchen" and r["path"] == "E:/onedrive/house/kitchen"
    r = client.post("/api/resolve", json={"ref": "{sharepoint:nope}/x"}).json()
    assert r["resolved"] is False and r["unresolved"] == ["sharepoint:nope"]
    assert client.post("/api/resolve", json={}).status_code == 422
    assert client.post("/api/resolve", json={"ref": ""}).status_code == 422


def test_api_resolve_carries_the_ref_in_the_body_not_the_query(client: TestClient) -> None:
    """#66 — ``ref`` is on every tracking-parameter blocklist, so a URL-cleaning
    browser extension strips it and the request arrives with no query at all.
    The value must ride a body: the old ``GET ?ref=`` shape is gone, and a
    query-only call can never be mistaken for a successful resolve."""
    path = "E:\\onedrive\\house\\kitchen"
    assert client.get("/api/resolve", params={"ref": path}).status_code == 405
    # what the stripper actually delivers: the same call minus its query string
    assert client.post("/api/resolve", params={"ref": path}).status_code == 422
    assert client.post("/api/resolve", json={"ref": path}).json()["ref"] == "{onedrive}/house/kitchen"


def test_task_payloads_carry_folder_resolved_and_url(client: TestClient) -> None:
    t = client.post("/api/tasks", json={"title": "Kitchen", "folder_ref": "{onedrive}/house/kitchen"}).json()
    # no explicit link yet → the web_roots-derived cloud twin (#28)
    assert t["folder_resolved"] == "E:/onedrive/house/kitchen"
    assert t["folder_url"] == "https://cloud.example/od/house/kitchen"
    client.post(f"/api/tasks/{t['id']}/links", json={"url": "{onedrive}/house/kitchen", "kind": "folder"})
    client.post(f"/api/tasks/{t['id']}/links", json={"url": "https://example.com/sites/house/kitchen", "kind": "folder"})
    d = client.get(f"/api/tasks/{t['id']}").json()
    # an explicit links(kind=folder) web link always beats the derivation
    assert d["folder_url"] == "https://example.com/sites/house/kitchen"
    row = [x for x in client.get("/api/tasks").json()["items"] if x["id"] == t["id"]][0]
    assert row["folder_resolved"] == "E:/onedrive/house/kitchen" and row["folder_url"].startswith("https://example.com/")
    # unknown placeholder → unknown, never a half path — and no web root → no derived URL
    u = client.post("/api/tasks", json={"title": "Elsewhere", "folder_ref": "{sharepoint:x}/y"}).json()
    assert u["folder_resolved"] is None and u["folder_url"] is None
    n = client.post("/api/tasks", json={"title": "No folder"}).json()
    assert n["folder_resolved"] is None and n["folder_url"] is None


def test_status_carries_folders_opener_and_placeholders(client: TestClient) -> None:
    st = client.get("/api/status").json()
    assert st["folders"]["enabled"] is False and "not configured" in st["folders"]["reason"]
    assert st["opener"]["install"].startswith("$d=") and "<base-url>" in st["opener"]["install"]
    assert st["opener"]["uninstall"].startswith("Remove-Item")
    assert "# onedrive=E:\\onedrive" in st["opener"]["env_template"]
    assert st["placeholders"] == {"onedrive": "E:/onedrive", "user": "rober"}
    assert st["opener"]["installed_here"] in (True, False, None)
    # which registration shape is in use is its own state, never folded into
    # installed_here — the fallback hands the URL to a command interpreter
    assert st["opener"]["mode"] in ("launcher", "fallback", None)


def test_opener_handler_is_served_publicly(client: TestClient) -> None:
    from starlette.testclient import TestClient as TC

    from app.webapp.server import create_app

    body = client.get("/opener/opener.cmd")
    assert body.status_code == 200 and body.text.startswith("@echo off")
    # the launcher is what actually gets registered, so it has to be downloadable too
    launcher = client.get("/opener/opener.ps1")
    assert launcher.status_code == 200 and "param(" in launcher.text
    with TC(create_app(), client=("100.64.0.9", 1)) as remote:
        assert remote.get("/opener/opener.cmd").status_code == 200
        assert remote.get("/opener/opener.ps1").status_code == 200
        assert remote.get("/api/status").status_code == 401
