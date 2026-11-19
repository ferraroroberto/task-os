"""Available features: each coarse block can be switched off on one machine.

Off means the block's routes answer 409 ``feature_off``, its background work is
stopped and its status section reads off with the one reason; on again restores
all three with no restart, and the choice lives in the (gitignored) config file.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src.config import load_config, save_features
from src.features import (
    FEATURES,
    KEYS,
    OFF_REASON,
    features_block,
    off_keys,
    search_kind_off_reason,
)
from src.issues import FAKE_PATH_ENV, PROVIDER_ENV
from src.issues.fake import FakeProvider
from tests.conftest import LOOPBACK, write_test_config
from tests.fixtures.folder_explorer_fake import FakeFolderExplorer


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    """A booted app over a writable temp config; extra keyword args go to ``write_test_config``."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    clients: list[TestClient] = []

    def _make(*, features: dict | None = None, **cfg: object) -> TestClient:
        path = write_test_config(tmp_path / "config.json", **cfg)
        if features is not None:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["features"] = features
            path.write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
        from app.webapp.server import create_app

        client = TestClient(create_app(), client=LOOPBACK)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def _switch(client: TestClient, key: str, enabled: bool) -> dict:
    res = client.put(f"/api/features/{key}", json={"enabled": enabled})
    assert res.status_code == 200, res.text
    return res.json()


def _row(client: TestClient, key: str) -> dict:
    return next(f for f in client.get("/api/features").json()["features"] if f["key"] == key)


def _alive(thread_owner: object) -> bool:
    thread = getattr(thread_owner, "_thread", None)
    return thread is not None and thread.is_alive()


# ------------------------------------------------------------------ config


def test_every_default_on_block_is_on_by_default(make_client: Callable[..., TestClient]) -> None:
    client = make_client()
    rows = client.get("/api/features").json()["features"]
    assert [r["key"] for r in rows] == list(KEYS)
    # The one opt-in block (it writes outside this install) is the only row that starts off.
    assert [r["key"] for r in rows if not r["enabled"]] == ["publish_address"]
    assert all(r["enabled"] for r in rows if not r["opt_in"])
    assert all(r["summary"] for r in rows)
    assert client.app.state.config.features_off == frozenset()
    assert client.app.state.config.features_on == frozenset()


def test_only_an_explicit_false_switches_a_block_off() -> None:
    assert off_keys({"time": False, "email": True, "ai": "no", "nonsense": False}) == {"time"}
    assert off_keys(None) == frozenset()
    assert off_keys(["time"]) == frozenset()
    assert features_block({"time", "nonsense"}) == {"time": False}


def test_save_features_writes_only_the_off_blocks(tmp_path: Path) -> None:
    path = write_test_config(tmp_path / "config.json")
    site = json.loads(path.read_text(encoding="utf-8"))["site"]
    save_features(frozenset({"calendar", "time"}), path=path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["features"] == {"time": False, "calendar": False}
    assert load_config(path).features_off == {"time", "calendar"}
    save_features(frozenset(), path=path)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert "features" not in after
    assert after["site"] == site                      # nothing else is touched


def test_the_committed_sample_has_no_switch_and_is_never_written() -> None:
    sample = json.loads(cfgmod.CONFIG_SAMPLE_PATH.read_text(encoding="utf-8"))
    assert "features" not in sample
    with pytest.raises(ValueError, match="sample"):
        save_features(frozenset({"time"}), path=cfgmod.CONFIG_SAMPLE_PATH)


def test_a_switch_survives_a_restart(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    client = make_client()
    _switch(client, "calendar", False)
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["features"] == {"calendar": False}
    client.__exit__(None, None, None)
    from app.webapp.server import create_app

    with TestClient(create_app(), client=LOOPBACK) as again:
        assert _row(again, "calendar")["enabled"] is False
        assert _row(again, "time")["enabled"] is True
        _switch(again, "calendar", True)
    assert "features" not in json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))


