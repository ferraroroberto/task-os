"""Story 07 — Phone (Step 7/13, issue #8).

    Open the tailnet URL on the phone → Add to Home Screen → Today tab → add
    a task → Board carousel swipe → open a drawer full-screen → tap a folder
    chip → the copy-path fallback is shown.

WebKit device emulation (iOS-class) against the **seeded** disposable
instance (``tests/fixtures/seed.py`` — synthetic data, the only dataset
allowed on screen). What a browser can prove of the story:

- the install metadata a phone reads before "Add to Home Screen": the
  manifest is reachable and well-formed (``standalone``, 192/512 + maskable
  icons all 200), the iOS meta tags and touch icon are in the shell;
- 390×844: Today is the landing tab → quick-add a task from Today → the
  Board is a one-column scroll-snap carousel and a swipe (scroll) moves the
  active column → a card opens the drawer full-screen → the folder chip
  carries the ref as a taskos:// opener link (a tap shows the path to copy —
  story 09) → the theme toggle persists across a reload;
- a 430-wide leg (the larger phones) of the same carousel;
- the vendored geometry contract at 320 / 390 / 430 / 772: no horizontal
  overflow, ≥ 44 px targets on the nav pill + the column strip;
- the /login page renders (phone + desktop shot) and signs in with the token
  against an instance booted with a temp config that carries one — the cookie
  comes back and the shell loads. The non-loopback gate itself is unit-level
  (``tests/test_auth.py``: a spoofed client address gets 401 / a redirect).

Screenshots the validation record links to:

    docs/screenshots/story-07-phone-1-phone.png    Today, the landing tab (390)
    docs/screenshots/story-07-phone-2-phone.png    quick-added task in Today
    docs/screenshots/story-07-phone-3-phone.png    Board carousel after a swipe
    docs/screenshots/story-07-phone-4-phone.png    drawer full-screen, folder chip
    docs/screenshots/story-07-phone-5-phone.png    dark theme persisted (Today)
    docs/screenshots/story-07-phone-6-phone.png    Board carousel at 430 wide
    docs/screenshots/story-07-phone-7-phone.png    /login on the phone
    docs/screenshots/story-07-phone-8-desktop.png  /login on the desktop

What no browser can prove — the real iPhone install over the tailnet HTTPS
URL — is recorded **not verified** in docs/validation/story-07-phone.md with
the owner's checklist.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.conftest import write_test_config
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e.conftest import _boot, _terminate

PHONE = {"width": 390, "height": 844}
PHONE_LG = {"width": 430, "height": 932}
DESKTOP = {"width": 1440, "height": 900}
COLUMNS = ["inbox", "todo", "doing", "standby", "done"]
E2E_TOKEN = "e2e-story-07-token"
# E2E_HEADED=1 shows the WebKit window — the headed walk of the same story.
HEADLESS = os.environ.get("E2E_HEADED", "") != "1"


def _col(page: Page, key: str):
    return page.locator(f".board-col[data-col='{key}']")


def _phone_context(pw: Playwright, viewport: dict, scheme: str = "light"):
    return pw.new_context(
        viewport=viewport, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme=scheme,
    )


@pytest.fixture(scope="module")
def authed_webapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A seeded disposable instance whose config carries an auth token — the /login walk."""
    from tests.fixtures.seed import seed_db

    work = tmp_path_factory.mktemp("taskos-e2e-authed")
    seed_db(work / "tasks.db")
    cfg = write_test_config(work / "config.json")           # sample, mirror / backup dirs blanked
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    raw["auth"] = {"token": E2E_TOKEN, "password_hash": ""}
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    proc, base, log = _boot(work, work / "tasks.db", cfg)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


# ---------------------------------------------------------- phone story

