"""Story 01 — Open the app.

    Tray icon appears → the browser opens http://127.0.0.1:8448 → an empty
    state says "Add your first task" → the theme toggle flips light/dark (and
    persists) → the footer shows the git SHA from /api/version.

Walks the story against a disposable instance (see conftest) at 1440×900
desktop (the pytest-playwright browser — Chromium by default) and at 390×844
phone (WebKit, iPhone-class emulation: touch → the floating bottom pill), light
and dark, saving the numbered proof shots the validation record links to:

    docs/screenshots/story-01-open-{1,2}-desktop.png   (light, dark)
    docs/screenshots/story-01-open-{1,2}-phone.png     (light, dark)
"""

from __future__ import annotations

import json
import tomllib
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from src.schema import SCHEMA_VERSION
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e.conftest import shot

# Six destinations: the Tree became a view of the Table (#161) and the slot it
# freed went to Archive (#159).
TABS = ["Board", "Table", "Today", "Archive", "Search"]   # Settings is the header gear (#281)
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
MEASURE = 772
WIDE_VIEWS = ["board", "table", "today", "archive"]
MEASURED_VIEWS = ["search", "settings"]


def _version(base: str) -> dict:
    with urllib.request.urlopen(f"{base}/api/version", timeout=5) as res:
        assert res.status == 200
        return json.loads(res.read().decode("utf-8"))


def _assert_shell(page: Page, sha: str, landing: str = "board") -> None:
    """The parts of the story every surface must show. ``landing`` is the tab
    a first visit opens on: the Board on a fine pointer, Today on a touch
    device (Step 5) — both empty panes carry the same first-task prompt."""
    tabs = page.locator("nav.tabs .tab")
    expect(tabs).to_have_count(len(TABS))
    assert tabs.all_inner_texts() == TABS
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", landing)
    expect(page.locator(".home-head .home-title")).to_contain_text("task-os")
    pane = "#paneToday" if landing == "today" else "#paneBoard"
    expect(page.locator(f"{pane} .empty-state-message")).to_have_text("Add your first task")
    expect(page.locator("#buildReadout")).to_contain_text(f"Build: {sha}")


def _theme(page: Page) -> str:
    return page.evaluate("document.documentElement.dataset.theme")


def _stored_theme(page: Page) -> str | None:
    return page.evaluate("localStorage.getItem('task-os.theme')")


def test_story_01_open(
    webapp: str, browser: Browser, playwright: Playwright, shots: Path,
) -> None:
    """The whole story in one test — the suite is capped at 15 (CLAUDE.md), so
    a step gets one test and walks its legs in order: the API answers, the
    desktop opens, the phone opens."""
    _api_leg(webapp)
    sha = _version(webapp)["git_sha"]
    _desktop_leg(webapp, browser, shots, sha)
    _phone_leg(webapp, playwright, shots, sha)


# --------------------------------------------------------------- API leg

def _api_leg(webapp: str) -> None:
    with urllib.request.urlopen(f"{webapp}/healthz", timeout=5) as res:
        assert res.status == 200
        assert json.loads(res.read()) == {"ok": True}
    body = _version(webapp)
    assert body["git_sha"] and body["git_sha"] != "unknown"
    assert body["asset_hash"] and body["asset_hash"] != "missing"
    assert body["schema_version"] == SCHEMA_VERSION


# ----------------------------------------------------------- desktop leg

