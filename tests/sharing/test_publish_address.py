"""Publishing the host address to a shared-folder file.

Every address here is a documentation-range placeholder from a mocked discovery,
and every file is a temp file: no test reads a live address or touches a share.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src.config import AppConfig, NetworkSharingConfig, load_config
from src.features import PUBLISH_ADDRESS, features_block, off_keys, on_keys
from src.runtime.files import REPO_ROOT
from src.sharing import publisher as pub
from src.sharing.address import Discovery, discover, share_server
from tests.conftest import LOOPBACK, write_test_config

ADDRESS = "192.0.2.10"
OTHER = "192.0.2.77"


def _found(address: str | None = ADDRESS, reason: str = "") -> Callable[[str], Discovery]:
    return lambda _path: Discovery(address, reason)


# ------------------------------------------------------------------ config


def test_publishing_is_off_in_the_sample_and_for_a_config_without_the_key() -> None:
    sample = json.loads(cfgmod.CONFIG_SAMPLE_PATH.read_text(encoding="utf-8"))
    assert sample["network_sharing"] == {"host_ip_file": ""}
    assert "features" not in sample
    config = load_config(cfgmod.CONFIG_SAMPLE_PATH)
    assert config.features_on == frozenset()
    assert config.network_sharing.host_ip_file == ""
    assert PUBLISH_ADDRESS not in config.features_off     # the off set is the default-on blocks'


def test_only_an_explicit_true_switches_publishing_on() -> None:
    assert on_keys({PUBLISH_ADDRESS: True}) == {PUBLISH_ADDRESS}
    for stray in (False, "yes", 1, None):
        assert on_keys({PUBLISH_ADDRESS: stray}) == frozenset()
    assert on_keys(None) == on_keys(["publish_address"]) == frozenset()
    # An explicit false is not a "switched off" default-on block, and the others keep their default.
    assert off_keys({PUBLISH_ADDRESS: False, "time": False}) == {"time"}
    assert features_block({"time"}, {PUBLISH_ADDRESS}) == {"time": False, PUBLISH_ADDRESS: True}
    assert features_block(set(), set()) == {}


def test_a_secret_path_stays_out_of_the_config_repr() -> None:
    assert "host" not in repr(NetworkSharingConfig(host_ip_file="host-secret.txt"))


# ------------------------------------------------------------------ publish()


def test_first_write_is_one_address_and_a_newline(tmp_path: Path) -> None:
    target = tmp_path / "host.txt"
    out = pub.publish(str(target), discover_address=_found())
    assert (out.state, out.address) == (pub.PUBLISHED, ADDRESS)
    assert target.read_bytes() == ADDRESS.encode() + b"\n"


def test_a_changed_address_is_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "host.txt"
    target.write_text(OTHER + "\n", encoding="utf-8")
    out = pub.publish(str(target), discover_address=_found())
    assert out.state == pub.PUBLISHED
    assert target.read_text(encoding="utf-8") == ADDRESS + "\n"


def test_an_unchanged_address_does_not_touch_the_file(tmp_path: Path) -> None:
    target = tmp_path / "host.txt"
    target.write_bytes(ADDRESS.encode() + b"\r\n")           # a hand-edited line ending is still the same address
    os.utime(target, ns=(10**18, 10**18))
    before = target.stat().st_mtime_ns
    out = pub.publish(str(target), discover_address=_found())
    assert out.state == pub.UNCHANGED and out.address == ADDRESS
    assert target.stat().st_mtime_ns == before
    assert target.read_bytes() == ADDRESS.encode() + b"\r\n"


@pytest.mark.parametrize("reason", ["ambiguous: 2 local addresses reach the share's server", "no route"])
def test_an_unavailable_address_leaves_the_old_file(tmp_path: Path, reason: str) -> None:
    target = tmp_path / "host.txt"
    target.write_text(OTHER + "\n", encoding="utf-8")
    out = pub.publish(str(target), discover_address=_found(None, reason))
    assert (out.state, out.reason) == (pub.UNAVAILABLE, reason)
    assert target.read_text(encoding="utf-8") == OTHER + "\n"


def test_a_discovery_that_raises_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    def boom(_path: str) -> Discovery:
        raise RuntimeError("secret detail")

    out = pub.publish(str(tmp_path / "host.txt"), discover_address=boom)
    assert out.state == pub.UNAVAILABLE and "secret detail" not in out.reason


def test_a_write_failure_is_reported_without_the_path(tmp_path: Path) -> None:
    missing_folder = tmp_path / "no-such-folder-xyz" / "host.txt"
    out = pub.publish(str(missing_folder), discover_address=_found())
    assert out.state == pub.FAILED and out.address == ADDRESS
    assert "no-such-folder-xyz" not in out.reason and str(tmp_path) not in out.reason
    assert not missing_folder.parent.exists()               # no folder is made on a share


def test_a_blank_or_relative_path_never_writes_in_the_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for text in ("", "   ", "host.txt", os.path.join("sub", "host.txt")):
        out = pub.publish(text, discover_address=_found())
        assert out.state == pub.UNAVAILABLE, text
        assert pub.path_problem(text)
    assert list(tmp_path.iterdir()) == []


def test_a_path_inside_a_code_folder_is_refused(tmp_path: Path) -> None:
    target = REPO_ROOT / "src" / "sharing" / "host-address-test.txt"
    out = pub.publish(str(target), discover_address=_found())
    assert out.state == pub.FAILED
    assert not target.exists()


# ------------------------------------------------------------------ discover()


def _discover(path: str, *, remotes: list[str] | None = None, sources: dict[str, str] | None = None,
              mapped: str | None = None) -> Discovery:
    def resolve(_server: str) -> list[str]:
        return remotes if remotes is not None else ["198.51.100.1"]

    def source_for(remote: str) -> str:
        return (sources or {}).get(remote, ADDRESS)

    return discover(path, mapped=lambda _p: mapped, resolve=resolve, source_for=source_for)


def test_the_address_is_the_source_of_the_route_to_the_shares_server() -> None:
    found = _discover("\\\\fileserver\\team\\host.txt")
    assert found == Discovery(ADDRESS)


def test_a_mapped_drive_is_followed_to_its_server() -> None:
    assert share_server("Z:\\host.txt", lambda _p: "\\\\fileserver\\team") == "fileserver"
    assert _discover("Z:\\host.txt", mapped="\\\\fileserver\\team").address == ADDRESS


def test_a_local_path_has_no_server_to_route_to() -> None:
    found = _discover("C:\\local\\host.txt")
    assert found.address is None and "network share" in found.reason


def test_two_routes_with_different_sources_are_ambiguous() -> None:
    found = _discover("\\\\fileserver\\team\\host.txt", remotes=["198.51.100.1", "203.0.113.1"],
                      sources={"198.51.100.1": ADDRESS, "203.0.113.1": OTHER})
    assert found.address is None and "ambiguous" in found.reason


def test_two_routes_with_the_same_source_are_not() -> None:
    found = _discover("\\\\fileserver\\team\\host.txt", remotes=["198.51.100.1", "198.51.100.2"])
    assert found.address == ADDRESS


@pytest.mark.parametrize("source", ["127.0.0.1", "169.254.3.4", "0.0.0.0"])
def test_a_loopback_or_link_local_source_is_not_an_address_to_publish(source: str) -> None:
    found = _discover("\\\\fileserver\\team\\host.txt", sources={"198.51.100.1": source})
    assert found.address is None and "this computer" in found.reason


def test_an_unresolvable_server_or_no_route_says_which() -> None:
    def no_dns(_s: str) -> list[str]:
        raise OSError("lookup failed for fileserver")

    def no_route(_r: str) -> str:
        raise OSError("unreachable")

    dns = discover("\\\\fileserver\\team\\h.txt", mapped=lambda _p: None, resolve=no_dns)
    assert dns.address is None and "resolved" in dns.reason and "fileserver" not in dns.reason
    route = discover("\\\\fileserver\\team\\h.txt", mapped=lambda _p: None, resolve=lambda _s: ["198.51.100.1"],
                     source_for=no_route)
    assert route.address is None and "no route" in route.reason


# ------------------------------------------------------------------ AddressPublisher


def _config(path: str, *, on: bool = True) -> AppConfig:
    return replace(AppConfig(), features_on=frozenset({PUBLISH_ADDRESS}) if on else frozenset(),
                   network_sharing=NetworkSharingConfig(host_ip_file=path))


def test_the_publisher_does_nothing_while_the_switch_is_off(tmp_path: Path) -> None:
    target = tmp_path / "host.txt"
    publisher = pub.AddressPublisher(lambda: _config(str(target), on=False), discover_address=_found())
    assert publisher.run(wait=5).state == pub.OFF
    assert not target.exists()


def test_an_enabled_switch_reads_not_run_until_it_has_an_outcome(tmp_path: Path) -> None:
    publisher = pub.AddressPublisher(lambda: _config(str(tmp_path / "host.txt")), discover_address=_found())
    assert publisher.row_fields()["detail"] == "Not run yet"
    publisher.run(wait=5)
    fields = publisher.row_fields()
    assert fields["detail"] == f"Published: {ADDRESS}" and fields["attention"] is False


def test_a_slow_share_never_holds_the_caller(tmp_path: Path) -> None:
    release = threading.Event()

    def slow(_path: str) -> Discovery:
        release.wait(10)
        return Discovery(ADDRESS)

    target = tmp_path / "host.txt"
    publisher = pub.AddressPublisher(lambda: _config(str(target)), discover_address=slow)
    start = time.monotonic()
    out = publisher.run(wait=0.05)
    assert out.state == pub.PENDING and time.monotonic() - start < 2
    assert publisher.row_fields()["pending"] is True
    assert publisher.run().state == pub.PENDING              # a run in flight is not doubled
    release.set()
    publisher._thread.join(5)  # type: ignore[union-attr]
    assert publisher.outcome is not None and publisher.outcome.state == pub.PUBLISHED


def test_a_failed_publish_is_logged_without_the_path(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    gone = tmp_path / "gone-folder-xyz" / "host.txt"
    publisher = pub.AddressPublisher(lambda: _config(str(gone)), discover_address=_found())
    with caplog.at_level("INFO"):
        publisher.run(wait=5)
    assert publisher.outcome is not None and publisher.outcome.state == pub.FAILED
    assert "address publish" in caplog.text
    assert "gone-folder-xyz" not in caplog.text and str(tmp_path) not in caplog.text


# ------------------------------------------------------------------ the app


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    """A booted app over a writable temp config whose address discovery is mocked."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    clients: list[TestClient] = []

    def _make(*, features: dict | None = None, host_ip_file: str = "", address: str | None = ADDRESS) -> TestClient:
        path = write_test_config(tmp_path / "config.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["network_sharing"] = {"host_ip_file": host_ip_file}
        if features is not None:
            raw["features"] = features
        path.write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
        monkeypatch.setattr(
            "app.webapp.server.AddressPublisher",
            lambda get_config: pub.AddressPublisher(get_config, discover_address=_found(address, "no route")),
        )
        from app.webapp.server import create_app

        client = TestClient(create_app(), client=LOOPBACK)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def _row(client: TestClient) -> dict:
    return next(f for f in client.get("/api/features").json()["features"] if f["key"] == PUBLISH_ADDRESS)


def _wait_for(target: Path, text: str, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return
        time.sleep(0.02)
    raise AssertionError(f"{target.name} never held {text!r}")


def test_a_fresh_config_boots_with_publishing_off_and_writes_nothing(
    make_client: Callable[..., TestClient], tmp_path: Path,
) -> None:
    target = tmp_path / "host.txt"
    client = make_client(host_ip_file=str(target))           # a path, but the switch is not on
    row = _row(client)
    assert row["enabled"] is False and row["opt_in"] is True and "detail" not in row
    assert client.app.state.publisher.outcome.state == pub.OFF
    assert not target.exists()


def test_startup_publishes_when_the_switch_and_the_path_are_set(
    make_client: Callable[..., TestClient], tmp_path: Path,
) -> None:
    target = tmp_path / "host.txt"
    client = make_client(features={PUBLISH_ADDRESS: True}, host_ip_file=str(target))
    _wait_for(target, ADDRESS + "\n")
    assert _row(client)["enabled"] is True


def test_both_launch_paths_boot_the_one_lifespan() -> None:
    import inspect

    from app.webapp import manager, serve
    from app.webapp.server import create_app

    # `tray.bat` (manager.py) spawns `python -m app.webapp.serve` and `scripts/launcher.py webapp`
    # calls serve.run: one default app, built by create_app() around the one lifespan
    # that starts the publish (the booted-app tests above prove that lifespan runs it).
    assert serve.DEFAULT_APP == "app.webapp.server:app"
    assert '"app.webapp.serve"' in inspect.getsource(manager)
    assert "lifespan=_lifespan" in inspect.getsource(create_app)


def test_enabling_publishes_once_at_once_and_it_persists(
    make_client: Callable[..., TestClient], tmp_path: Path,
) -> None:
    target = tmp_path / "host.txt"
    client = make_client(host_ip_file=str(target))
    res = client.put(f"/api/features/{PUBLISH_ADDRESS}", json={"enabled": True})
    assert res.status_code == 200, res.text
    row = next(f for f in res.json()["features"] if f["key"] == PUBLISH_ADDRESS)
    assert row["enabled"] is True and row["available"] is True
    assert row["detail"] == f"Published: {ADDRESS}" and row["attention"] is False
    assert target.read_text(encoding="utf-8") == ADDRESS + "\n"
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["features"] == {PUBLISH_ADDRESS: True}
    assert load_config(tmp_path / "config.json").features_on == {PUBLISH_ADDRESS}
    # The other blocks are untouched, and the page's off list is the default-on blocks' alone.
    assert "data-features-off" not in client.get("/").text


def test_disabling_stops_writes_and_leaves_the_file(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    target = tmp_path / "host.txt"
    client = make_client(features={PUBLISH_ADDRESS: True}, host_ip_file=str(target))
    _wait_for(target, ADDRESS + "\n")
    assert client.put(f"/api/features/{PUBLISH_ADDRESS}", json={"enabled": False}).status_code == 200
    assert _row(client)["enabled"] is False
    assert target.read_text(encoding="utf-8") == ADDRESS + "\n"
    assert "features" not in json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    client.app.state.publisher.run(wait=5)
    assert client.app.state.publisher.outcome.state == pub.OFF


def test_a_blank_path_is_reported_and_nothing_is_written(
    make_client: Callable[..., TestClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    client = make_client(features={PUBLISH_ADDRESS: True}, host_ip_file="")
    row = _row(client)
    assert row["enabled"] is True and row["available"] is False and "blank" in row["reason"]
    assert "detail" not in row                               # an enabled switch is not shown as success
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".txt")] == []


def test_an_unavailable_address_shows_its_reason_on_the_row(
    make_client: Callable[..., TestClient], tmp_path: Path,
) -> None:
    client = make_client(features={PUBLISH_ADDRESS: True}, host_ip_file=str(tmp_path / "host.txt"), address=None)
    client.app.state.publisher._thread.join(5)
    row = _row(client)
    assert row["detail"] == "Unavailable: no route" and row["attention"] is True
