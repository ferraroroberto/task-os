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
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)

TABS = ["Board", "Table", "Tree", "Today", "Search", "Settings"]
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def _version(base: str) -> dict:
    with urllib.request.urlopen(f"{base}/api/version", timeout=5) as res:
        assert res.status == 200
        return json.loads(res.read().decode("utf-8"))


def _assert_shell(page: Page, sha: str) -> None:
    """The parts of the story every surface must show."""
    tabs = page.locator("nav.tabs .tab")
    expect(tabs).to_have_count(len(TABS))
    assert tabs.all_inner_texts() == TABS
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
    expect(page.locator(".home-head .home-title")).to_contain_text("task-os")
    expect(page.locator("#paneBoard .empty-state-message")).to_have_text("Add your first task")
    expect(page.locator("#buildReadout")).to_contain_text(f"Build: {sha}")


def _theme(page: Page) -> str:
    return page.evaluate("document.documentElement.dataset.theme")


def _stored_theme(page: Page) -> str | None:
    return page.evaluate("localStorage.getItem('task-os.theme')")


# --------------------------------------------------------------- API leg

def test_healthz_and_version(webapp: str) -> None:
    with urllib.request.urlopen(f"{webapp}/healthz", timeout=5) as res:
        assert res.status == 200
        assert json.loads(res.read()) == {"ok": True}
    body = _version(webapp)
    assert body["git_sha"] and body["git_sha"] != "unknown"
    assert body["asset_hash"] and body["asset_hash"] != "missing"
    assert body["schema_version"] == 1


# ----------------------------------------------------------- desktop leg

def test_desktop_open_toggle_persist(webapp: str, browser: Browser, shots: Path) -> None:
    sha = _version(webapp)["git_sha"]
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        page.goto(webapp)
        _assert_shell(page, sha)
        assert _theme(page) == "light"
        # PC-first: the app column uses the full width (no 772px cap).
        app_w = page.locator("main.app").evaluate("el => el.getBoundingClientRect().width")
        assert app_w >= DESKTOP["width"] - 40, f"main.app is {app_w}px wide — not full width"
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-01-open-1-desktop.png"))

        # Toggle → dark, persisted, survives a reload.
        page.click("#themeToggle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert _stored_theme(page) == "dark"
        page.screenshot(path=str(shots / "story-01-open-2-desktop.png"))
        page.reload()
        _assert_shell(page, sha)
        assert _theme(page) == "dark", "theme did not persist across reload"

        # Tab switch persists too (nav-tabs storageKey), then back to light.
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("#paneTable")).to_be_visible()
        expect(page.locator("#paneTable .empty-state-message")).to_have_text("Add your first task")
        page.reload()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        page.click("nav.tabs .tab[data-tab='board']")
        page.click("#themeToggle")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        assert _stored_theme(page) == "light"
    finally:
        context.close()


# ------------------------------------------------------------- phone leg

def test_phone_open_pill_toggle(webapp: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): bottom pill, 44px targets, light + dark."""
    sha = _version(webapp)["git_sha"]
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
        _assert_shell(page, sha)

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
        page.screenshot(path=str(shots / "story-01-open-1-phone.png"))

        page.tap("#themeToggle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert _stored_theme(page) == "dark"
        page.screenshot(path=str(shots / "story-01-open-2-phone.png"))
        page.reload()
        assert _theme(page) == "dark"
        context.close()
    finally:
        wk.close()
