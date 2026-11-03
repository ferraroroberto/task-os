"""The gate's usage-track-ratchet stage maps the vendored script's exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import usage_track_ratchet_gate
from tests.gates._ratchet_gate_cases import (
    FLEET,
    REPO_ROOT,
    check_gate_runs_wrapper_after,
    check_only_exit_zero_passes,
    check_stage_enabled_vendored_and_unrouted,
    check_stage_verdict_follows_exit,
)


@pytest.mark.parametrize(("code", "passes"), [(0, True), (1, False), (2, False), (3, False), (-1, False)])
def test_only_exit_zero_passes(code: int, passes: bool) -> None:
    check_only_exit_zero_passes(usage_track_ratchet_gate, code, passes)


@pytest.mark.parametrize("code", [0, 1, 3])
def test_the_stage_verdict_follows_the_script_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    check_stage_verdict_follows_exit(
        usage_track_ratchet_gate, "usage_track_ratchet.py", "usage track ratchet", tmp_path, capsys, code
    )


def test_the_pre_ship_gate_runs_the_wrapper_right_after_the_runtime_write_ratchet() -> None:
    check_gate_runs_wrapper_after("usage track ratchet", "usage_track_ratchet", "runtime write ratchet")


def test_the_stage_is_enabled_vendored_and_routed_to_no_browser_suite() -> None:
    check_stage_enabled_vendored_and_unrouted("usage_track_ratchet")


def test_the_reader_the_script_loads_is_vendored_too() -> None:
    assert (REPO_ROOT / FLEET["vendored"]["usage_track_scan"]["dest"]).is_file()