def _desktop_leg(webapp: str, browser: Browser, shots: Path, sha: str) -> None:
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        page.goto(webapp)
        _assert_shell(page, sha)
        assert _theme(page) == "light"
        # PC-first: the app column uses the full width beside the nav (no 772px
        # cap). At this width the nav is the vendored left rail, so the column
        # runs from the rail's edge to the viewport's, never under it.
        rail = page.locator("nav.tabs").evaluate("el => el.getBoundingClientRect().right")
        app = page.locator("main.app").evaluate(
            "el => { const r = el.getBoundingClientRect(); return {left: r.left, width: r.width}; }")
        assert app["left"] >= rail, f"main.app starts at {app['left']}px, under the {rail}px rail"
        assert app["width"] >= DESKTOP["width"] - rail - 40, f"main.app is {app['width']}px wide — not full width"
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-01-open-1-desktop.png")

        # Toggle → dark, persisted, survives a reload.
        page.click("#themeToggle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert _stored_theme(page) == "dark"
        shot(page, shots / "story-01-open-2-desktop.png")
        page.reload()
        _assert_shell(page, sha)
        assert _theme(page) == "dark", "theme did not persist across reload"

        # Tab switch persists too (nav-tabs storageKey), then back to light.
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("#paneTable")).to_be_visible()
        expect(page.locator("#paneTable .empty-state-message")).to_have_text("Add your first task")
        # The Table's view toggle is hidden while there is nothing to draw, but
        # the palette can still switch the view (#161) — and the host it
        # reveals carries the same prompt, never a blank pane.
        expect(page.locator("#tableViewToggle")).to_be_hidden()
        page.keyboard.press("Control+K")
        page.fill("#paletteInput", ">tree view")
        page.keyboard.press("Enter")
        expect(page.locator("#paneTable #treeHost .empty-state-message")).to_have_text("Add your first task")
        expect(page.locator("#paneTable .empty-state-message")).to_have_count(1)
        page.evaluate("() => localStorage.removeItem('task-os.tableView')")
        page.reload()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        page.click("nav.tabs .tab[data-tab='board']")

        # Width follows the shape of the view (fleet-config#1113, design.md Layout):
        # the two-dimensional tabs span the window, the one-dimensional ones keep the
        # 772px measure. The wide views are declared in `.fleet.toml` (`[design]
        # wide_views`), which fleet-config's design review reads, so this pins the
        # declaration to the rendered widths. Last, because it moves the stored tab.
        _assert_widths(page)
        # The gear opens Settings over the tab it covers (#281): no tab lit while
        # it is up, and a tab press leaves it, as for the journal.
        gear = page.locator("#settingsBtn")
        expect(gear).to_have_attribute("aria-current", "page")
        expect(page.locator("nav.tabs .tab.active")).to_have_count(0)
        _open_palette_from_settings(page, tap=False)
        _walk_text_size(page, tap=False)
        page.click("nav.tabs .tab[data-tab='board']")
        expect(page.locator("#paneSettings")).to_be_hidden()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        expect(gear).not_to_have_attribute("aria-current", "page")
        # The header keeps the spec's two trailing icon buttons (#301): the theme
        # toggle and the gear. Issue sync lives on the Settings card (story 08)
        # and the command palette is Ctrl+K alone (stories 05 / 10 press it).
        expect(page.locator(".home-head .home-toggle")).to_have_count(2)
        expect(page.locator("#paletteBtn, #issuesSync")).to_have_count(0)

        page.click("#themeToggle")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        assert _stored_theme(page) == "light"
    finally:
        context.close()


def _pane_width(page: Page, tab: str) -> float:
    if tab == "settings":                 # no tab since #281: the header gear opens it
        page.locator("#settingsBtn").click()
        pane = page.locator("#paneSettings")
        pane.wait_for()
        return pane.evaluate("el => el.getBoundingClientRect().width")
    page.locator(f"nav.tabs .tab[data-tab='{tab}']").click()
    pane = page.locator("[role=tabpanel]:not([hidden])")
    pane.wait_for()
    return pane.evaluate("el => el.getBoundingClientRect().width")


def _assert_widths(page: Page) -> None:
    fleet_toml = Path(__file__).resolve().parents[2] / ".fleet.toml"
    declared = tomllib.loads(fleet_toml.read_text(encoding="utf-8"))["design"]["wide_views"]
    assert declared == WIDE_VIEWS, f".fleet.toml [design] wide_views is {declared}"
    for tab in WIDE_VIEWS:
        width = _pane_width(page, tab)
        assert width >= DESKTOP["width"] * 0.6, f"{tab} is a declared wide view but is {width}px wide"
    for tab in MEASURED_VIEWS:
        width = _pane_width(page, tab)
        assert MEASURE - 1 <= width <= MEASURE + 1, f"{tab} is one-dimensional and must hold the {MEASURE}px measure, got {width}px"


