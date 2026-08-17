"""Folder index over a temp tree (``src/folder_index.py``, Step 9) — service,
API and CLI. Never touches a real synced folder: the roots are built here."""

from __future__ import annotations

import io
import json
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.config import load_config
from src.folder_index import FolderIndexService
from tests.conftest import write_test_config


def _tree(root: Path) -> None:
    for rel in ("house/kitchen/plans", "house/garden", "admin/car", "code/garden-bot/src", "Tenant/docs - Documents/plans"):
        (root / rel).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    root = tmp_path / "onedrive"
    _tree(root)
    return write_test_config(
        tmp_path / "config.json",
        folder_roots=["{onedrive}/house", "{onedrive}/code", "{sharepoint:docs}"],
        placeholders={"onedrive": str(root).replace("\\", "/"), "user": "me",
                      "sharepoint:docs": str(root / "Tenant" / "docs - Documents").replace("\\", "/")},
    )


def test_service_reindex_search_and_status(cfg: Path, tmp_path: Path) -> None:
    svc = FolderIndexService(load_config(cfg), index_path=tmp_path / "idx.txt")
    assert svc.enabled and svc.status()["configured"]
    assert svc.status()["entries"] == 0 and svc.status()["last_indexed"] is None
    r = svc.reindex()
    assert r["entries"] == 9 and (tmp_path / "idx.txt").exists()
    st = svc.status()
    assert st["entries"] == 9 and st["last_indexed"] and st["indexing"] is False and st["stale"] is False
    assert all(x["exists"] for x in st["roots"])
    hits = svc.search("kitchen")
    assert [h["ref"] for h in hits] == ["{onedrive}/house/kitchen", "{onedrive}/house/kitchen/plans"]
    assert hits[0]["name"] == "kitchen" and hits[0]["depth"] == 1 and hits[1]["depth"] == 2
    assert hits[0]["path"].endswith("/onedrive/house/kitchen")
    # AND across terms, case-insensitive; the sharepoint root folds onto its own token
    assert [h["ref"] for h in svc.search("DOCS plans")] == ["{sharepoint:docs}/plans"]
    assert svc.search("nothing-here") == [] and svc.search("") == []
    assert len(svc.search("a", limit=2)) == 2


def test_service_load_from_file_without_scan(cfg: Path, tmp_path: Path) -> None:
    idx = tmp_path / "idx.txt"
    FolderIndexService(load_config(cfg), index_path=idx).reindex()
    fresh = FolderIndexService(load_config(cfg), index_path=idx)
    assert fresh.load() == 9 and fresh.status()["last_indexed"]
    assert fresh.search("garden-bot")[0]["ref"] == "{onedrive}/code/garden-bot"


def test_start_reindexes_when_missing_and_loads_when_fresh(cfg: Path, tmp_path: Path) -> None:
    idx = tmp_path / "idx.txt"
    svc = FolderIndexService(load_config(cfg), index_path=idx)
    svc.start()
    deadline = time.time() + 10
    while time.time() < deadline and svc.status()["entries"] == 0:
        time.sleep(0.05)
    svc.stop()
    assert svc.status()["entries"] == 9 and idx.exists()
    again = FolderIndexService(load_config(cfg), index_path=idx)
    again.start()
    deadline = time.time() + 10
    while time.time() < deadline and again.status()["entries"] == 0:
        time.sleep(0.05)
    again.stop()
    assert again.status()["entries"] == 9 and again.last_duration_s is None   # loaded, not rescanned


def test_not_configured_and_unresolved_roots_are_visible(tmp_path: Path) -> None:
    off = FolderIndexService(load_config(write_test_config(tmp_path / "c.json")), index_path=tmp_path / "i.txt")
    assert not off.enabled and "not configured" in off.reason and off.status()["configured"] is False
    with pytest.raises(RuntimeError):
        off.reindex()
    bad = FolderIndexService(
        load_config(write_test_config(tmp_path / "c2.json", folder_roots=["{nowhere}/x"], placeholders={})),
        index_path=tmp_path / "i2.txt",
    )
    assert not bad.enabled and "{nowhere}" in bad.reason
    assert bad.status()["roots"][0]["error"].startswith("unresolved placeholder")
    missing = FolderIndexService(
        load_config(write_test_config(tmp_path / "c3.json", folder_roots=[str(tmp_path / "gone")], placeholders={})),
        index_path=tmp_path / "i3.txt",
    )
    assert not missing.enabled and "not found" in missing.status()["roots"][0]["error"]


# ------------------------------------------------------------------ API


@pytest.fixture
def client(cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "data" / "tasks.db"))
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def test_api_reindex_search_status(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/api/folders/reindex").json()
    assert r["entries"] == 9 and r["index_file"].endswith("folder_index.txt")
    assert Path(r["index_file"]).parent == tmp_path / "data"     # next to the database
    s = client.get("/api/folders/search", params={"q": "kitchen"}).json()
    assert s["count"] == 2 and s["items"][0]["ref"] == "{onedrive}/house/kitchen" and s["indexing"] is False
    st = client.get("/api/status").json()["folders"]
    assert st["enabled"] and st["entries"] == 9 and st["last_indexed"]
    assert client.get("/api/folders/search").status_code == 422


def test_api_disabled_is_409_with_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(write_test_config(tmp_path / "c.json")))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        r = c.get("/api/folders/search", params={"q": "x"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "folders_disabled"
        assert c.post("/api/folders/reindex").status_code == 409


# ------------------------------------------------------------------ CLI


def test_cli_folders_local(cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.cli import main

    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "data" / "tasks.db"))
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(cfg))
    out = io.StringIO()
    with redirect_stdout(out):
        assert main(["--local", "folders", "reindex"]) == 0
    assert "9 folder(s) indexed" in out.getvalue()
    out = io.StringIO()
    with redirect_stdout(out):
        assert main(["--local", "--json", "folders", "search", "garden"]) == 0
    hits = json.loads(out.getvalue())
    assert {h["ref"] for h in hits["items"]} == {"{onedrive}/house/garden", "{onedrive}/code/garden-bot", "{onedrive}/code/garden-bot/src"}
    out = io.StringIO()
    with redirect_stdout(out):
        assert main(["--local", "folders"]) == 0
    assert out.getvalue().startswith("folders  9 folder(s)")