def test_a_read_only_config_refuses_the_switch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(cfgmod.CONFIG_SAMPLE_PATH))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=LOOPBACK) as client:
        res = client.put("/api/features/time", json={"enabled": False})
    assert res.status_code == 409 and res.json()["error"]["code"] == "config_readonly"


def test_an_unknown_block_is_a_404(make_client: Callable[..., TestClient]) -> None:
    client = make_client()
    res = client.put("/api/features/nonsense", json={"enabled": False})
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"


# ----------------------------------------------------------- the page itself


def test_the_page_carries_the_off_blocks_from_first_paint(make_client: Callable[..., TestClient]) -> None:
    client = make_client(features={"time": False, "email": False})
    assert '<html lang="en" data-features-off="email time">' in client.get("/").text
    _switch(client, "email", True)
    _switch(client, "time", True)
    assert "data-features-off" not in client.get("/").text


def test_every_off_attribute_has_a_css_rule() -> None:
    css = (Path(__file__).resolve().parents[2] / "app/webapp/static/styles/base.css").read_text(encoding="utf-8")
    # The opt-in block owns no screen: it never rides the page's off list.
    for f in (f for f in FEATURES if f.default_on):
        assert f':root[data-features-off~="{f.key}"] [data-feature="{f.key}"]' in css


# -------------------------------------------------------------- per block


def test_time_off_hides_the_tracker_and_on_restores_it(make_client: Callable[..., TestClient]) -> None:
    client = make_client()
    assert client.get("/api/time/meta").status_code == 200
    _switch(client, "time", False)
    for res in (client.get("/api/time/meta"), client.get("/api/time/timers"), client.get("/api/time/summary")):
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "feature_off"
        assert OFF_REASON in res.json()["error"]["message"]
    assert client.get("/api/board").status_code == 200   # the rest of the app is untouched
    _switch(client, "time", True)
    assert client.get("/api/time/meta").status_code == 200


def test_calendar_off_draws_no_lane_and_never_fetches(make_client: Callable[..., TestClient]) -> None:
    client = make_client()
    fetched: list[str] = []
    client.app.state.calendar._fetcher = lambda url, timeout: fetched.append(url) or ""
    _switch(client, "calendar", False)
    lane = client.get("/api/today").json()["calendar"]
    assert lane["configured"] is False and lane["state"] == "off" and lane["reason"] == OFF_REASON
    assert client.post("/api/calendar/refresh").status_code == 409
    status = client.get("/api/status").json()["calendar"]
    assert status["feature_off"] is True and status["reason"] == OFF_REASON
    assert fetched == []
    _switch(client, "calendar", True)
    assert client.post("/api/calendar/refresh").status_code == 200
    assert "feature_off" not in client.get("/api/status").json()["calendar"]


