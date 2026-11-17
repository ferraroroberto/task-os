"""The phone story's sheet-fit walk: every sheet a phone can open — Filters, Quick-add
(folder picker open too) and each Settings sheet — sits wholly inside the viewport at
390x664 and 390x844, light and dark, with its primary action (Done / Add) in view
without scrolling anything.

One browser context and one page serve all four cells (viewport and colour scheme
change in place), so the walk opens no extra sockets. The shots it saves are named in
`test_story_07_phone.py`'s docstring."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, Page, expect

from tests.e2e._geometry import assert_no_horizontal_overflow
from tests.e2e.conftest import settle, shot

SHORT_PHONE = {"width": 390, "height": 664}
TALL_PHONE = {"width": 390, "height": 844}
CELLS = (("light", SHORT_PHONE), ("dark", SHORT_PHONE), ("light", TALL_PHONE), ("dark", TALL_PHONE))


def assert_sheet_fits(page: Page, sheet: str, primary: str, cell: str) -> None:
    """The sheet's box is wholly inside the viewport and its primary action is
    inside the sheet and fully in view, without scrolling anything."""
    fit = page.evaluate("""([s, p]) => {
      const box = q => document.querySelector(q).getBoundingClientRect();
      const a = box(s), b = box(p);
      return { top: a.top, bottom: a.bottom, pTop: b.top, pBottom: b.bottom, height: window.innerHeight };
    }""", [sheet, primary])
    cell = f"{cell}: {fit}"
    assert fit["top"] >= 0 and fit["bottom"] <= fit["height"], cell
    assert fit["pTop"] >= fit["top"] and fit["pBottom"] <= fit["bottom"], cell
    expect(page.locator(primary)).to_be_in_viewport(ratio=1)
    assert_no_horizontal_overflow(page)


def _filters(page: Page, shots: Path, scheme: str, cell: str, short: bool) -> None:
    sheet = page.locator("#filterSheet")
    page.locator("#paneToday .filter-open").tap()
    expect(sheet).to_be_visible()
    settle(page)
    assert_sheet_fits(page, "#filterSheet", "#filterSheet .filter-done", f"filters {cell}")
    if short:
        assert page.evaluate("() => { const b = document.querySelector('#filterSheet .filter-body'); return b.scrollHeight > b.clientHeight + 1; }"), \
            f"the rows are what scrolls on a short phone — filters {cell}"
        shot(page, shots / ("story-07-phone-14-phone.png" if scheme == "light" else "story-07-phone-15-phone.png"))
    sheet.locator(".filter-done").tap()
    expect(sheet).to_be_hidden()


def _quick_add(page: Page, shots: Path, scheme: str, cell: str, short: bool) -> None:
    quick_add = page.locator("#quickAdd")
    page.locator("#paneToday .quick-add-btn").tap()
    expect(quick_add).to_be_visible()
    settle(page)
    assert_sheet_fits(page, "#quickAdd", "#quickAdd .quick-add-submit", f"quick-add {cell}")
    quick_add.locator(".quick-add-pick").tap()
    expect(quick_add.locator("#quickAddPicker")).to_be_visible()
    settle(page)
    assert_sheet_fits(page, "#quickAdd", "#quickAdd .quick-add-submit", f"quick-add picker {cell}")
    if short:
        quick_add.locator("#quickAddPicker").evaluate("el => el.scrollIntoView({ block: 'center' })")
        shot(page, shots / ("story-07-phone-16-phone.png" if scheme == "light" else "story-07-phone-17-phone.png"))
    quick_add.locator(".detail-close").tap()
    expect(quick_add).to_be_hidden()


def _settings_sheets(page: Page, base: str, shots: Path, scheme: str, cell: str, short: bool) -> None:
    page.goto(f"{base}/#settings")
    keys = page.evaluate("""() => [...document.querySelectorAll('#paneSettings [data-settings-sheet]')]
      .filter(r => r.getClientRects().length).map(r => r.dataset.settingsSheet)""")
    assert len(keys) >= 10, keys
    for key in keys:
        page.locator(f'#paneSettings [data-settings-sheet="{key}"]').tap()
        expect(page.locator("#settingsSheet")).to_be_visible()
        settle(page)
        assert_sheet_fits(page, "#settingsSheet", "#settingsSheet .settings-sheet-done", f"settings {key} {cell}")
        if short and key == "timecats" and scheme == "light":
            shot(page, shots / "story-07-phone-18-phone.png")
        page.locator("#settingsSheet .settings-sheet-done").tap()
        expect(page.locator("#settingsSheet")).to_be_hidden()


def walk_sheets_fit(context: BrowserContext, base: str, shots: Path) -> None:
    """Run the four cells on one page of *context*; any page error fails the walk."""
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    for scheme, size in CELLS:
        short = size is SHORT_PHONE
        cell = f"{scheme} {size['height']}"
        page.set_viewport_size(size)
        page.emulate_media(color_scheme=scheme)
        page.goto(f"{base}/")
        expect(page.locator("html")).to_have_attribute("data-theme", scheme)
        _filters(page, shots, scheme, cell, short)
        _quick_add(page, shots, scheme, cell, short)
        _settings_sheets(page, base, shots, scheme, cell, short)
    assert errors == [], errors
