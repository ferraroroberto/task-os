"""The Folder field's pick from the front File Explorer window: ``POST /api/folders/explorer-window``.

folder-explorer is faked (``tests/fixtures/folder_explorer_fake``) — no test ever
reads a real File Explorer window. Each way the read can fail has its own code
and a message that says which, and none of them ever answers an empty path.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src.this_pc import is_this_pc
from tests.conftest import LOOPBACK, write_test_config
from tests.fixtures.folder_explorer_fake import FakeFolderExplorer

PATH = "/api/folders/explorer-window"
TOKEN = "t" * 32


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    clients: list[TestClient] = []

    def _make(*, host: tuple[str, int] = LOOPBACK, token: str = "", **cfg: object) -> TestClient:
        path = write_test_config(tmp_path / "config.json", **cfg)
        if token:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["auth"] = {**raw.get("auth", {}), "token": token}
            path.write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
        from app.webapp.server import create_app

        client = TestClient(create_app(), client=host)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def fake() -> Iterator[FakeFolderExplorer]:
    f = FakeFolderExplorer()
    yield f
    f.stop()


def test_a_front_window_gives_its_folder(make_client: Callable[..., TestClient], fake: FakeFolderExplorer) -> None:
    fake.explorer = ("ok", "D:\\Work\\Plans")
    r = make_client(folder_explorer_url=fake.url).post(PATH)
    assert r.status_code == 200 and r.json() == {"path": "D:\\Work\\Plans"}
    assert "/api/v1/explorer/folder" in fake.requests


@pytest.mark.parametrize(("kind", "status", "code", "words"), [
    ("none", 404, "no_explorer_window", "No Explorer folder"),
    ("unavailable", 502, "explorer_unavailable", "Windows did not say"),
    ("absent", 502, "folder_explorer_outdated", "update it"),
])
def test_each_failure_says_which_and_gives_no_path(
    make_client: Callable[..., TestClient], fake: FakeFolderExplorer, kind: str, status: int, code: str, words: str,
) -> None:
    fake.explorer = (kind, None)
    r = make_client(folder_explorer_url=fake.url).post(PATH)
    err = r.json()["error"]
    assert r.status_code == status and err["code"] == code and words in err["message"]
    assert "path" not in r.json()


def test_folder_explorer_down_is_not_no_window(make_client: Callable[..., TestClient], fake: FakeFolderExplorer) -> None:
    client = make_client(folder_explorer_url=fake.url)
    fake.stop()
    r = client.post(PATH)
    assert r.status_code == 502 and r.json()["error"]["code"] == "folder_explorer_unreachable"


def test_no_folder_explorer_configured(make_client: Callable[..., TestClient]) -> None:
    r = make_client().post(PATH)
    assert r.status_code == 503 and r.json()["error"]["code"] == "folders_unavailable"


def test_a_machine_that_is_not_the_pc_never_reaches_the_window(
    make_client: Callable[..., TestClient], fake: FakeFolderExplorer,
) -> None:
    fake.explorer = ("ok", "D:\\Work\\Plans")
    client = make_client(folder_explorer_url=fake.url, host=("203.0.113.9", 50000), token=TOKEN)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    r = client.post(PATH, headers=auth)
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_this_pc"
    assert fake.requests == []
    assert client.get("/api/me", headers=auth).json()["pc"] is False


def test_me_says_the_pc_itself_is_the_pc(make_client: Callable[..., TestClient]) -> None:
    assert make_client().get("/api/me").json()["pc"] is True


def test_this_pc_is_loopback_or_an_own_address() -> None:
    assert is_this_pc("127.0.0.1") and is_this_pc("::1") and is_this_pc("::ffff:127.0.0.1")
    assert not is_this_pc("203.0.113.9") and not is_this_pc("0.0.0.0") and not is_this_pc("") and not is_this_pc(None)
    assert not is_this_pc("not-an-address") and not is_this_pc("224.0.0.1")
