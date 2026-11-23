"""The gate's request-budget-ratchet stage maps the vendored script's exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import request_budget_ratchet_gate
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
    check_only_exit_zero_passes(request_budget_ratchet_gate, code, passes)


@pytest.mark.parametrize("code", [0, 1, 3])
def test_the_stage_verdict_follows_the_script_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    check_stage_verdict_follows_exit(
        request_budget_ratchet_gate, "request_budget_ratchet.py", "request budget ratchet", tmp_path, capsys, code
    )


def test_the_pre_ship_gate_runs_the_wrapper_right_after_the_ux_surface_ratchet() -> None:
    check_gate_runs_wrapper_after("request budget ratchet", "request_budget_ratchet", "ux surface ratchet")


def test_the_stage_is_enabled_vendored_and_routed_to_no_browser_suite() -> None:
    check_stage_enabled_vendored_and_unrouted("request_budget_ratchet")


def test_the_reader_the_script_loads_is_vendored_too() -> None:
    assert (REPO_ROOT / FLEET["vendored"]["request_budget_scan"]["dest"]).is_file()


def test_the_tree_holds_no_request_budget_debt_and_every_declared_loop_is_real() -> None:
    """The baseline is empty, so the tree must hold no hit at all; a loop declaration that
    no loop matches any more would excuse nothing and only hide the next one."""
    from scripts import request_budget_ratchet as ratchet

    cfg, vendored = ratchet.load_config(REPO_ROOT)
    assert cfg is not None
    tree = ratchet.scan_tree(REPO_ROOT, cfg, vendored)
    assert tree.found == {}
    assert tree.stale_loops == []
    assert set(cfg.loops) == {"app/tray/tray.py", "app/webapp/manager.py", "src/mirror.py", "src/poller.py"}
    assert {(path, rule) for path, _line, rule, _why in tree.exempted} == {
        ("app/webapp/static/js/time/frame.js", "fixed-rate-poll"),
        ("app/webapp/static/js/time/frame.js", "poll-floor"),
    }
