"""Width follows the shape of the view (fleet-config#1113, design.md Layout).

The Board, Table, Today and Archive tabs are two-dimensional (lanes, a many-field
grid, a calendar lane, a run-report grid) and span the window; Search and
Settings are one-dimensional and keep the centred 772px measure. The wide views
are declared in `.fleet.toml` (`[design] wide_views`), which fleet-config's
design review reads, so this pins the declaration to the rendered widths.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from playwright.sync_api import Page

DESKTOP = {"width": 1440, "height": 900}
MEASURE = 772
WIDE = ["board", "table", "today", "archive"]
MEASURED = ["search", "settings"]


def _pane_width(page: Page, tab: str) -> float:
    page.locator(f"nav.tabs .tab[data-tab='{tab}']").click()
    pane = page.locator("[role=tabpanel]:not([hidden])")
    pane.wait_for()
    return pane.evaluate("el => el.getBoundingClientRect().width")


def test_wide_views_declared_and_rendered(webapp: str, page: Page) -> None:
    fleet_toml = Path(__file__).resolve().parents[2] / ".fleet.toml"
    declared = tomllib.loads(fleet_toml.read_text(encoding="utf-8"))["design"]["wide_views"]
    assert declared == WIDE, f".fleet.toml [design] wide_views is {declared}"

    page.set_viewport_size(DESKTOP)
    page.goto(webapp)
    for tab in WIDE:
        width = _pane_width(page, tab)
        assert width >= DESKTOP["width"] * 0.6, f"{tab} is a declared wide view but is {width}px wide"
    for tab in MEASURED:
        width = _pane_width(page, tab)
        assert MEASURE - 1 <= width <= MEASURE + 1, f"{tab} is one-dimensional and must hold the {MEASURE}px measure, got {width}px"
