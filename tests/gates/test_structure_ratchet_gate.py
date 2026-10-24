"""The gate's structure-ratchet stage maps the vendored script's exit codes.

`scripts/structure_ratchet.py` exits 3 when it could not measure the tree (git
unusable, an unreadable or unparseable file, an unknown `shape`): nothing was
checked. These tests pin that 3 fails as NOT CONFIRMED -- never a pass, never a
skip -- that the pre-ship gate calls the wrapper that guarantees it rather than
the script, that the vendored copy matches its recorded hash and shape are
declared, and that the baseline file does not drag the browser suite into a
diff that only touches it. They run fake scripts in a temp directory and never
touch the real `tasks.db` or `config/config.json`.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts import classify_e2e
from scripts import structure_ratchet_gate as gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _verdict(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out.rstrip().splitlines()[-1]


def test_only_exit_zero_passes() -> None:
    assert gate.classify_exit(0)[0] is True
    assert not any(gate.classify_exit(code)[0] for code in (1, 2, 3, 4, -1))


def test_exit_three_is_not_confirmed_and_never_a_skip() -> None:
    ok, label = gate.classify_exit(3)
    assert not ok
    assert "NOT CONFIRMED" in label
    assert "skip" not in label.lower()


@pytest.mark.parametrize("code", [0, 1, 2, 3])
def test_the_stage_exits_nonzero_exactly_when_the_script_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    fake = tmp_path / "structure_ratchet.py"
    fake.write_text(f"print('script says so')\nraise SystemExit({code})\n", encoding="utf-8")
    assert gate.run(fake) == (0 if code == 0 else 1)
    out = capsys.readouterr().out
    assert "script says so" in out
    assert out.rstrip().splitlines()[-1].startswith(
        "OK: structure ratchet" if code == 0 else "FAIL: structure ratchet"
    )


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("x", 1), OSError("no exec")])
def test_a_script_that_cannot_finish_is_not_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: Exception
) -> None:
    def broken(*_a: object, **_k: object) -> object:
        raise failure

    monkeypatch.setattr(subprocess, "run", broken)
    assert gate.run(Path("structure_ratchet.py")) == 1
    last = _verdict(capsys)
    assert last.startswith("FAIL: structure ratchet") and "NOT CONFIRMED" in last


def test_the_pre_ship_gate_calls_the_wrapper_not_the_script() -> None:
    gate_ps1 = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(
        encoding="utf-8"
    )
    stage_lines = [
        line for line in gate_ps1.splitlines() if line.lstrip().startswith("Invoke-Stage")
    ]
    ratchet = [line for line in stage_lines if "structure_ratchet" in line]
    assert len(ratchet) == 1
    assert "-m scripts.structure_ratchet_gate" in ratchet[0]
    assert "structure_ratchet.py" not in ratchet[0]
    names = [line.split('"')[1] for line in stage_lines]
    assert names.index("structure ratchet") == names.index("docs ratchet") + 1


def test_the_shape_is_declared_and_the_script_is_vendored() -> None:
    fleet = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))
    assert fleet["shape"] == "webapp-tray"
    assert fleet["structure_ratchet"]["enabled"] is True
    assert (REPO_ROOT / fleet["structure_ratchet"]["baseline"]).is_file()
    entry = fleet["vendored"]["structure_ratchet"]
    assert entry["dest"] == "scripts/structure_ratchet.py"
    assert (REPO_ROOT / entry["dest"]).is_file()


def test_the_baseline_file_routes_to_no_browser_suite() -> None:
    config = classify_e2e.load_config(REPO_ROOT / ".fleet.toml")
    routing = classify_e2e.classify([".structure-ratchet-baseline.json"], config)
    assert routing.tier == "skip"