def test_phone_install_metadata_and_story(seeded_webapp: str, playwright: Playwright, shots: Path) -> None:
    base = seeded_webapp
    try:
        wk = playwright.webkit.launch(headless=HEADLESS)
    except Exception as exc:  # noqa: BLE001 — a missing browser is a hard failure, named
        pytest.fail(f"WebKit is required for the phone story: {exc}")
    try:
        context = _phone_context(wk, PHONE)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/")

        # 0. "Add to Home Screen" metadata: manifest + icons reachable, iOS tags present.
        manifest_href = page.locator("link[rel='manifest']").get_attribute("href")
        assert manifest_href, "no <link rel=manifest>"
        res = page.request.get(f"{base}{manifest_href}")
        assert res.status == 200, res.status
        manifest = res.json()
        assert manifest["name"] == "task-os" and manifest["display"] == "standalone"
        assert manifest["start_url"] == "/" and manifest["scope"] == "/"
        sizes = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
        assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes, sizes
        for icon in manifest["icons"]:
            r = page.request.get(f"{base}{icon['src']}")
            assert r.status == 200 and r.headers.get("content-type", "").startswith("image/png"), icon
        expect(page.locator("meta[name='apple-mobile-web-app-capable']")).to_have_attribute("content", "yes")
        expect(page.locator("meta[name='apple-mobile-web-app-title']")).to_have_attribute("content", "task-os")
        touch = page.locator("link[rel='apple-touch-icon']").get_attribute("href")
        assert touch and page.request.get(f"{base}{touch}").status == 200
        viewport = page.locator("meta[name='viewport']").get_attribute("content") or ""
        assert "viewport-fit=cover" in viewport and "width=device-width" in viewport
        assert page.locator("meta[name='theme-color']").count() >= 1

        # 1. Fresh phone → Today is the landing tab.
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        expect(page.locator("#paneToday section.today .trow").first).to_be_visible()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-07-phone-1-phone.png"))

        # 2. Quick-add from Today: a task due today lands in the due list.
        qa = page.locator("#paneToday .quick-add-input")
        expect(qa).to_be_visible()
        qa.fill("Water the balcony plants today")
        expect(page.locator("#paneToday .quick-add-chips .chip").first).to_be_visible()   # parsed preview
        qa.press("Enter")
        expect(page.locator(".toast-success").last).to_contain_text("Water the balcony plants")
        added = page.locator("#paneToday section.today .trow", has=page.locator(".trow-title", has_text=re.compile(r"^Water the balcony plants$")))
        expect(added).to_be_visible()
        expect(added.locator(".trow-status")).to_have_value("inbox")   # the ONE row: status select on the line
        new_id = int(added.get_attribute("data-id"))
        detail = page.request.get(f"{base}/api/tasks/{new_id}").json()
        assert detail["title"] == "Water the balcony plants" and detail["due"] is not None
        page.screenshot(path=str(shots / "story-07-phone-2-phone.png"))

        # 3. Board: one-column carousel; a swipe (scroll) moves the active column.
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        expect(page.locator("#paneBoard")).to_be_visible()
        columns = page.locator(".board-columns")
        assert columns.evaluate("el => getComputedStyle(el).scrollSnapType").startswith("x")
        strip = page.locator(".board-strip-btn")
        expect(strip).to_have_count(5)
        assert_min_target(strip)
        assert_no_overlap(strip)
        # the Board opens on Todo (the working column); exactly one column in view
        visible = [k for k in COLUMNS if 0 <= _col(page, k).bounding_box()["x"] < PHONE["width"] - 1]
        assert visible == ["todo"], visible
        # swipe left (a scroll of one column width) → Doing becomes the active column
        columns.evaluate("el => el.scrollBy({left: el.clientWidth, behavior: 'auto'})")
        expect(page.locator(".board-strip-btn[data-col='doing']")).to_have_class(re.compile(r"\bactive\b"))
        visible = [k for k in COLUMNS if 0 <= _col(page, k).bounding_box()["x"] < PHONE["width"] - 1]
        assert visible == ["doing"], visible
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-07-phone-3-phone.png"))

        # 4. Row → drawer full-screen; the folder chip carries the ref (Step 9 made it an opener link).
        columns.evaluate("el => el.scrollBy({left: -el.clientWidth, behavior: 'auto'})")   # swipe back → todo
        expect(page.locator(".board-strip-btn[data-col='todo']")).to_have_class(re.compile(r"\bactive\b"))
        kitchen = page.locator("#paneBoard .trow", has=page.locator(".trow-title", has_text=re.compile(r"^Kitchen$"))).first
        kitchen_col = kitchen.evaluate("el => el.closest('.board-col').dataset.col")
        page.locator(f".board-strip-btn[data-col='{kitchen_col}']").tap()          # the strip is the column switcher
        expect(page.locator(f".board-strip-btn[data-col='{kitchen_col}']")).to_have_class(re.compile(r"\bactive\b"))
        # #74: on the phone the row's folder chip is its bare glyph with a full
        # 44px tap surface - the ref ellipsized at 180px said nothing and its pill
        # was a ~20px target - and the status select centres against the WHOLE row
        # (title + meta), not the title line alone.
        fchip = kitchen.locator(".trow-meta .chip-folder")
        expect(fchip).to_be_visible()
        expect(fchip.locator(".chip-label")).to_be_hidden()
        assert "{onedrive}/house/kitchen" in (fchip.get_attribute("aria-label") or "")
        assert_min_target(fchip)
        # One glyph size on the meta line: the folder reads no heavier than the
        # calendar or the repeat arrows beside it (round 2 of #74).
        sizes = kitchen.locator(".trow-meta .icon").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect();"
            " return [Math.round(r.width), Math.round(r.height)]; })")
        assert sizes and all(sz == [16, 16] for sz in sizes), sizes
        # The 44px surface is INVISIBLE (no fill, no border - the accent glyph is
        # the whole affordance) and stays inside this card: a widened target that
        # reached into the next row would steal that row's taps.
        hit = kitchen.evaluate(
            "el => { const c = el.querySelector('.trow-folder');"
            " const b = getComputedStyle(c, '::before'), cs = getComputedStyle(c);"
            " const cb = c.getBoundingClientRect(), r = el.getBoundingClientRect();"
            " const n = s => parseFloat(s) || 0;"
            " return { top: cb.top + n(b.top), bottom: cb.bottom - n(b.bottom),"
            "  rowTop: r.top, rowBottom: r.bottom, bg: cs.backgroundColor,"
            "  border: cs.borderTopColor }; }")
        assert hit["top"] >= hit["rowTop"] - 0.5, hit
        assert hit["bottom"] <= hit["rowBottom"] + 0.5, hit
        # What actually bounds it: the row's bottom padding is >= the ::before
        # inset, so even a wrapped meta line (glyph flush with the meta's bottom)
        # keeps the target inside this card. Assert the invariant, not the number.
        pad_vs_inset = kitchen.evaluate(
            "el => { const c = el.querySelector('.trow-folder');"
            " return [parseFloat(getComputedStyle(el).paddingBottom),"
            "  -parseFloat(getComputedStyle(c, '::before').bottom)]; }")
        assert pad_vs_inset[0] >= pad_vs_inset[1], pad_vs_inset
        assert hit["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), hit
        assert hit["border"] in ("rgba(0, 0, 0, 0)", "transparent"), hit
        sel = kitchen.locator(".trow-status")
        # ONE locator, so both rects are measured in a single evaluate_all:
        # the Board is a scroll-snapping carousel and two separate
        # measurements can land at different scroll offsets.
        assert_no_overlap(kitchen.locator(".trow-meta .chip-folder, .trow-status"))
        main_box = kitchen.locator(".trow-main").bounding_box()
        meta_box = kitchen.locator(".trow-meta").bounding_box()
        sel_box = sel.bounding_box()
        title_box = kitchen.locator(".trow-title").bounding_box()
        assert main_box and meta_box and sel_box and title_box
        rows_centre = (main_box["y"] + meta_box["y"] + meta_box["height"]) / 2
        sel_centre = sel_box["y"] + sel_box["height"] / 2
        assert abs(sel_centre - rows_centre) <= 2, (sel_box, main_box, meta_box)
        assert sel_centre > title_box["y"] + title_box["height"] / 2 + 2, (sel_box, title_box)
        # ... and centred on the CARD, not just on title+meta: an empty third grid
        # track used to add a trailing row-gap that put the card's centre 3px
        # below the select's, and the 1px hairline another half (#74).
        row_box = kitchen.bounding_box()
        assert row_box and abs(sel_centre - (row_box["y"] + row_box["height"] / 2)) <= 0.5, (sel_box, row_box)
        kitchen.locator(".trow-main").tap()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")
        # UX round 2 (#32): on the phone the code line sits ABOVE the title
        # (never inline pushing it off-screen) and a long title wraps to more
        # lines instead of clipping sideways (textarea + fit, no ellipsis).
        title_el = drawer.locator("#drawerTitle")
        code_box = drawer.locator(".drawer-code").bounding_box()
        t_box = title_el.bounding_box()
        assert code_box and t_box and code_box["y"] + code_box["height"] <= t_box["y"] + 1, (code_box, t_box)
        one_line_h = title_el.evaluate("el => el.clientHeight")
        wrapped = title_el.evaluate(
            "el => { const v = el.value;"
            " el.value = 'a very long task title that would have clipped off the right edge before round two';"
            " el.dispatchEvent(new Event('input'));"
            " const grown = {h: el.clientHeight, fits: el.scrollWidth <= el.clientWidth + 1};"
            " el.value = v; el.dispatchEvent(new Event('input')); return grown; }")
        assert wrapped["h"] > one_line_h and wrapped["fits"], (one_line_h, wrapped)
        box = drawer.bounding_box()
        assert box and box["x"] <= 1 and box["width"] >= PHONE["width"] - 2 and box["height"] >= PHONE["height"] - 2, box
        # Step 9: the chip is a taskos:// link (the per-PC opener); on a phone a
        # tap shows the path to copy instead of navigating (story 09 walks that).
        chip = drawer.locator(".drawer-folder .chip-folder").first
        expect(chip).to_be_visible()
        expect(chip).to_have_text("{onedrive}/house/kitchen")
        assert chip.evaluate("el => el.tagName") == "A"
        assert (chip.get_attribute("href") or "").startswith("taskos://open?ref=%7Bonedrive%7D")
        link_chip = drawer.locator(".drawer-links .chip-folder").first
        expect(link_chip).to_have_text(re.compile("Kitchen folder"))
        assert "{onedrive}/house/kitchen" in (link_chip.get_attribute("title") or "")   # the unresolved ref, per PC
        assert_min_target(drawer.locator(".drawer-close"))
        page.locator(".toast .toast-close").evaluate_all("els => els.forEach(b => b.click())")   # clear the quick-add toast
        expect(page.locator(".toast")).to_have_count(0)
        page.screenshot(path=str(shots / "story-07-phone-4-phone.png"))
        drawer.locator(".drawer-close").tap()
        expect(drawer).to_be_hidden()

        # 5. Theme toggle → dark; a reload keeps it (localStorage) and the tab.
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        page.locator("#themeToggle").tap()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.reload()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        expect(page.locator("#paneToday section.today .trow").first).to_be_visible()
        page.screenshot(path=str(shots / "story-07-phone-5-phone.png"))
        assert errors == [], errors
        context.close()

        # 6. The 430-wide leg: same carousel, one column at a time.
        context = _phone_context(wk, PHONE_LG)
        page = context.new_page()
        page.goto(f"{base}/")
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        wrap = page.locator(".board-columns").bounding_box()
        first = _col(page, "inbox").bounding_box()
        assert wrap and first and abs(first["width"] - wrap["width"]) < 2, (wrap, first)
        visible = [k for k in COLUMNS if 0 <= _col(page, k).bounding_box()["x"] < PHONE_LG["width"] - 1]
        assert len(visible) == 1, visible
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-07-phone-6-phone.png"))
        context.close()

        # 7. Geometry contract across the phone widths + the tablet edge.
        for width in (320, 390, 430, 772):
            context = _phone_context(wk, {"width": width, "height": 844})
            page = context.new_page()
            page.goto(f"{base}/")
            expect(page.locator("#paneToday section.today .trow").first).to_be_visible()
            assert_no_horizontal_overflow(page)
            tabs = page.locator("nav.tabs .tab")
            # The vendored nav is the floating pill on the phone widths (fixed)
            # and the desktop segmented control at 772 (its own, smaller
            # geometry). Six pill tabs at 320 wide are ~42px across — the
            # component's auto-fit, not this app's — so the 44px floor is
            # asserted on the pill from 390 up and the height floor at 320.
            pill = page.locator("nav.tabs").evaluate("el => getComputedStyle(el).position") == "fixed"
            assert pill == (width < 772), (width, pill)
            if pill and width >= 390:
                assert_min_target(tabs)
            elif pill:
                assert all(b["height"] >= 44 for b in tabs.evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())"))
            assert_no_overlap(tabs)
            page.locator("nav.tabs .tab[data-tab='board']").tap()
            expect(page.locator(".board-strip-btn").first).to_be_visible()
            assert_min_target(page.locator(".board-strip-btn"))
            assert_no_horizontal_overflow(page)
            context.close()
    finally:
        wk.close()


# ------------------------------------------------------------- login page

def test_login_page_and_token_sign_in(authed_webapp: str, playwright: Playwright, browser: Browser, shots: Path) -> None:
    base = authed_webapp
    # phone: the page renders (vendored card, one field) and a wrong secret is refused
    wk = playwright.webkit.launch(headless=HEADLESS)
    try:
        context = _phone_context(wk, PHONE)
        page = context.new_page()
        page.goto(f"{base}/login?next=%2F%23task%2F1")
        expect(page.locator("#loginForm.card")).to_be_visible()
        expect(page.locator("#loginSecret")).to_be_focused()
        assert_min_target(page.locator("#loginSubmit"))
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-07-phone-7-phone.png"))
        page.fill("#loginSecret", "not-the-token")
        page.locator("#loginSubmit").tap()
        expect(page.locator("#loginError")).to_have_text("wrong token or password")
        # the token → cookie → the shell, deep link preserved
        page.fill("#loginSecret", E2E_TOKEN)
        page.locator("#loginSubmit").tap()
        expect(page.locator("nav.tabs .tab.active")).to_be_visible()
        assert page.url == f"{base}/#task/1"
        names = {c["name"]: c for c in context.cookies()}
        assert "taskos_token" in names and names["taskos_token"]["httpOnly"] is True
        expect(page.locator("#taskDrawer")).to_be_visible()
        # Settings → Phone access: the token is configured; this browser is on
        # loopback, so it reads as the owner ("this PC") — a phone reads "signed in".
        page.locator("#taskDrawer .drawer-close").tap()
        page.locator("nav.tabs .tab[data-tab='settings']").tap()
        expect(page.locator("#accessClient")).to_have_text("this PC")
        expect(page.locator("#accessRows")).to_contain_text("configured")
        st = page.request.get(f"{base}/api/status").json()
        assert st["auth"]["enabled"] is True and st["https"] is False
        context.close()
    finally:
        wk.close()
    # desktop shot of the same page
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        page.goto(f"{base}/login")
        expect(page.locator("#loginForm.card")).to_be_visible()
        page.screenshot(path=str(shots / "story-07-phone-8-desktop.png"))
    finally:
        context.close()
