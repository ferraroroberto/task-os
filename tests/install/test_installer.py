"""The install keeps every setting a PC has: configs are created only when missing, an existing one gains only
the keys that change nothing (after a backup), registrations that exist are kept, a second run is unchanged and
``-WhatIf`` writes nothing. Every test runs against a temp folder, never this checkout's config."""

from __future__ import annotations

import json
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.install import __main__ as cli
from src.install import checklist, machine, requirements
from src.install.config_merge import (
    config_same_behaviour,
    ensure_config,
    ensure_configs,
    missing_paths,
    plan_additions,
)
from src.install.machine import MachineStep
from src.install.requirements import RequirementsStep

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "config" / "config.sample.json"
NOW = datetime(2026, 11, 21, 9, 30, 0)

# A PC's own settings: every value differs from the sample's, and some sample keys are absent.
EXISTING = {
    "site": "office",
    "port": 9123,
    "your_name": "Alex",
    "issues": {"provider": "gitlab", "owner": "someone-else"},
    "mirror": {"dir": "{onedrive}/elsewhere/mirror", "backup_dir": ""},
    "time": {"compare_area": "work"},
    "auth": {"token": "kept-secret", "password_hash": ""},
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout-shaped temp folder holding the real committed samples."""
    (tmp_path / "config").mkdir()
    for sample in (REPO_ROOT / "config").glob("*.sample.json"):
        shutil.copy(sample, tmp_path / "config" / sample.name)
    return tmp_path


def _leaves(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    out: dict[tuple[str, ...], Any] = {}
    for key, value in data.items():
        if isinstance(value, dict) and value:
            out.update(_leaves(value, (*prefix, key)))
        else:
            out[(*prefix, key)] = value
    return out


def _write(path: Path, data: Any) -> bytes:
    raw = json.dumps(data, indent=4).encode("utf-8")
    path.write_bytes(raw)
    return raw


# ---------------------------------------------------------------- config files


def test_a_fresh_pc_gets_each_config_copied_from_its_sample(root: Path) -> None:
    steps = {s.path.name: s for s in ensure_configs(root / "config", whatif=False, now=NOW)}
    assert {n: s.status for n, s in steps.items()} == {"config.json": "created", "sharepoint-mapping.json": "created"}
    assert (root / "config" / "config.json").read_bytes() == SAMPLE.read_bytes()


def test_an_existing_config_keeps_every_value_gains_the_harmless_keys_and_is_backed_up(root: Path) -> None:
    target = root / "config" / "config.json"
    original = _write(target, EXISTING)

    step = ensure_config(SAMPLE, target, whatif=False, same=config_same_behaviour, now=NOW)

    merged = json.loads(target.read_text(encoding="utf-8"))
    assert step.status == "merged"
    for path, value in _leaves(EXISTING).items():  # no existing value changed
        node: Any = merged
        for key in path:
            node = node[key]
        assert node == value, path
    assert {"capture", "voice", "calendar", "alerts"} <= set(step.added)  # missing keys were added...
    assert all(k in merged for k in ("capture", "voice", "calendar", "alerts"))
    # ...but never one whose sample value would change what this PC runs
    assert {"placeholders.user", "time.people", "team.people", "placeholders.onedrive"} & set(step.added) == set()
    assert {"time.people", "team.people"} <= set(step.held_back)
    assert "people" not in merged["time"]
    assert step.backup == root / "config" / "backups" / "config.20261121-093000.json"
    assert step.backup.read_bytes() == original  # a backup was written, byte for byte
    assert config_same_behaviour(EXISTING, merged)


def test_a_second_run_reports_unchanged_and_writes_nothing(root: Path) -> None:
    ensure_configs(root / "config", whatif=False, now=NOW)
    target = root / "config" / "config.json"
    _write(target, EXISTING)
    ensure_configs(root / "config", whatif=False, now=NOW)
    after_first = target.read_bytes()
    backups = sorted((root / "config" / "backups").iterdir())

    again = ensure_configs(root / "config", whatif=False, now=datetime(2026, 11, 22))

    assert [s.status for s in again] == ["unchanged", "unchanged"]
    assert target.read_bytes() == after_first
    assert sorted((root / "config" / "backups").iterdir()) == backups


def test_whatif_lists_the_changes_and_makes_none(root: Path) -> None:
    target = root / "config" / "config.json"
    original = _write(target, EXISTING)

    steps = {s.path.name: s for s in ensure_configs(root / "config", whatif=True, now=NOW)}

    assert steps["config.json"].status == "would-merge" and "capture" in steps["config.json"].added
    assert steps["sharepoint-mapping.json"].status == "would-create"
    assert target.read_bytes() == original
    assert not (root / "config" / "sharepoint-mapping.json").exists()
    assert not (root / "config" / "backups").exists()


@pytest.mark.parametrize("content", ["{ not json", "[1, 2]"])
def test_a_config_that_does_not_parse_is_left_alone_and_reported(root: Path, content: str) -> None:
    target = root / "config" / "config.json"
    target.write_text(content, encoding="utf-8")
    step = ensure_config(SAMPLE, target, whatif=False, same=config_same_behaviour, now=NOW)
    assert step.status == "unparseable" and "left untouched" in step.detail
    assert target.read_text(encoding="utf-8") == content
    assert not (root / "config" / "backups").exists()


def test_a_file_with_no_reader_holds_every_missing_key_back(root: Path) -> None:
    target = root / "config" / "sharepoint-mapping.json"
    _write(target, {"title": "Name"})
    step = next(s for s in ensure_configs(root / "config", whatif=False, now=NOW) if s.path == target)
    assert step.status == "unchanged" and step.added == () and "due" in step.held_back
    assert json.loads(target.read_text(encoding="utf-8")) == {"title": "Name"}


def test_a_missing_block_that_changes_behaviour_is_tried_key_by_key() -> None:
    sample = {"a": 1, "block": {"safe": 1, "risky": 2}, "kept": {"x": 1}}
    current = {"kept": {}}

    def same(before: dict[str, Any], after: dict[str, Any]) -> bool:
        return after.get("block", {}).get("risky") is None and after.get("a") is None

    merged, added, held = plan_additions(current, sample, same)
    assert missing_paths(current, sample) == [("a",), ("block",), ("kept", "x")]
    assert added == ["block.safe", "kept.x"] and held == ["a", "block.risky"]
    assert merged == {"kept": {"x": 1}, "block": {"safe": 1}}


# ---------------------------------------------------------------- registrations


def test_the_sign_in_start_is_opt_in_and_never_doubled(tmp_path: Path) -> None:
    repo, folder = tmp_path / "repo", tmp_path / "Startup"
    repo.mkdir()
    assert machine.ensure_startup(repo, whatif=False, enable=False, folder=folder).status == "not-registered"
    assert machine.ensure_startup(repo, whatif=True, enable=True, folder=folder).status == "would-register"
    assert not folder.exists()

    made = machine.ensure_startup(repo, whatif=False, enable=True, folder=folder)
    entry = folder / machine.STARTUP_FILE_NAME
    assert made.status == "registered" and str(repo.resolve() / "tray.bat") in entry.read_text(encoding="utf-8")
    assert machine.ensure_startup(repo, whatif=False, enable=True, folder=folder).status == "kept"


def test_another_startup_entry_for_this_tray_is_kept(tmp_path: Path) -> None:
    repo, folder = tmp_path / "repo", tmp_path / "Startup"
    repo.mkdir()
    folder.mkdir()
    foreign = folder / "MyLauncher.cmd"
    foreign.write_text(f'call "{repo.resolve() / "tray.bat"}"\n', encoding="utf-8")
    step = machine.ensure_startup(repo, whatif=False, enable=True, folder=folder)
    assert step == MachineStep("start at sign-in", "kept", "already present: MyLauncher.cmd")
    assert sorted(p.name for p in folder.iterdir()) == ["MyLauncher.cmd"]


class _FakeInstaller:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str]] = []

    def default_dest(self) -> Path:
        return Path("handler-dir")

    def install(self, dest: Path, scheme: str) -> bool:
        self.calls.append((dest, scheme))
        return True


@pytest.mark.parametrize(("state", "whatif", "status", "installs"), [
    (True, False, "kept", 0),
    (False, True, "would-register", 0),
    (False, False, "registered", 1),
    (None, False, "skipped", 0),
])
def test_the_folder_opener_is_registered_only_where_none_exists(
    monkeypatch: pytest.MonkeyPatch, state: bool | None, whatif: bool, status: str, installs: int,
) -> None:
    fake = _FakeInstaller()
    monkeypatch.setattr(machine, "opener_state", lambda scheme: state)
    monkeypatch.setattr(machine, "_opener_installer", lambda: fake)
    assert machine.ensure_opener(whatif=whatif, scheme="taskos-test").status == status
    assert len(fake.calls) == installs


# ---------------------------------------------------------------- requirements


def _pip_answer(stdout: str, code: int = 0) -> Any:
    class Done:
        returncode, stderr = code, ""

    Done.stdout = stdout
    return lambda args, timeout: Done


@pytest.mark.parametrize(("report", "whatif", "status"), [
    ('{"install": []}', False, "unchanged"),
    ('{"install": [{"metadata": {"name": "fastapi", "version": "1.0"}}]}', True, "would-install"),
    ("not json", False, "failed"),
])
def test_requirements_trust_only_pips_own_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report: str, whatif: bool, status: str,
) -> None:
    monkeypatch.setattr(requirements, "running_in_venv", lambda repo: True)
    monkeypatch.setattr(requirements, "_pip", _pip_answer(report))
    assert requirements.ensure_requirements(tmp_path, whatif=whatif).status == status


# ---------------------------------------------------------------- the whole run + checklist


@pytest.fixture
def quiet_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run's PC-wide steps stubbed: the registry and pip stay out of a unit test."""
    monkeypatch.setattr(cli, "ensure_requirements", lambda repo, whatif: RequirementsStep("unchanged"))
    monkeypatch.setattr(cli, "ensure_opener", lambda whatif: MachineStep("folder opener", "kept"))
    monkeypatch.setattr(checklist, "opener_state", lambda scheme: True)


def _tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def test_install_whatif_then_install_then_reinstall(root: Path, quiet_machine: None,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    folder = root / "Startup"
    before = _tree(root)
    assert cli.run(root, whatif=True, startup=True, startup_folder=folder, probe=False) == 0
    assert _tree(root) == before
    assert "[would-create] config/config.json" in capsys.readouterr().out

    assert cli.run(root, whatif=False, startup=True, startup_folder=folder, probe=False) == 0
    assert "[created] config/config.json" in capsys.readouterr().out

    installed = _tree(root)
    assert cli.run(root, whatif=False, startup=True, startup_folder=folder, probe=False) == 0
    out = capsys.readouterr().out
    assert _tree(root) == installed
    assert "[unchanged] config/config.json" in out and "[kept] start at sign-in" in out
    assert "[ok] config/config.json" in out and "[missing] your name" in out
    # a config straight from the sample still names the author's account and folders: flagged, never ok
    assert "[unknown] config reviewed for this PC - still the sample's values" in out and "issues.owner" in out


def test_a_config_with_its_own_values_counts_as_reviewed(root: Path) -> None:
    data = {"issues": {"owner": "me"}, "placeholders": {"onedrive": "{x}", "user": "me"},
            "mirror": {"dir": "", "backup_dir": ""}, "team": {"people": []}, "time": {"people": []}}
    assert checklist.sample_values_kept(root, data).state == "ok"


def test_an_unparseable_config_fails_the_run_and_the_checklist_says_unknown(
    root: Path, quiet_machine: None, capsys: pytest.CaptureFixture[str],
) -> None:
    (root / "config" / "config.json").write_text("{", encoding="utf-8")
    assert cli.run(root, whatif=False, startup=False, startup_folder=root / "S", probe=False) == 1
    out = capsys.readouterr().out
    assert "[unparseable] config/config.json" in out and "[unknown] your name" in out


def test_the_app_probe_tells_not_running_from_answering() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert checklist.probe_app(port).state == "missing"
