"""The gate's conventions-ratchet stage maps the vendored script's exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet_gate
from tests.gates._ratchet_gate_cases import (
    check_gate_runs_wrapper_after,
    check_only_exit_zero_passes,
    check_stage_enabled_vendored_and_unrouted,
    check_stage_verdict_follows_exit,
)


@pytest.mark.parametrize(("code", "passes"), [(0, True), (1, False), (2, False), (3, False), (-1, False)])
def test_only_exit_zero_passes(code: int, passes: bool) -> None:
    check_only_exit_zero_passes(conventions_ratchet_gate, code, passes)


@pytest.mark.parametrize("code", [0, 1, 3])
def test_the_stage_verdict_follows_the_script_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    check_stage_verdict_follows_exit(
        conventions_ratchet_gate, "conventions_ratchet.py", "conventions ratchet", tmp_path, capsys, code
    )


def test_the_pre_ship_gate_runs_the_wrapper_right_after_the_dead_code_ratchet() -> None:
    check_gate_runs_wrapper_after("conventions ratchet", "conventions_ratchet", "dead-code ratchet")


def test_the_stage_is_enabled_vendored_and_routed_to_no_browser_suite() -> None:
    check_stage_enabled_vendored_and_unrouted("conventions_ratchet")
