"""The gate's dead-code-ratchet stage maps the vendored script's exit codes.

`scripts/dead_code_ratchet.py` exits 3 when it could not read the tracked Python
tree (git unusable, a file that cannot be read or does not parse): nothing was
checked. These tests pin that 3 fails as NOT CONFIRMED -- never a
pass, never a skip -- and that the pre-ship gate, `.fleet.toml` and the e2e
routing carry the stage. They run fake scripts in a temp directory and never
touch the real `tasks.db` or `config/config.json`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from scripts import classify_e2e, dead_code_ratchet_gate

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("code", "passes"), [(0, True), (1, False), (2, False), (3, False), (-1, False)])
def test_only_exit_zero_passes(code: int, passes: bool) -> None:
    ok, label = dead_code_ratchet_gate.classify_exit(code)
    assert ok is passes
    if code == 3:
        assert "NOT CONFIRMED" in label and "skip" not in label.lower()


@pytest.mark.parametrize("code", [0, 1, 3])
def test_the_stage_verdict_follows_the_script_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    fake = tmp_path / "dead_code_ratchet.py"
    fake.write_text(f"print('script says so')\nraise SystemExit({code})\n", encoding="utf-8")
    assert dead_code_ratchet_gate.run(fake) == (0 if code == 0 else 1)
    lines = capsys.readouterr().out.rstrip().splitlines()
    assert "script says so" in lines
    assert lines[-1].startswith("OK:" if code == 0 else "FAIL:")
    assert "dead-code ratchet" in lines[-1]


def test_the_pre_ship_gate_runs_the_wrapper_right_after_the_doc_refs_ratchet() -> None:
    ps1 = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    stages = re.findall(r'^Invoke-Stage "([^"]+)"\s+\{(.*)\}\s*$', ps1, flags=re.MULTILINE)
    names = [name for name, _ in stages]
    body = dict(stages)["dead-code ratchet"]
    assert "-m scripts.dead_code_ratchet_gate" in body
    assert "dead_code_ratchet.py" not in body
    assert names.index("dead-code ratchet") == names.index("doc-refs ratchet") + 1


def test_the_stage_is_enabled_vendored_and_routed_to_no_browser_suite() -> None:
    table = FLEET["dead_code_ratchet"]
    assert table["enabled"] is True
    assert (REPO_ROOT / table["baseline"]).is_file()
    assert (REPO_ROOT / FLEET["vendored"]["dead_code_ratchet"]["dest"]).is_file()
    config = classify_e2e.load_config(REPO_ROOT / ".fleet.toml")
    assert classify_e2e.classify([table["baseline"]], config).tier == "skip"