def _open_palette_from_settings(page: Page, *, tap: bool) -> None:
    """Settings' Command palette card opens the palette (#316): Ctrl+K has no
    phone equivalent since the header lost its palette button (#301). Leaves the
    palette closed and the card shut, as it found them."""
    press = page.tap if tap else page.click
    expect(page.locator("#paneSettings")).to_be_visible()
    press("#paletteCard summary")
    expect(page.locator("#paletteOpen")).to_be_visible()
    if tap:
        assert_min_target(page.locator("#paletteOpen"))
    press("#paletteOpen")
    expect(page.locator("#palette")).to_be_visible()
    expect(page.locator("#paletteInput")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#palette")).not_to_be_visible()
    press("#paletteCard summary")


#: The root font-size each Text size step computes to (text-size.css: 93.75% /
#: 100% / 112.5% of the 16px default).
TEXT_STEPS = {"small": 15.0, "default": 16.0, "large": 18.0}


def _walk_text_size(page: Page, *, tap: bool) -> None:
    """Settings' Text size card (#314): the escape from the viewport zoom lock.

    Each step changes the root font-size, the choice is stored and stamped before
    first paint on reload, an unreadable value falls back to default, and Large
    does not push any pane past the viewport. Leaves the store clean."""
    press = page.tap if tap else page.click
    root_px = lambda: page.evaluate("parseFloat(getComputedStyle(document.documentElement).fontSize)")  # noqa: E731
    html = page.locator("html")
    expect(page.locator("#paneSettings")).to_be_visible()
    assert root_px() == TEXT_STEPS["default"]
    expect(html).to_have_attribute("data-textsize", "default")
    press("#textSizeCard summary")
    expect(page.locator("#textSizeControl")).to_be_visible()
    if tap:
        assert_min_target(page.locator("#textSizeControl .range-tab"))
    for step, px in TEXT_STEPS.items():
        press(f"#textSizeControl [data-textsize='{step}']")
        expect(html).to_have_attribute("data-textsize", step)
        assert root_px() == px, (step, root_px())
        expect(page.locator(f"#textSizeControl [data-textsize='{step}']")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#textSizeControl .range-tab.active")).to_have_count(1)
        expect(page.locator("#textSizeMeta")).to_have_text(step.capitalize())
        assert_no_horizontal_overflow(page)
    # Large is the last step taken: it is stored, and the next load already wears it.
    assert page.evaluate("localStorage.getItem('task-os.textsize')") == "large"
    page.reload()
    expect(html).to_have_attribute("data-textsize", "large")
    assert root_px() == TEXT_STEPS["large"]
    assert_no_horizontal_overflow(page)       # the landing pane at Large
    # …and anything that is not a step falls back to default instead of sticking.
    page.evaluate("localStorage.setItem('task-os.textsize', 'enormous')")
    page.reload()
    expect(html).to_have_attribute("data-textsize", "default")
    assert root_px() == TEXT_STEPS["default"]
    page.evaluate("localStorage.removeItem('task-os.textsize')")


# ------------------------------------------------------------- phone leg

def _phone_leg(webapp: str, playwright: Playwright, shots: Path, sha: str) -> None:
    """390-wide WebKit (iOS-class): bottom pill, 44px targets, light + dark."""
    try:
        wk = playwright.webkit.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — a missing browser is a hard failure, named
        pytest.fail(f"WebKit is required for the phone leg: {exc}")
    try:
        context = wk.new_context(
            viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True,
            color_scheme="light",
        )
        page = context.new_page()
        page.goto(webapp)
        _assert_shell(page, sha, landing="today")

        # The nav is the floating bottom pill: fixed, anchored near the bottom.
        nav = page.locator("nav.tabs")
        assert nav.evaluate("el => getComputedStyle(el).position") == "fixed"
        box = nav.bounding_box()
        assert box is not None
        assert box["y"] + box["height"] > PHONE["height"] - 60, f"pill not at the bottom: {box}"
        assert_min_target(page.locator("nav.tabs .tab"))
        assert_no_overlap(page.locator("nav.tabs .tab"))
        assert_min_target(page.locator("#themeToggle"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-01-open-1-phone.png")

        page.tap("#themeToggle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert _stored_theme(page) == "dark"
        shot(page, shots / "story-01-open-2-phone.png")
        page.reload()
        assert _theme(page) == "dark"
        # The palette has a way in without a hardware keyboard (#316).
        page.tap("#settingsBtn")
        assert_min_target(page.locator("#paletteCard summary"))
        _open_palette_from_settings(page, tap=True)
        _walk_text_size(page, tap=True)
        context.close()
    finally:
        wk.close()
