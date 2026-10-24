"""Checks shared by the per-ratchet gate-wrapper tests (`test_*_ratchet_gate.py`).

Each ratchet script exits 3 when it could not read the tracked tree (git unusable, a file
that cannot be read or does not parse): nothing was checked. These checks pin that 3 fails
as NOT CONFIRMED -- never a pass, never a skip -- and that the pre-ship gate, `.fleet.toml`
and the e2e routing carry the stage. They run fake scripts in a temp directory and never
touch the real `tasks.db` or `config/config.json`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from scripts import classify_e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))


def check_only_exit_zero_passes(gate: ModuleType, code: int, passes: bool) -> None:
    ok, label = gate.classify_exit(code)
    assert ok is passes
    if code == 3:
        assert "NOT CONFIRMED" in label and "skip" not in label.lower()


def check_stage_verdict_follows_exit(
    gate: ModuleType,
    script_name: str,
    stage: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    code: int,
) -> None:
    fake = tmp_path / script_name
    fake.write_text(f"print('script says so')\nraise SystemExit({code})\n", encoding="utf-8")
    assert gate.run(fake) == (0 if code == 0 else 1)
    lines = capsys.readouterr().out.rstrip().splitlines()
    assert "script says so" in lines
    assert lines[-1].startswith("OK:" if code == 0 else "FAIL:")
    assert stage in lines[-1]


def check_gate_runs_wrapper_after(stage: str, module: str, previous_stage: str) -> None:
    ps1 = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    stages = re.findall(r'^Invoke-Stage "([^"]+)"\s+\{(.*)\}\s*$', ps1, flags=re.MULTILINE)
    names = [name for name, _ in stages]
    body = dict(stages)[stage]
    assert f"-m scripts.{module}_gate" in body
    assert f"{module}.py" not in body
    assert names.index(stage) == names.index(previous_stage) + 1


def check_stage_enabled_vendored_and_unrouted(key: str) -> None:
    table = FLEET[key]
    assert table["enabled"] is True
    assert (REPO_ROOT / table["baseline"]).is_file()
    assert (REPO_ROOT / FLEET["vendored"][key]["dest"]).is_file()
    config = classify_e2e.load_config(REPO_ROOT / ".fleet.toml")
    assert classify_e2e.classify([table["baseline"]], config).tier == "skip"