def test_issues_off_stops_the_poller_and_on_restarts_it(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    forge = FakeProvider.from_issues(tmp_path / "forge.json", [])
    monkeypatch.setenv(PROVIDER_ENV, "fake")
    monkeypatch.setenv(FAKE_PATH_ENV, str(forge.path))
    client = make_client()
    issues = client.app.state.issues
    assert issues.enabled and _alive(issues)
    assert client.get("/api/issues/status").status_code == 200
    _switch(client, "issues", False)
    assert not _alive(issues)
    for res in (client.get("/api/issues/status"), client.post("/api/issues/sync"), client.get("/api/tasks/1/issue")):
        assert res.status_code == 409 and res.json()["error"]["code"] == "feature_off"
    groups = {g["kind"]: g for g in client.get("/api/search?q=x").json()["groups"]}
    assert groups["issues"]["configured"] is False and groups["issues"]["reason"] == OFF_REASON
    assert groups["tasks"]["configured"] is True    # the rest of search is untouched
    _switch(client, "issues", True)
    assert _alive(issues)
    assert client.get("/api/issues/status").status_code == 200


def test_email_off_covers_search_picker_capture_and_archiving(make_client: Callable[..., TestClient]) -> None:
    fake = FakeFolderExplorer(folders=["A/B"])
    try:
        client = make_client(folder_explorer_url=fake.url)
        capture = client.app.state.capture
        assert client.get("/api/folders/search", params={"q": "A"}).status_code == 200
        _switch(client, "email", False)
        assert not _alive(capture)
        before = len(fake.requests)
        for res in (
            client.get("/api/folders/search", params={"q": "A"}),
            client.post("/api/folders/explorer-window"),
            client.post("/api/capture/email/run"),
            client.get("/api/archive/runs"),
            client.post("/api/archive/run", json={}),
        ):
            assert res.status_code == 409 and res.json()["error"]["code"] == "feature_off"
        groups = {g["kind"]: g for g in client.get("/api/search?q=A").json()["groups"]}
        for kind in ("folders", "emails"):
            assert groups[kind]["configured"] is False and groups[kind]["reason"] == OFF_REASON
        status = client.get("/api/status").json()
        for section in ("folders", "capture", "archive"):
            assert status[section]["feature_off"] is True
        assert len(fake.requests) == before            # nothing reached folder-explorer
        _switch(client, "email", True)
        assert client.get("/api/folders/search", params={"q": "A"}).status_code == 200
    finally:
        fake.stop()


def test_ai_off_covers_voice_enrichment_and_triage(make_client: Callable[..., TestClient]) -> None:
    client = make_client()
    _switch(client, "ai", False)
    for res in (
        client.get("/api/ai/suggestions"),
        client.post("/api/ai/triage", json={}),
        client.post("/api/transcribe", content=b"x", headers={"content-type": "audio/wav"}),
        client.post("/api/enrich", json={"text": "hello"}),
    ):
        assert res.status_code == 409 and res.json()["error"]["code"] == "feature_off"
    status = client.get("/api/status").json()
    for section in ("voice", "enrich", "ai"):
        assert status[section]["feature_off"] is True and status[section]["enabled"] is False
    _switch(client, "ai", True)
    assert client.get("/api/ai/suggestions").status_code == 200


def test_mirror_off_stops_the_watcher_and_the_backup(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    client = make_client(dir=str(tmp_path / "mirror"), backup_dir=str(tmp_path / "backups"))
    mirror, backup = client.app.state.mirror, client.app.state.backup
    assert _alive(mirror) and _alive(backup)
    _switch(client, "mirror", False)
    assert not _alive(mirror) and not _alive(backup)
    for res in (client.post("/api/mirror/export"), client.post("/api/mirror/import"), client.post("/api/backup")):
        assert res.status_code == 409 and res.json()["error"]["code"] == "feature_off"
    status = client.get("/api/status").json()
    assert status["mirror"]["feature_off"] is True and status["backup"]["feature_off"] is True
    _switch(client, "mirror", True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not (_alive(mirror) and _alive(backup)):
        time.sleep(0.05)
    assert _alive(mirror) and _alive(backup)
    assert client.post("/api/mirror/export").status_code == 200


# ----------------------------------------------------------- availability


def test_a_block_whose_dependency_is_missing_is_unavailable_with_the_reason(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client()
    email = _row(client, "email")
    assert email["enabled"] is True and email["available"] is False
    assert "folder_explorer_url" in email["reason"]
    assert _row(client, "calendar")["available"] is False and "ics_url" in _row(client, "calendar")["reason"]
    assert _row(client, "time")["available"] is True and _row(client, "time")["reason"] is None
    _switch(client, "email", False)
    assert _row(client, "email")["available"] is True      # off is its own state, not an unavailable one


def test_search_kinds_belong_to_the_blocks_that_feed_them() -> None:
    assert search_kind_off_reason({"email"}, "folders") == OFF_REASON
    assert search_kind_off_reason({"email"}, "emails") == OFF_REASON
    assert search_kind_off_reason({"issues"}, "issues") == OFF_REASON
    assert search_kind_off_reason({"issues"}, "tasks") is None
    assert search_kind_off_reason(set(), "folders") is None
