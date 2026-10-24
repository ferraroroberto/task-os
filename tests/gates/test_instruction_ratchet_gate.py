"""The gate's instruction-ratchet stage maps the vendored script's exit codes.

`scripts/instruction_ratchet.py` exits 3 when it could not measure the
instruction files (git unusable, an unreadable file, a skill description it
cannot read): nothing was checked. These tests pin that 3 fails as NOT
CONFIRMED -- never a pass, never a skip -- that the pre-ship gate calls the
wrapper that guarantees it rather than the script, that the vendored copy is
declared and its baseline exists, and that the baseline file does not drag the
browser suite into a diff that only touches it. They run fake scripts in a temp
directory and never touch the real `tasks.db` or `config/config.json`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scripts import classify_e2e
from scripts import instruction_ratchet_gate as gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_only_exit_zero_passes() -> None:
    assert gate.classify_exit(0)[0] is True
    assert not any(gate.classify_exit(code)[0] for code in (1, 2, 3, 4, -1))


def test_exit_three_is_not_confirmed_and_never_a_skip() -> None:
    ok, label = gate.classify_exit(3)
    assert not ok
    assert "NOT CONFIRMED" in label
    assert "skip" not in label.lower()


@pytest.mark.parametrize("code", [0, 1, 3])
def test_the_stage_exits_nonzero_exactly_when_the_script_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    fake = tmp_path / "instruction_ratchet.py"
    fake.write_text(f"print('script says so')\nraise SystemExit({code})\n", encoding="utf-8")
    assert gate.run(fake) == (0 if code == 0 else 1)
    out = capsys.readouterr().out
    assert "script says so" in out
    assert out.rstrip().splitlines()[-1].startswith(
        "OK: instruction ratchet" if code == 0 else "FAIL: instruction ratchet"
    )


def test_the_pre_ship_gate_calls_the_wrapper_after_the_structure_ratchet() -> None:
    gate_ps1 = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(
        encoding="utf-8"
    )
    stage_lines = [
        line for line in gate_ps1.splitlines() if line.lstrip().startswith("Invoke-Stage")
    ]
    ratchet = [line for line in stage_lines if "instruction_ratchet" in line]
    assert len(ratchet) == 1
    assert "-m scripts.instruction_ratchet_gate" in ratchet[0]
    assert "instruction_ratchet.py" not in ratchet[0]
    names = [line.split('"')[1] for line in stage_lines]
    assert names.index("instruction ratchet") == names.index("structure ratchet") + 1


def test_the_stage_is_enabled_and_the_script_is_vendored() -> None:
    fleet = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))
    assert fleet["instruction_ratchet"]["enabled"] is True
    assert (REPO_ROOT / fleet["instruction_ratchet"]["baseline"]).is_file()
    entry = fleet["vendored"]["instruction_ratchet"]
    assert entry["dest"] == "scripts/instruction_ratchet.py"
    assert (REPO_ROOT / entry["dest"]).is_file()


def test_the_baseline_file_routes_to_no_browser_suite() -> None:
    config = classify_e2e.load_config(REPO_ROOT / ".fleet.toml")
    routing = classify_e2e.classify([".instruction-ratchet-baseline.json"], config)
    assert routing.tier == "skip"
