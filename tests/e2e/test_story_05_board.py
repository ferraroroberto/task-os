"""Story 05 — Board day (Step 5/13, issue #6).

    Board tab: five columns visible at once on the laptop → project chip
    filters to one project (shared with the Table, encoded in the URL) → drag
    a card doing → standby → the counts update and the activity log has the
    row → Today tab lists due / overdue grouped by project, recurring first →
    tick a recurring task → its due rolls a cadence forward and it leaves
    Today's due list → tick a plain task → it lands in the Board's Done today.

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-05-board-{1..7}-desktop.png

then the phone at 390×844 (WebKit, touch) — Today as the landing tab, the
Board as a one-column scroll-snap carousel — with the geometry checks:

    docs/screenshots/story-05-board-8-phone.png   (Today, the landing tab)
    docs/screenshots/story-05-board-9-phone.png   (Board carousel, one column)
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
COLUMNS = ["inbox", "todo", "doing", "standby", "done"]


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=5) as res:
        assert res.status == 200
        return json.loads(res.read().decode("utf-8"))


def _card(page: Page, title: str):
    return page.locator(".board-item", has=page.locator(".board-card-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _today_row(page: Page, title: str):
    return page.locator(".today-row", has=page.locator(".today-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _col(page: Page, key: str):
    return page.locator(f".board-col[data-col='{key}']")


def _counts(page: Page) -> dict[str, int]:
    return {k: int(page.locator(f".board-col-count[data-col='{k}']").inner_text()) for k in COLUMNS}


# ----------------------------------------------------------- desktop leg

def test_desktop_board_day(seeded_webapp: str, browser: Browser, shots: Path) -> None:
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. Board is the desktop landing tab; five columns side by side, full width.
        page.goto(f"{base}/")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        cols = page.locator(".board-col")
        expect(cols).to_have_count(5)
        assert cols.evaluate_all("els => els.map(e => e.dataset.col)") == COLUMNS
        boxes = [cols.nth(i).bounding_box() for i in range(5)]
        assert all(b and b["width"] > 200 for b in boxes), boxes
        for a, b in zip(boxes, boxes[1:], strict=False):
            assert a["x"] + a["width"] <= b["x"] + 1, (a, b)   # left to right, no overlap
        assert abs(boxes[0]["y"] - boxes[4]["y"]) < 2                # one row
        assert boxes[4]["x"] + boxes[4]["width"] > DESKTOP["width"] - 40  # uses the full width
        api = _get(base, "/api/board")["columns"]
        counts = _counts(page)
        assert counts == {k: len(api[k]) for k in COLUMNS}, counts
        assert counts["done"] == 0                                    # seed's done tasks are old
        expect(_col(page, "done").locator(".board-empty .empty-state-message")).to_be_visible()
        # a card carries project line · due · person · chips · children · last comment
        # (story 04 may already have edited "Get three quotes" in this session's
        # seeded instance — the checks below use cards it leaves alone)
        quotes = _card(page, "Get three quotes")
        expect(quotes.locator(".board-card-project")).to_have_text("Home renovation")
        expect(quotes.locator(".board-card-person")).to_contain_text("Sam Rivera")
        expect(_card(page, "Kitchen").locator(".board-card-meta .chip-folder")).to_contain_text("{onedrive}/house/kitchen")
        watering = _card(page, "Fix watering schedule drift")
        expect(watering.locator(".board-card-meta a.chip-issue")).to_have_attribute("href", re.compile("garden-bot/issues/12"))
        expect(watering.locator(".board-card-comment a.chip-issue")).to_be_visible()
        expect(_card(page, "Repair fence").locator(".board-card-due")).to_have_class(re.compile("due-overdue"))
        expect(_card(page, "Renew passports").locator(".board-card-kids")).to_have_text("2")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-1-desktop.png"))

        # 2. Project chip → only that project's descendants; the URL carries it;
        #    the Table's own filter bar shows the same selection (shared state).
        home = next(t for t in api["doing"] if t["title"] == "Home renovation")
        page.locator("#boardFilters select[name='project']").select_option(str(home["id"]))
        expect(page).to_have_url(f"{base}/?project={home['id']}")
        filtered = _get(base, f"/api/board?project={home['id']}")["columns"]
        expect(page.locator(".board-col-count[data-col='todo']")).to_have_text(str(len(filtered["todo"])))
        assert _counts(page) == {k: len(filtered[k]) for k in COLUMNS}
        shown = page.locator(".board-item").evaluate_all("els => els.map(e => Number(e.dataset.id))")
        allowed = {t["id"] for col in filtered.values() for t in col}
        assert shown and set(shown) <= allowed
        expect(page.locator("#boardFilters .filter-clear")).to_be_visible()
        page.screenshot(path=str(shots / "story-05-board-2-desktop.png"))
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("#tableFilters select[name='project']")).to_have_value(str(home["id"]))
        expect(page.locator(".task-row").first).to_be_visible()
        page.click("nav.tabs .tab[data-tab='board']")
        page.locator("#boardFilters .filter-clear").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.locator(".board-col-count[data-col='todo']")).to_have_text(str(len(api["todo"])))

        # 3. Drag a card doing → standby: PATCH status, counts update, activity row.
        quotes = _card(page, "Get three quotes")
        qid = int(quotes.get_attribute("data-id"))
        assert quotes.evaluate("el => el.closest('.board-col').dataset.col") == "doing"
        quotes.drag_to(_col(page, "standby"))
        moved = _col(page, "standby").locator(f".board-item[data-id='{qid}']")
        expect(moved).to_be_visible()
        expect(page.locator(".board-col-count[data-col='doing']")).to_have_text(str(len(api["doing"]) - 1))
        expect(page.locator(".board-col-count[data-col='standby']")).to_have_text(str(len(api["standby"]) + 1))
        detail = _get(base, f"/api/tasks/{qid}")
        assert detail["status"] == "standby"
        act = detail["activity"][0]
        assert (act["field"], act["old_value"], act["new_value"]) == ("status", "doing", "standby")
        log = _get(base, f"/api/activity?task={qid}&limit=1")["items"][0]
        assert log["field"] == "status" and log["new_value"] == "standby"
        page.screenshot(path=str(shots / "story-05-board-3-desktop.png"))

        # 4. Card click → the drawer, activity log shows the move.
        moved.locator(".board-card").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(page).to_have_url(f"{base}/#task/{qid}")
        expect(drawer.locator("#drawerTitle")).to_have_value("Get three quotes")
        first_act = drawer.locator(".activity-row").first
        expect(first_act).to_have_attribute("data-field", "status")
        expect(first_act.locator(".activity-old")).to_have_text("doing")
        expect(first_act.locator(".activity-new")).to_have_text("standby")
        # side panel: the columns stay visible to its left
        drawer_box = drawer.bounding_box()
        first_col = _col(page, "inbox").bounding_box()
        assert drawer_box and first_col and first_col["x"] + first_col["width"] < drawer_box["x"]
        page.screenshot(path=str(shots / "story-05-board-4-desktop.png"))
        drawer.locator(".drawer-close").click()
        expect(drawer).to_be_hidden()

        # 5. Today: due ≤ today grouped by root project, overdue first, recurring first.
        page.click("nav.tabs .tab[data-tab='today']")
        expect(page.locator("#paneToday")).to_be_visible()
        today = _get(base, "/api/today")
        expect(page.locator(".today-counts")).to_have_text(
            f"{today['counts']['overdue']} overdue · {today['counts']['today']} due today"
        )
        groups = page.locator(".today-card .today-group")
        expect(groups).to_have_count(len(today["due"]))
        titles = groups.locator(".today-group-title").evaluate_all(
            "els => els.map(e => e.firstChild.textContent.trim())"
        )
        assert titles[0] == "Home renovation" and "Family admin" in titles and "No project" in titles
        # first group holds only overdue rows; a group's recurring rows lead
        expect(groups.first.locator(".today-row.is-overdue")).to_have_count(2)
        fam = groups.filter(has=page.locator(".today-group-link", has_text="Family admin"))
        fam_titles = fam.locator(".today-title").evaluate_all("els => els.map(e => e.textContent)")
        assert fam_titles == ["Dentist check-up", "School enrolment forms"]
        expect(fam.locator(".today-row").first.locator(".today-recur")).to_be_visible()
        # UX round 1 (issue #27): rows are one line — no person on the row
        # (the drawer keeps the person field).
        expect(_today_row(page, "School enrolment forms")).to_be_visible()
        expect(page.locator(".today-card .today-person")).to_have_count(0)
        later = page.locator(".today-later")
        assert later.evaluate("el => el.open") is False              # collapsed by default
        expect(later.locator(".collapse-count")).to_have_text(f"{today['counts']['week']} tasks")
        page.screenshot(path=str(shots / "story-05-board-5-desktop.png"))

        # 6. Tick a recurring task → its due rolls one cadence, it leaves the
        #    due list and shows up under "Later this week".
        vocab = _today_row(page, "Vocabulary review")
        vid = int(vocab.get_attribute("data-id"))
        assert _get(base, f"/api/tasks/{vid}")["recurrence"] == "weekly"
        vocab.locator(".today-check").click()
        next_due = (date.today() + timedelta(days=7)).isoformat()
        expect(page.locator(".toast-success").last).to_contain_text(f"next: {next_due}")
        rolled = _get(base, f"/api/tasks/{vid}")
        assert rolled["due"] == next_due and rolled["status"] == "todo"
        assert rolled["activity"][0]["field"] == "due"
        expect(page.locator(f".today-card .today-row[data-id='{vid}']")).to_have_count(0)
        later.locator("summary").click()
        expect(later.locator(f".today-row[data-id='{vid}']")).to_be_visible()
        expect(page.locator(".today-counts")).to_contain_text(f"{today['counts']['today'] - 1} due today")
        page.screenshot(path=str(shots / "story-05-board-6-desktop.png"))

        # 7. Tick a plain overdue task → done; the Board's Done today gains it.
        books = _today_row(page, "Return library books")
        bid = int(books.get_attribute("data-id"))
        books.locator(".today-check").click()
        expect(page.locator(".toast-success").last).to_contain_text("Done: Return library books")
        expect(page.locator(f".today-card .today-row[data-id='{bid}']")).to_have_count(0)
        done = _get(base, f"/api/tasks/{bid}")
        assert done["status"] == "done" and done["done_at"][:10] == date.today().isoformat()
        page.click("nav.tabs .tab[data-tab='board']")
        expect(_col(page, "done").locator(f".board-item[data-id='{bid}']")).to_be_visible()
        expect(page.locator(".board-col-count[data-col='done']")).to_have_text("1")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-7-desktop.png"))
        assert errors == [], errors
    finally:
        context.close()


# ------------------------------------------------------------- phone leg

def test_phone_today_landing_and_board_carousel(seeded_webapp: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): Today is the landing tab, the Board a
    one-column scroll-snap carousel with the count strip, 44px targets."""
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
        page.goto(f"{base}/")
        # 8. Fresh phone → Today (coarse pointer, nothing persisted yet).
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        expect(page.locator(".today-card .today-row").first).to_be_visible()
        assert_min_target(page.locator(".today-card .today-check"))
        assert_no_overlap(page.locator(".today-card .today-check"))
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-8-phone.png"))

        # 9. Board: strip of five counts + one column per screen (scroll-snap).
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        expect(page.locator("#paneBoard")).to_be_visible()
        strip = page.locator(".board-strip-btn")
        expect(strip).to_have_count(5)
        assert_min_target(strip)
        assert_no_overlap(strip)
        columns = page.locator(".board-columns")
        assert columns.evaluate("el => getComputedStyle(el).scrollSnapType").startswith("x")
        wrap = columns.bounding_box()
        first = _col(page, "inbox").bounding_box()
        assert wrap and first and abs(first["width"] - wrap["width"]) < 2, (wrap, first)
        # exactly one column inside the viewport at a time
        visible = [k for k in COLUMNS if 0 <= _col(page, k).bounding_box()["x"] < PHONE["width"] - 1]
        assert len(visible) == 1, visible
        # tap the strip → the carousel scrolls to that column and marks it active
        page.locator(".board-strip-btn[data-col='doing']").tap()
        expect(page.locator(".board-strip-btn[data-col='doing']")).to_have_class(re.compile(r"\bactive\b"))
        page.wait_for_function(
            "() => Math.abs(document.querySelector(\".board-col[data-col='doing']\").getBoundingClientRect().left"
            " - document.querySelector('.board-columns').getBoundingClientRect().left) < 2"
        )
        # touch fallback for the drag: a compact status select inline on the
        # title line — right-aligned, small control, never a full-width row
        # (UX round 1, issue #27)
        first_item = _col(page, "doing").locator(".board-item").first
        card_select = first_item.locator(".board-card-status")
        expect(card_select).to_be_visible()
        sel_box = card_select.bounding_box()
        title_box = first_item.locator(".board-card-title").bounding_box()
        item_box = first_item.bounding_box()
        assert sel_box and title_box and item_box
        assert sel_box["height"] <= 40, sel_box                      # compact, not a 44px row of its own
        assert sel_box["width"] < item_box["width"] / 2, (sel_box, item_box)   # auto width, not full-width
        assert sel_box["x"] + sel_box["width"] >= item_box["x"] + item_box["width"] - 16, (sel_box, item_box)
        # on the title line: the select's box overlaps the title's vertical band
        assert sel_box["y"] < title_box["y"] + title_box["height"] and sel_box["y"] + sel_box["height"] > title_box["y"], (sel_box, title_box)
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-9-phone.png"))
        context.close()
    finally:
        wk.close()
