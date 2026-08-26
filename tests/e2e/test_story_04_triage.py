"""Story 04 — Monday triage (Step 4/13, issue #5).

    Table filtered status:doing → change a due date inline → the activity log
    shows old → new with time → open a drawer → add a comment containing a
    link → the link is a clickable chip → quick-add "renew passport next
    friday" → the parsed date shows as a chip → create → drag it under a
    project in the Tree → the breadcrumb appears in the Table.

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-04-triage-{1..8}-desktop.png

then the drawer at 390×844 (WebKit, touch) with the geometry checks:

    docs/screenshots/story-04-triage-9-phone.png   (table as the shared rows)
    docs/screenshots/story-04-triage-10-phone.png  (drawer as a full-screen sheet)

UX round 3 (issue #46): the filter state is ONE card shared by every tab and
lives in the URL (``?status=doing`` is the same view on the Board, Table,
Tree, Today), so a shared URL no longer moves the tab by itself — the story
opens the Table explicitly. On the phone the Table renders the ONE shared
task row (``.trow``) instead of a card-ified grid.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e.conftest import _get

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
LINK = "https://example.com/passport-office"


def _next_friday(today: date) -> date:
    coming = today + timedelta(days=(4 - today.weekday()) % 7)
    return coming + timedelta(days=7)


def _row(page: Page, title: str):
    """A desktop Table grid row by exact title (the seed has both "Renew
    passports" and the story's "renew passport")."""
    return page.locator(".task-row", has=page.locator(".t-title-text", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _trow(page: Page, title: str, scope: str = ""):
    """The ONE shared task row (rows.js) by exact title, optionally inside ``scope``."""
    return page.locator(f"{scope} .trow".strip(), has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _open_filters(page: Page, host_id: str):
    """The shared filter card is collapsed by default — open it like a user would."""
    card = page.locator(f"#{host_id} .filter-card")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


# ----------------------------------------------------------- desktop leg

def test_desktop_triage(seeded_webapp: str, browser: Browser, shots: Path) -> None:
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()

        # 1. Table filtered status:doing — via the URL, the shareable view. The
        #    filter is shared by every tab (UX round 3), so the URL never moves
        #    the tab by itself: open the Table, the query survives the switch.
        page.goto(f"{base}/?status=doing")
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        expect(page).to_have_url(f"{base}/?status=doing")
        card = _open_filters(page, "tableFilters")
        # status is a multi-select (#48): the summary reads the one status picked
        status_sel = card.locator(".msel[data-name='status']")
        expect(status_sel.locator(".msel-text")).to_have_text("doing")
        expect(status_sel.locator("input[name='status']:checked")).to_have_count(1)
        expect(status_sel.locator("input[name='status'][value='doing']")).to_be_checked()
        expect(card.locator(".filter-desc")).to_contain_text("doing")
        rows = page.locator(".task-row")
        expect(rows).to_have_count(7)  # the seed's seven `doing` tasks
        expect(card.locator(".filter-desc")).to_contain_text("7 tasks")
        statuses = page.locator(".task-row .trow-status").evaluate_all("els => els.map(e => e.value)")
        assert set(statuses) == {"doing"}
        # breadcrumb under a nested title, project = top ancestor
        quotes = _row(page, "Get three quotes")
        expect(quotes.locator(".t-crumb")).to_have_text("Home renovation › Kitchen")
        expect(quotes.locator(".c-project")).to_have_text("Home renovation")
        # last comment renders its folder placeholder as a chip
        expect(quotes.locator(".c-comment .chip-folder")).to_contain_text("{onedrive}/house/kitchen/plans")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-04-triage-1-desktop.png"))

        # 2. Change a due date inline — natural text into the due editor.
        task_id = int(quotes.get_attribute("data-id"))
        old_due = _get(base, f"/api/tasks/{task_id}")["due"]
        quotes.locator(".due-btn").click()
        editor = quotes.locator(".due-text")
        expect(editor).to_be_visible()
        editor.fill("in 2 weeks")
        editor.press("Enter")
        new_due = (date.today() + timedelta(days=14)).isoformat()
        expect(page.locator(f".task-row[data-id='{task_id}'] .due-btn")).to_have_attribute(
            "title", f"{new_due} — click to change"
        )
        assert _get(base, f"/api/tasks/{task_id}")["due"] == new_due
        page.screenshot(path=str(shots / "story-04-triage-2-desktop.png"))

        # 3. Open the drawer → activity shows due: old → new with actor + time.
        page.locator(f".task-row[data-id='{task_id}']").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(page).to_have_url(f"{base}/?status=doing#task/{task_id}")
        expect(drawer.locator("#drawerTitle")).to_have_value("Get three quotes")
        first_act = drawer.locator(".activity-row").first
        expect(first_act).to_have_attribute("data-field", "due")
        expect(first_act.locator(".activity-old")).to_have_text(old_due)
        expect(first_act.locator(".activity-new")).to_have_text(new_due)
        expect(first_act.locator(".activity-meta")).to_contain_text("Roberto")  # X-Actor default from the sample config
        # The list stays visible beside the drawer (side panel, not an overlay).
        table_box = page.locator(".table-wrap").bounding_box()
        drawer_box = drawer.bounding_box()
        assert table_box and drawer_box and table_box["x"] + table_box["width"] <= drawer_box["x"] + 1
        assert drawer_box["width"] >= 400
        page.screenshot(path=str(shots / "story-04-triage-3-desktop.png"))

        # 4. Add a comment containing a link → chip with href, newest first.
        # UX rounds 1+2 (issues #27/#32): placeholder keeps the Ctrl+Enter
        # hint, quiet ghost Send (the Description Edit tier).
        expect(drawer.locator(".comment-input")).to_have_attribute("placeholder", "Add a comment… (Ctrl+Enter to send)")
        expect(drawer.locator(".comment-send")).to_have_class(re.compile(r"\bbutton-ghost\b"))
        drawer.locator(".comment-input").fill(f"Office booked, details at {LINK} — bring photos")
        drawer.locator(".comment-input").press("Control+Enter")
        newest = drawer.locator(".comment").first
        expect(newest.locator(".comment-body")).to_contain_text("Office booked")
        chip = newest.locator("a.chip")
        expect(chip).to_have_attribute("href", LINK)
        expect(chip).to_have_attribute("target", "_blank")
        expect(chip).to_have_attribute("rel", "noopener")
        expect(newest.locator(".comment-origin")).to_have_text("ui")
        comments = _get(base, f"/api/tasks/{task_id}/comments")["items"]
        assert comments[-1]["origin"] == "ui" and LINK in comments[-1]["body"]
        # …and the Table's last-comment column picked it up
        expect(page.locator(f".task-row[data-id='{task_id}'] .c-comment a.chip")).to_have_attribute("href", LINK)
        page.screenshot(path=str(shots / "story-04-triage-4-desktop.png"))
        # click the chip: opens the link in a new tab (the target is stubbed —
        # the suite never depends on the network)
        context.route(LINK, lambda route: route.fulfill(status=200, content_type="text/html", body="<title>stub</title>ok"))
        with context.expect_page() as popup_info:
            chip.click()
        popup = popup_info.value
        popup.wait_for_load_state()
        assert popup.url == LINK, popup.url
        popup.close()
        drawer.locator(".drawer-close").click()
        expect(drawer).to_be_hidden()

        # 5. Quick-add "renew passport next friday" → parsed date chip.
        qa = page.locator("#paneTable .quick-add-input")
        qa.fill("renew passport next friday")
        friday = _next_friday(date.today()).isoformat()
        date_chip = page.locator("#paneTable .quick-add-chips .chip-date")
        expect(date_chip).to_have_attribute("data-due", friday)
        expect(date_chip).to_contain_text("next friday")
        page.screenshot(path=str(shots / "story-04-triage-5-desktop.png"))

        # 6. Enter creates it; the new row is focused (default filter = open).
        qa.press("Enter")
        expect(page.locator(".toast-success").last).to_contain_text("renew passport")
        # the doing filter hides an inbox task — clear to see it, as a user would
        _open_filters(page, "tableFilters").locator(".filter-clear").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.locator("#tableFilters .msel[data-name='status'] .msel-text")).to_have_text("Open tasks")
        new_row = _row(page, "renew passport")
        expect(new_row).to_be_visible()
        new_id = int(new_row.get_attribute("data-id"))
        created = _get(base, f"/api/tasks/{new_id}")
        assert created["due"] == friday and created["parent_id"] is None
        expect(new_row.locator(".due-btn")).to_have_attribute("title", f"{friday} — click to change")
        page.screenshot(path=str(shots / "story-04-triage-6-desktop.png"))

        # 7. Tree: drag it under a project (Family admin) → moved, toast, rollup.
        page.click("nav.tabs .tab[data-tab='tree']")
        expect(page.locator("#paneTree")).to_be_visible()
        family = page.locator(".tree-node", has=page.locator(":scope > .tree-row .trow-title", has_text="Family admin")).first
        family_id = int(family.get_attribute("data-id"))
        kids_before = int(family.locator(":scope > .tree-row .trow-kids").inner_text())
        # Collapse the four top-level projects so source and target share the
        # viewport (a real user does the same on a long tree); the state persists.
        project_ids = page.locator(".tree-node[aria-level='1'][aria-expanded='true']").evaluate_all(
            "els => els.map(e => e.dataset.id)"
        )
        for pid in project_ids:
            page.locator(f".tree-node[data-id='{pid}'] > .tree-row > .tree-toggle").click()
        expect(page.locator(".tree-node[aria-level='1'][aria-expanded='false']")).to_have_count(4)
        assert page.evaluate("JSON.parse(localStorage.getItem('task-os.tree.collapsed')).length") == 4
        source = page.locator(f".tree-node[data-id='{new_id}']")
        expect(source).to_be_visible()
        expect(source).to_have_attribute("aria-level", "1")
        # UX round 1 (issue #27): the top-level drop zone only shows during a drag
        expect(page.locator(".tree-root-drop")).to_be_hidden()
        source.locator(":scope > .tree-row").drag_to(family.locator(":scope > .tree-row"))
        expect(page.locator(".toast-success").last).to_contain_text("under Family admin")
        moved = _get(base, f"/api/tasks/{new_id}")
        assert moved["parent_id"] == family_id
        assert [c["title"] for c in moved["breadcrumb"]] == ["Family admin"]
        assert moved["activity"][0]["field"] == "parent"
        # the re-render kept the collapse state; expand Family admin to see it nested
        family = page.locator(f".tree-node[data-id='{family_id}']")
        expect(family).to_have_attribute("aria-expanded", "false")
        family.locator(":scope > .tree-row > .tree-toggle").click()
        nested = family.locator(f".tree-children .tree-node[data-id='{new_id}']")
        expect(nested).to_be_visible()
        expect(nested).to_have_attribute("aria-level", "2")
        # the row's children count (the shared row's rollup) grew by one
        expect(family.locator(":scope > .tree-row .trow-kids")).to_have_text(str(kids_before + 1))
        page.screenshot(path=str(shots / "story-04-triage-7-desktop.png"))
        # a cycle is refused and surfaced as a toast, nothing changes (the
        # two-line rows push the nested one below the fold — bring both into
        # the viewport first, as a user scrolling would; a drag that starts
        # while the page scrolls under the pointer would pick up another row)
        nested.locator(":scope > .tree-row").evaluate("el => el.scrollIntoView({block: 'end'})")
        family.locator(":scope > .tree-row").drag_to(nested.locator(":scope > .tree-row"))
        expect(page.locator(".toast-error").last).to_contain_text("cycle")
        assert _get(base, f"/api/tasks/{family_id}")["parent_id"] is None

        # 8. Back in the Table the breadcrumb is there.
        page.click("nav.tabs .tab[data-tab='table']")
        moved_row = page.locator(f".task-row[data-id='{new_id}']")
        expect(moved_row.locator(".t-crumb")).to_have_text("Family admin")
        expect(moved_row.locator(".c-project")).to_have_text("Family admin")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-04-triage-8-desktop.png"))

        # Deep link: a fresh load of #task/<id> opens the drawer with the breadcrumb.
        page.goto(f"{base}/#task/{new_id}")
        expect(page.locator("#taskDrawer")).to_be_visible()
        expect(page.locator("#taskDrawer .drawer-crumbs .crumb")).to_have_text(["Family admin"])
    finally:
        context.close()


# ------------------------------------------------------------- phone leg

def test_phone_table_cards_and_drawer_sheet(seeded_webapp: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): the Table as the shared rows, drawer
    full-screen, 44px targets (the row's status select is the deliberate
    compact exception — ≤32px, centred on the title line, UX rounds 1–3)."""
    base = seeded_webapp
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
        page.goto(f"{base}/?status=doing")
        page.locator("nav.tabs .tab[data-tab='table']").tap()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "table")
        rows = page.locator("#paneTable .table-rows .trow")
        expect(rows).to_have_count(7)
        # phone: the grid is not rendered at all — the Table is the ONE shared
        # row (title + status select, the meta line with the project under it)
        expect(page.locator(".task-table")).to_have_count(0)
        watering = _trow(page, "Fix watering schedule drift", "#paneTable")
        expect(watering.locator(".trow-project")).to_have_text("Side project: garden-bot")
        expect(watering.locator(".trow-due")).to_be_visible()
        expect(watering.locator(".trow-status")).to_have_value("doing")
        assert_no_horizontal_overflow(page)
        assert_min_target(page.locator("#paneTable .quick-add-input"))
        # the shared filter card: the status multi-select holds the six statuses,
        # the URL's one checked; on the phone the controls sit two per line,
        # equal widths (#48)
        card = _open_filters(page, "tableFilters")
        status_sel = card.locator(".msel[data-name='status']")
        status_sel.locator("summary.msel-summary").click()
        expect(status_sel.locator("input[name='status']")).to_have_count(6)
        expect(status_sel.locator("input[name='status'][value='doing']")).to_be_checked()
        page.keyboard.press("Escape")
        boxes = card.locator(".filter-row > .filter-select, .filter-row > .msel").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.width)]; })")
        assert len(boxes) == 6, boxes
        lefts = sorted(set(b[0] for b in boxes))
        assert len(lefts) == 2, boxes                                  # two columns
        assert max(b[1] for b in boxes) - min(b[1] for b in boxes) <= 2, boxes   # equal widths
        # rows are >=44px tall; the status select is compact and, since #74,
        # centred against the WHOLE card (title + meta) rather than the title line
        assert_min_target(rows)
        assert_no_overlap(rows.locator(".trow-status"))
        heights = rows.locator(".trow-status").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and all(h <= 32 for h in heights), heights
        sel_box = watering.locator(".trow-status").bounding_box()
        main_box = watering.locator(".trow-main").bounding_box()
        meta_box = watering.locator(".trow-meta").bounding_box()
        assert sel_box and main_box and meta_box
        sel_center = sel_box["y"] + sel_box["height"] / 2
        rows_center = (main_box["y"] + meta_box["y"] + meta_box["height"]) / 2
        assert abs(sel_center - rows_center) <= 2, (sel_box, main_box, meta_box)
        assert page.locator("#paneTable .table-rows").evaluate("el => getComputedStyle(el).borderRadius") == "0px"
        page.screenshot(path=str(shots / "story-04-triage-9-phone.png"))

        # the drawer is a full-screen sheet; the pill is hidden while it is up
        _trow(page, "Get three quotes", "#paneTable").locator(".trow-main").tap()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        box = drawer.bounding_box()
        assert box and box["width"] >= PHONE["width"] - 1 and box["height"] >= PHONE["height"] - 1, box
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "hidden"
        assert_min_target(drawer.locator(".drawer-close"))
        assert_min_target(drawer.locator(".field-control"))
        assert_min_target(drawer.locator(".comment-send"))
        # UX round 2 (#32): the composer keeps the Ctrl+Enter hint; Send stays
        # on the Description "Edit" tier (ghost, same rendered height).
        expect(drawer.locator(".comment-input")).to_have_attribute(
            "placeholder", "Add a comment… (Ctrl+Enter to send)")
        send_box = drawer.locator(".comment-send").bounding_box()
        edit_box = drawer.locator(".drawer-tools .button-ghost").first.bounding_box()
        assert send_box and edit_box and abs(send_box["height"] - edit_box["height"]) <= 1, (send_box, edit_box)
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-04-triage-10-phone.png"))
        drawer.locator(".drawer-close").tap()
        expect(drawer).to_be_hidden()
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "visible"
        context.close()
    finally:
        wk.close()
