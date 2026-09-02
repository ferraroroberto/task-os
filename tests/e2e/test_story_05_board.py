"""Story 05 — Board day (Step 5/13, issue #6).

    Board tab: five columns visible at once on the laptop → the top strip's
    text filter narrows the board without opening any disclosure and the +
    opens the quick-add dialog (#80) → project chip
    filters to one project (shared with the Table, encoded in the URL) → drag
    a row doing → standby → the counts update and the activity log has the
    row → Today tab lists due / overdue grouped by project, sorted by due
    then priority within a group → mark a recurring task complete → its due
    rolls a cadence forward and it
    leaves Today's due list, then mark it done instead → it closes for good
    (issue #54) → mark a plain task done → it lands in the Board's Done
    today.

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-05-board-{1..7}-desktop.png
    docs/screenshots/story-05-board-{10..12}-desktop.png   (§ #81, below)

then the phone at 390×844 (WebKit, touch) — Today as the landing tab, the
Board as a one-column scroll-snap carousel — with the geometry checks:

    docs/screenshots/story-05-board-8-phone.png   (Today, the landing tab)
    docs/screenshots/story-05-board-9-phone.png   (Board carousel, one column)
    docs/screenshots/story-05-board-10-phone.png  (§ #81 Select mode + bulk bar)

§ #81 (multi-select, folded into this story rather than a 15th e2e test, the
way #77 rides inside story 09): Select mode across Board and Table over ONE
selection store, the bulk status / due actions, and the partial-failure
report. Story 12 in ``docs/validation.md`` points here.

§ #99 (``_walk_keyboard_actions``, same reason): a keyboard-only triage —
the row keys and their undo, the inert-while-typing and inert-while-the-
drawer-is-open guards, the same keys over a selection, the `?` sheet and the
palette entries that carry them. Story 16 points here.

    docs/screenshots/story-16-keyboard-triage-{1..5}-desktop.png

§ #102 (``_walk_done_journal``, same reason): the done journal — reached
from the Done column's link and the palette, days newest first with counts,
the seed's own closings (yesterday · two days back with a cancelled row ·
the week before), the cancelled switch, the shared filters riding the URL
with the status / due / modified / sort controls hidden, "the week before"
loading older weeks down to the seed's first closing day, the drawer under
``#journal/task/<id>``, and a tab press leaving. Story 18 points here.

    docs/screenshots/story-18-done-journal-{1,2}-desktop.png
    docs/screenshots/story-18-done-journal-3-phone.png   (phone leg, below)

§ #121 (``_walk_delete_task``, same reason): deleting a task — the drawer's
Delete and its confirmation naming the task and the subtree that goes with
it, cancel leaving everything untouched, confirm closing the drawer with a
toast and a 404 behind it, then the Select bar's delete over a batch of
mistakes. The walk makes its own tasks over the API so the seed stays whole.
Story 19 points here.

    docs/screenshots/story-19-delete-task-{1,2}-desktop.png

UX round 3 (issue #46): every view renders the ONE task row (``.trow`` —
title + status select on line 1, the meta line under it) and shares ONE
filter card; the Today checkbox is gone — "ticking" is the row's status
select, on every pointer. Today's done tasks ride in the shared list only
for the Board's Done today column: Table, Tree and Today keep showing open
tasks (as the filter card says), so a task finished today leaves the Today
list and appears in the Board's Done today column.
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
COLUMNS = ["inbox", "todo", "doing", "standby", "done"]


def _trow(page: Page, scope: str, title: str):
    """The ONE shared task row (rows.js) by exact title inside ``scope``."""
    return page.locator(f"{scope} .trow", has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _card(page: Page, title: str):
    return _trow(page, "#paneBoard", title)


def _today_row(page: Page, title: str):
    # the due list only — "Later this week" is the sibling disclosure
    return _trow(page, "#paneToday section.today", title)


def _col(page: Page, key: str):
    return page.locator(f".board-col[data-col='{key}']")


def _counts(page: Page) -> dict[str, int]:
    return {k: int(page.locator(f".board-col-count[data-col='{k}']").inner_text()) for k in COLUMNS}


def _open_filters(page: Page, host_id: str):
    """The shared filter card is collapsed by default — open it like a user would."""
    card = page.locator(f"#{host_id} .filter-card")
    expect(card).to_be_visible()
    if not card.evaluate("el => el.open"):
        card.locator("summary.collapse-summary").click()
    expect(card).to_have_attribute("open", "")
    return card


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
        expect(_col(page, "done").locator(".board-col-title")).to_have_text(re.compile(r"^Done today"))
        expect(_col(page, "done").locator(".board-empty .empty-state-message")).to_be_visible()
        # a row = title + status select on line 1, then the meta line: project ·
        # due · priority · chips · children · comment COUNT · person — never the
        # comment body (UX round 2, issue #32; the ONE row of round 3, #46)
        # (story 04 may already have edited "Get three quotes" in this session's
        # seeded instance — the checks below use rows it leaves alone)
        quotes = _card(page, "Get three quotes")
        expect(quotes.locator(".trow-status")).to_have_value("doing")
        expect(quotes.locator(".trow-project")).to_have_text("Home renovation")
        expect(quotes.locator(".trow-person")).to_contain_text("Sam Rivera")
        expect(_card(page, "Kitchen").locator(".trow-meta .chip-folder")).to_contain_text("{onedrive}/house/kitchen")
        watering = _card(page, "Fix watering schedule drift")
        expect(watering.locator(".trow-meta a.chip-issue")).to_have_attribute("href", re.compile("garden-bot/issues/12"))
        expect(watering.locator(".trow-comments")).to_have_text("1")
        expect(page.locator("#paneBoard .trow-comments").first).to_have_text(re.compile(r"^\d+$"))
        expect(page.locator("#paneBoard .t-comment")).to_have_count(0)   # the body bloated the cards
        expect(_card(page, "Repair fence").locator(".trow-due")).to_have_class(re.compile("due-overdue"))
        expect(_card(page, "Renew passports").locator(".trow-kids")).to_have_text("2")
        # flat regions, not cards: no rounded box on a column (issue #32)
        for k in COLUMNS:
            assert _col(page, k).evaluate("el => getComputedStyle(el).borderRadius") == "0px", k
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-1-desktop.png"))

        # 2. The top strip (#80): the text filter is on screen without opening
        #    anything — typing filters the board live — and the + opens the one
        #    quick-add dialog, whose Escape discards the draft.
        q = page.locator("#boardFilterText .filter-q")
        expect(q).to_be_visible()
        filter_card = page.locator("#boardFilters .filter-card")
        assert not filter_card.evaluate("el => el.open")        # still collapsed
        q.fill("passport")
        expect(page).to_have_url(f"{base}/?q=passport")
        expect(_card(page, "Renew passports")).to_be_visible()
        expect(_card(page, "Repair fence")).to_have_count(0)
        assert not filter_card.evaluate("el => el.open")        # never had to open
        q.fill("")
        expect(page).to_have_url(f"{base}/")
        page.locator("#paneBoard .quick-add-btn").click()
        quick_add = page.locator("#quickAdd")
        expect(quick_add).to_be_visible()
        quick_add.locator(".quick-add-input").fill("Order fence paint tomorrow")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        expect(quick_add.locator(".quick-add-due")).to_have_value(tomorrow)
        page.keyboard.press("Escape")                            # discards the draft
        expect(quick_add).to_be_hidden()
        assert not any(t["title"].startswith("Order fence paint")
                       for col in _get(base, "/api/board")["columns"].values() for t in col)

        # 3. Project filter → only that project's descendants; the URL carries it;
        #    the Table's card shows the same selection (one shared state).
        home = next(t for t in api["doing"] if t["title"] == "Home renovation")
        card = _open_filters(page, "boardFilters")
        card.locator("select[name='project']").select_option(str(home["id"]))
        expect(page).to_have_url(f"{base}/?project={home['id']}")
        expect(card.locator(".filter-desc")).to_contain_text("Home renovation")
        filtered = _get(base, f"/api/board?project={home['id']}")["columns"]
        expect(page.locator(".board-col-count[data-col='todo']")).to_have_text(str(len(filtered["todo"])))
        assert _counts(page) == {k: len(filtered[k]) for k in COLUMNS}
        shown = page.locator("#paneBoard .board-list .trow").evaluate_all("els => els.map(e => Number(e.dataset.id))")
        allowed = {t["id"] for col in filtered.values() for t in col}
        assert shown and set(shown) <= allowed
        expect(card.locator(".filter-clear")).to_be_visible()
        page.screenshot(path=str(shots / "story-05-board-2-desktop.png"))
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("#tableFilters select[name='project']")).to_have_value(str(home["id"]))
        expect(page.locator("#tableFilters .filter-desc")).to_contain_text("Home renovation")
        expect(page.locator(".task-row").first).to_be_visible()
        page.click("nav.tabs .tab[data-tab='board']")
        _open_filters(page, "boardFilters").locator(".filter-clear").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.locator(".board-col-count[data-col='todo']")).to_have_text(str(len(api["todo"])))

        # 4. Drag a row doing → standby: PATCH status, counts update, activity row.
        quotes = _card(page, "Get three quotes")
        qid = int(quotes.get_attribute("data-id"))
        assert quotes.evaluate("el => el.closest('.board-col').dataset.col") == "doing"
        # both ends in the viewport first (a page that scrolls under the
        # pointer mid-drag would pick up whichever row slides under it)
        _col(page, "standby").scroll_into_view_if_needed()
        quotes.drag_to(_col(page, "standby"))
        moved = _col(page, "standby").locator(f".trow[data-id='{qid}']")
        expect(moved).to_be_visible()
        expect(moved.locator(".trow-status")).to_have_value("standby")
        expect(page.locator(".board-col-count[data-col='doing']")).to_have_text(str(len(api["doing"]) - 1))
        expect(page.locator(".board-col-count[data-col='standby']")).to_have_text(str(len(api["standby"]) + 1))
        detail = _get(base, f"/api/tasks/{qid}")
        assert detail["status"] == "standby"
        act = detail["activity"][0]
        assert (act["field"], act["old_value"], act["new_value"]) == ("status", "doing", "standby")
        log = _get(base, f"/api/activity?task={qid}&limit=1")["items"][0]
        assert log["field"] == "status" and log["new_value"] == "standby"
        page.screenshot(path=str(shots / "story-05-board-3-desktop.png"))

        # 5. Row click → the drawer, activity log shows the move.
        moved.locator(".trow-main").click()
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

        # 6. Today: due ≤ today grouped by root project, overdue first, sorted
        #    by due then priority within a group — recurring or not (#116).
        page.click("nav.tabs .tab[data-tab='today']")
        expect(page.locator("#paneToday")).to_be_visible()
        today = _get(base, "/api/today")
        # scoped: My plan (#89) has a .today-counts of its own above this one
        due_counts = page.locator("section.today:not(.today-plan) > .today-head .today-counts")
        expect(due_counts).to_have_text(
            f"{today['counts']['overdue']} overdue · {today['counts']['today']} due today"
        )
        groups = page.locator("#paneToday section.today .today-group")
        expect(groups).to_have_count(len(today["due"]))
        titles = groups.locator(".today-group-title").evaluate_all(
            "els => els.map(e => e.firstChild.textContent.trim())"
        )
        assert titles[0] == "Home renovation" and "Family admin" in titles and "No project" in titles
        # first group holds only overdue rows
        expect(groups.first.locator(".trow.is-overdue")).to_have_count(2)
        fam = groups.filter(has=page.locator(".today-group-link", has_text="Family admin"))
        fam_titles = fam.locator(".trow-title").evaluate_all("els => els.map(e => e.textContent)")
        # both due today — the tie breaks on priority, not on the recurring
        # "Dentist check-up" being recurring (#116: a task's schedule always
        # decides its position, so a date/priority change actually reorders it)
        assert fam_titles == ["School enrolment forms", "Dentist check-up"]
        expect(fam.locator(".trow").last.locator(".trow-recur")).to_be_visible()
        # the ONE row here too (#46): the status select on every row; the
        # project is NOT repeated on the meta line — the group already names it
        school = _today_row(page, "School enrolment forms")
        expect(school).to_be_visible()
        expect(school.locator(".trow-status")).to_have_value("todo")
        expect(school.locator(".trow-person")).to_contain_text("Jordan Lee")
        expect(page.locator("#paneToday .trow-project")).to_have_count(0)
        later = page.locator(".today-later")
        assert later.evaluate("el => el.open") is False              # collapsed by default
        expect(later.locator(".collapse-count")).to_have_text(f"{today['counts']['week']} tasks")
        page.screenshot(path=str(shots / "story-05-board-5-desktop.png"))

        # 7. Mark a recurring task complete (the row's status select gains a
        #    `complete` option for a recurring task, issue #54) → its due
        #    rolls a cadence forward, it leaves the due list and shows up
        #    under "Later this week" with the new date.
        vocab = _today_row(page, "Vocabulary review")
        vid = int(vocab.get_attribute("data-id"))
        assert _get(base, f"/api/tasks/{vid}")["recurrence"] == "weekly"
        expect(vocab.locator(".trow-status option[value='complete']")).to_have_count(1)
        vocab.locator(".trow-status").select_option("complete")
        next_due = (date.today() + timedelta(days=7)).isoformat()
        expect(page.locator(f"#paneToday section.today .trow[data-id='{vid}']")).to_have_count(0)
        rolled = _get(base, f"/api/tasks/{vid}")
        assert rolled["due"] == next_due and rolled["status"] == "todo"
        assert rolled["activity"][0]["field"] == "due"
        later.locator("summary.collapse-summary").click()
        rolled_row = later.locator(f".trow[data-id='{vid}']")
        expect(rolled_row).to_be_visible()
        expect(rolled_row.locator(".trow-status")).to_have_value("todo")
        expect(rolled_row.locator(".trow-due")).to_have_attribute("title", next_due)
        expect(due_counts).to_contain_text(f"{today['counts']['today'] - 1} due today")
        page.screenshot(path=str(shots / "story-05-board-6-desktop.png"))

        # 7b. The same recurring task, picked "done" instead of "complete":
        #     closes for good — no further roll, off the recurring series
        #     from here (issue #54's other half).
        rolled_row.locator(".trow-status").select_option("done")
        expect(later.locator(f".trow[data-id='{vid}']")).to_have_count(0)
        closed = _get(base, f"/api/tasks/{vid}")
        assert closed["status"] == "done" and closed["due"] == next_due
        assert closed["done_at"] is not None

        # 8. Mark a plain overdue task done → done today: it leaves the Today
        #    list (open tasks only) and the Board's Done today column gains
        #    it, alongside 6b's now-closed recurring task (both done today).
        books = _today_row(page, "Return library books")
        bid = int(books.get_attribute("data-id"))
        books.locator(".trow-status").select_option("done")
        expect(page.locator(f"#paneToday section.today .trow[data-id='{bid}']")).to_have_count(0)
        done = _get(base, f"/api/tasks/{bid}")
        assert done["status"] == "done" and done["done_at"][:10] == date.today().isoformat()
        page.click("nav.tabs .tab[data-tab='board']")
        expect(_col(page, "done").locator(f".trow[data-id='{bid}']")).to_be_visible()
        expect(page.locator(".board-col-count[data-col='done']")).to_have_text("2")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-7-desktop.png"))

        # ---------------------------------------------- § #81 bulk select
        # 9. Select mode: tick three cards across three columns, bulk-change
        #    their status, and prove the selection is ONE store — it survives
        #    the trip to the Table, where the same three rows are ticked.
        page.click("#paneBoard [data-select-toggle]")
        expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "true")
        picks = ["Compare phone plans", "Choose worktop material", "Get three quotes"]
        for title in picks:
            _card(page, title).locator(".trow-check").check()
        ids = [int(_card(page, t).get_attribute("data-id")) for t in picks]
        assert len({_get(base, f"/api/tasks/{i}")["status"] for i in ids}) == 3   # three columns
        bar = page.locator("#boardBulk")
        expect(bar).to_be_visible()
        # the label carries the whole phrase — the visible text may drop the
        # word "selected" on a narrow phone, never the number
        expect(bar.locator(".bulk-count")).to_have_attribute("aria-label", "3 selected")
        expect(bar.locator(".bulk-n")).to_have_text("3")
        # the bar takes the strip over rather than stacking a third row on it
        expect(page.locator("#paneBoard [data-quick-add]")).to_be_hidden()
        # one line, one height — asserted on the desktop leg too, because the
        # mismatch that shipped here was fine-pointer only: the squares took
        # .icon-btn's 34px against the select's 36px
        boxes = bar.locator("select, button").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect()).map(r => ({y: r.y, h: r.height, w: r.width}))")
        assert len(boxes) == 4, boxes                        # status select · date · delete · ✕
        assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2, boxes
        assert len({round(b["h"]) for b in boxes}) == 1, boxes
        assert all(round(s["w"]) == round(s["h"]) for s in boxes[1:]), boxes
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-10-desktop.png"))

        # 10. The selection carries to the Table, checkbox column and all.
        page.click("nav.tabs .tab[data-tab='table']")
        expect(page.locator("#tableHost th.c-sel")).to_be_visible()
        expect(page.locator("#tableBulk .bulk-count")).to_have_attribute("aria-label", "3 selected")
        for i in ids:
            expect(page.locator(f"#tableHost .task-row[data-id='{i}'] .row-check")).to_be_checked()
        page.screenshot(path=str(shots / "story-05-board-11-desktop.png"))

        # 11. Bulk-change the status → all three move, each with its own
        #     activity row, exactly as three single-task edits would have.
        page.locator("#tableBulk .bulk-status").select_option("standby")
        expect(page.locator("#tableBulk")).to_be_hidden()          # applied, selection cleared
        for i in ids:
            detail = _get(base, f"/api/tasks/{i}")
            assert detail["status"] == "standby", detail
            log = next(a for a in detail["activity"] if a["field"] == "status")
            assert log["new_value"] == "standby", log
        # Select mode is still on — the next pick needs no second trip to the toggle
        expect(page.locator("#paneTable [data-select-toggle]")).to_have_attribute("aria-pressed", "true")

        # 12. A bulk due date. The bar carries the native picker alone (no
        #     phrase box — that lives on the Table's own cell), and the picker
        #     dialog is OS chrome Playwright cannot open, so the walk sets the
        #     date input and fires the change the picker itself would.
        page.locator(f"#tableHost .task-row[data-id='{ids[0]}'] .row-check").check()
        page.locator(f"#tableHost .task-row[data-id='{ids[1]}'] .row-check").check()
        expect(page.locator("#tableBulk .bulk-due")).to_be_visible()
        expect(page.locator("#tableBulk .due-text")).to_have_count(0)
        target = (date.today() + timedelta(days=14)).isoformat()
        page.locator("#tableBulk input.due-date").evaluate(
            "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }", target)
        expect(page.locator("#tableBulk")).to_be_hidden()
        assert [_get(base, f"/api/tasks/{i}")["due"] for i in ids[:2]] == [target, target]

        # 13. A batch that partially fails names the id rather than dropping
        #     it silently — the task deleted in another tab (#81).
        page.locator(f"#tableHost .task-row[data-id='{ids[0]}'] .row-check").check()
        page.locator(f"#tableHost .task-row[data-id='{ids[1]}'] .row-check").check()
        page.evaluate(f"fetch('/api/tasks/{ids[1]}', {{method: 'DELETE'}})")
        page.locator("#tableBulk .bulk-status").select_option("todo")
        expect(page.locator(".toasts")).to_have_text(re.compile(rf"1 updated .* 1 failed .*#{ids[1]}"))
        assert _get(base, f"/api/tasks/{ids[0]}")["status"] == "todo"
        page.screenshot(path=str(shots / "story-05-board-12-desktop.png"))

        # 14. Leaving Select mode puts the pane back exactly as it was.
        page.click("#paneTable [data-select-toggle]")
        expect(page.locator("#tableHost th.c-sel")).to_have_count(0)
        expect(page.locator("#paneTable [data-quick-add]")).to_be_visible()

        _walk_keyboard_actions(page, base, shots)
        _walk_done_journal(page, base, shots)
        _walk_delete_task(page, base, shots)
        assert errors == [], errors
    finally:
        context.close()


def _clear_toasts(page: Page) -> None:
    """Toasts stack and outlive a step, so each assertion below reads only its
    own: drop what is on screen before pressing the next key."""
    page.evaluate("document.getElementById('toasts').replaceChildren()")


def _walk_keyboard_actions(page: Page, base: str, shots: Path) -> None:
    """§ #99 — a keyboard-only triage, with undo, on the Board.

    Story 16 in ``docs/validation.md`` points here. The keys act on the row
    that has focus (or on the ticked set), so the walk focuses rows the way a
    user's Tab does and then only presses keys.
    """
    page.click("nav.tabs .tab[data-tab='board']")

    # 15. `p` cycles the focused row's priority, and the toast offers the undo
    #     the `z` key runs. The reversal is a real write: the activity log
    #     carries both directions, which a client-side rollback could not.
    readme = _card(page, "Write README")
    rid = int(readme.get_attribute("data-id"))
    assert _get(base, f"/api/tasks/{rid}")["priority"] == "low"
    readme.locator(".trow-main").focus()
    _clear_toasts(page)
    page.keyboard.press("p")
    expect(page.locator(".toasts")).to_have_text(re.compile("Priority medium"))
    expect(page.locator(".toast-action").first).to_have_text("Undo (Z)")
    assert _get(base, f"/api/tasks/{rid}")["priority"] == "medium"
    page.screenshot(path=str(shots / "story-16-keyboard-triage-1-desktop.png"))
    _clear_toasts(page)
    page.keyboard.press("z")
    expect(page.locator(".toasts")).to_have_text(re.compile("Undone"))
    detail = _get(base, f"/api/tasks/{rid}")
    assert detail["priority"] == "low"
    prio = [a for a in detail["activity"] if a["field"] == "priority"]
    assert [(a["old_value"], a["new_value"]) for a in prio[:2]] == [
        ("medium", "low"), ("low", "medium"),
    ], prio

    # 16. Focus follows the work: after the write the same row still has it,
    #     so the next key lands where the eye is. `t` sets the due date.
    expect(page.locator(f"#paneBoard .trow[data-id='{rid}'] .trow-main")).to_be_focused()
    _clear_toasts(page)
    page.keyboard.press("t")
    expect(page.locator(".toasts")).to_have_text(re.compile("Due tomorrow"))
    assert _get(base, f"/api/tasks/{rid}")["due"] == (date.today() + timedelta(days=1)).isoformat()

    # 17. `e` completes — and on a recurring task that means the roll, whose
    #     undo has to put the *pre-roll* due back (issue #54 semantics).
    weekly = _card(page, "Weekly review")
    wid = int(weekly.get_attribute("data-id"))
    before = _get(base, f"/api/tasks/{wid}")
    weekly.locator(".trow-main").focus()
    _clear_toasts(page)
    page.keyboard.press("e")
    expect(page.locator(".toasts")).to_have_text(re.compile("Completed"))
    rolled = _get(base, f"/api/tasks/{wid}")
    assert rolled["due"] > before["due"] and rolled["status"] == before["status"]
    _clear_toasts(page)
    page.keyboard.press("z")
    expect(page.locator(".toasts")).to_have_text(re.compile("Undone"))
    assert _get(base, f"/api/tasks/{wid}")["due"] == before["due"]

    # 18. The keys are inert wherever text is being typed — the Board's filter
    #     box swallows every one of them as characters.
    page.fill("#boardFilterText input", "")
    page.click("#boardFilterText input")
    page.keyboard.type("etw")
    expect(page.locator("#boardFilterText input")).to_have_value("etw")
    assert _get(base, f"/api/tasks/{rid}")["status"] == "todo"
    page.fill("#boardFilterText input", "")

    # 19. …and while the drawer is open, which owns the keyboard.
    _card(page, "Write README").locator(".trow-main").click()
    expect(page.locator("#taskDrawer")).to_be_visible()
    page.keyboard.press("1")
    page.keyboard.press("Escape")
    expect(page.locator("#taskDrawer")).to_be_hidden()
    assert _get(base, f"/api/tasks/{rid}")["status"] == "todo"

    # 20. With tasks ticked the same key acts on the set — and the undo puts
    #     each task's OWN prior status back, not one shared value.
    page.click("#paneBoard [data-select-toggle]")
    picks = ["Write README", "Fix watering schedule drift"]        # todo · doing
    for title in picks:
        _card(page, title).locator(".trow-check").check()
    ids = [int(_card(page, t).get_attribute("data-id")) for t in picks]
    assert [_get(base, f"/api/tasks/{i}")["status"] for i in ids] == ["todo", "doing"]
    page.evaluate(f"document.querySelector('.trow[data-id=\"{ids[0]}\"] .trow-main').focus()")
    _clear_toasts(page)
    page.keyboard.press("1")
    expect(page.locator(".toasts")).to_have_text(re.compile("2 tasks"))
    assert [_get(base, f"/api/tasks/{i}")["status"] for i in ids] == ["inbox", "inbox"]
    page.screenshot(path=str(shots / "story-16-keyboard-triage-2-desktop.png"))
    _clear_toasts(page)
    page.keyboard.press("z")
    expect(page.locator(".toasts")).to_have_text(re.compile("Undone"))
    assert [_get(base, f"/api/tasks/{i}")["status"] for i in ids] == ["todo", "doing"]
    # the ticks survive a keyed action (several keys, one set), so Escape is
    # what leaves Select mode — the toggle is hidden while the bar is up
    expect(page.locator(f"#paneBoard .trow[data-id='{ids[0]}']")).to_have_class(re.compile("is-selected"))
    page.keyboard.press("Escape")
    expect(page.locator("#boardBulk")).to_be_hidden()

    # 21. The Table's desktop grid is a different element (a <tr>, not the
    #     shared .trow) — the keys reach it too.
    page.click("nav.tabs .tab[data-tab='table']")
    trow = page.locator(f"#tableHost .task-row[data-id='{rid}']")
    trow.focus()
    _clear_toasts(page)
    page.keyboard.press("4")
    expect(page.locator(".toasts")).to_have_text(re.compile("Status standby"))
    assert _get(base, f"/api/tasks/{rid}")["status"] == "standby"
    _clear_toasts(page)
    page.keyboard.press("z")
    expect(page.locator(".toasts")).to_have_text(re.compile("Undone"))
    assert _get(base, f"/api/tasks/{rid}")["status"] == "todo"

    # 22. …and a Search hit, which may be a task outside the filtered list —
    #     the prior values then come from a fetch, not from what is on screen.
    page.click("nav.tabs .tab[data-tab='search']")
    page.fill("#searchInput", "README")
    tasks_group = page.locator(".search-group[data-kind='tasks']")
    expect(tasks_group).to_be_visible()
    if not tasks_group.evaluate("el => el.open"):
        tasks_group.locator("summary.collapse-summary").click()
    hit = tasks_group.locator(f".trow[data-id='{rid}']").first
    expect(hit).to_be_visible()
    hit.locator(".trow-main").focus()
    _clear_toasts(page)
    page.keyboard.press("p")
    expect(page.locator(".toasts")).to_have_text(re.compile("Priority medium"))
    _clear_toasts(page)
    page.keyboard.press("z")
    expect(page.locator(".toasts")).to_have_text(re.compile("Undone"))
    assert _get(base, f"/api/tasks/{rid}")["priority"] == "low"
    page.click("nav.tabs .tab[data-tab='board']")

    # 23. `?` is the reference card, built from the one keymap table — and the
    #     palette lists the same keys, which is where they are discovered.
    page.keyboard.press("?")
    expect(page.locator("#keysHelp")).to_be_visible()
    # 9 actions + Z + ?, then the five "getting around" keys
    expect(page.locator("#keysHelp .keys-rows").first.locator(".keys-row")).to_have_count(11)
    expect(page.locator("#keysHelp .keys-rows").first).to_contain_text("Complete task")
    expect(page.locator("#keysHelp")).to_contain_text("Getting around")
    page.screenshot(path=str(shots / "story-16-keyboard-triage-3-desktop.png"))
    page.keyboard.press("Escape")
    expect(page.locator("#keysHelp")).to_be_hidden()

    # the same sheet in the dark theme (the modal's backdrop swallows a click
    # on the header toggle, so the theme flips between openings)
    page.click("#themeToggle")
    page.keyboard.press("?")
    expect(page.locator("#keysHelp")).to_be_visible()
    page.screenshot(path=str(shots / "story-16-keyboard-triage-4-desktop.png"))
    page.keyboard.press("Escape")
    page.click("#themeToggle")

    page.click("#paletteBtn")
    page.fill("#paletteInput", ">priority")
    expect(page.locator(".palette-item").first).to_contain_text("Cycle priority")
    expect(page.locator(".palette-item").first.locator("kbd")).to_have_text("P")
    page.screenshot(path=str(shots / "story-16-keyboard-triage-5-desktop.png"))
    page.keyboard.press("Escape")
    expect(page.locator("#palette")).to_be_hidden()


def _journal_day(page: Page, day: str):
    return page.locator(f".journal-day[data-day='{day}']")


def _walk_done_journal(page: Page, base: str, shots: Path) -> None:
    """§ #102 — the done journal, from the Board's Done column.

    Runs after the keyboard walk, so today already holds what the story
    closed; the seed adds yesterday (two done), two days back (one done, one
    cancelled) and nine days back (the week before). One task is completed
    through the API mid-walk — the coding task with the issue chip — and
    restored at the end, so the phone leg's Today reads as seeded.
    """
    today = date.today()
    iso = lambda days_ago: (today - timedelta(days=days_ago)).isoformat()  # noqa: E731
    watering = _get(base, "/api/tasks?q=watering%20schedule")["items"][0]
    assert watering["status"] == "doing", watering["status"]     # the keyboard walk put it back

    # 1. The Done column's head links to the journal: no tab lit, #journal in the URL.
    _clear_toasts(page)
    page.click("nav.tabs .tab[data-tab='board']")
    page.click(".board-col[data-col='done'] .board-col-link")
    expect(page.locator("#paneJournal")).to_be_visible()
    expect(page.locator("#paneBoard")).to_be_hidden()
    expect(page.locator("nav.tabs .tab.active")).to_have_count(0)
    assert page.evaluate("location.hash") == "#journal"

    # 2. Days newest first with counts; the seed's closings where they belong.
    days = page.locator(".journal-day")
    expect(days.first).to_have_attribute("data-day", iso(0))
    listed = days.evaluate_all("els => els.map(e => e.dataset.day)")
    assert listed == sorted(listed, reverse=True) and listed[:3] == [iso(0), iso(1), iso(2)], listed
    assert iso(9) not in listed                                   # the week before is a load away
    expect(_journal_day(page, iso(1)).locator(".today-group-title")).to_contain_text("Yesterday")
    expect(_journal_day(page, iso(1)).locator(".today-group-count")).to_have_text("2 done")
    kettle = _trow(page, f".journal-day[data-day='{iso(1)}']", "Descale the kettle")
    expect(kettle.locator(".trow-project")).to_have_text("Home renovation")
    expect(kettle.locator(".trow-status")).to_have_value("done")
    expect(_journal_day(page, iso(2)).locator(".today-group-count")).to_have_text("1 done · 1 cancelled")
    muted = _trow(page, f".journal-day[data-day='{iso(2)}']", "Cancel the unused streaming plan")
    assert float(muted.evaluate("el => getComputedStyle(el).opacity")) < 1
    # the page is exactly the API's window (this week, both closed statuses)
    api = _get(base, f"/api/tasks?status=done,cancelled&done_from={iso(6)}&done_to={iso(0)}")
    assert page.locator("#journalHost .trow").count() == api["count"]

    # 3. A coding task closed now lands on today with its issue chip; #journal
    #    deep-links straight back here after a reload.
    page.evaluate(f"fetch('/api/tasks/{watering['id']}', {{method: 'PATCH', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{status: 'done'}})}})")
    page.wait_for_function(f"() => fetch('/api/tasks/{watering['id']}').then(r => r.json()).then(t => t.status === 'done')")
    page.reload()
    expect(page.locator("#paneJournal")).to_be_visible()
    expect(page.locator("nav.tabs .tab.active")).to_have_count(0)
    drift = _trow(page, f".journal-day[data-day='{iso(0)}']", "Fix watering schedule drift")
    expect(drift.locator(".trow-meta a.chip-issue")).to_have_attribute("href", re.compile("garden-bot/issues/12"))
    expect(drift.locator(".trow-project")).to_have_text("Side project: garden-bot")
    page.screenshot(path=str(shots / "story-18-done-journal-1-desktop.png"))

    # 4. The cancelled switch drops the muted rows (and the count follows).
    page.click(".journal-toggle .toggle")
    expect(page.locator("#journalHost .trow[data-status='cancelled']")).to_have_count(0)
    expect(_journal_day(page, iso(2)).locator(".today-group-count")).to_have_text("1 done")
    page.click(".journal-toggle .toggle")
    expect(page.locator("#journalHost .trow[data-status='cancelled']")).to_have_count(1)

    # 5. The shared filters apply and ride the URL; the controls that say
    #    nothing about a closed task are not there.
    family = _get(base, "/api/tasks?q=family%20admin")["items"][0]
    _open_filters(page, "journalFilters")
    expect(page.locator("#journalFilters select[name='due'], #journalFilters select[name='updated'],"
                        " #journalFilters select[name='sort'], #journalFilters .msel[data-name='status']")).to_have_count(0)
    page.select_option("#journalFilters select[name='project']", str(family["id"]))
    expect(page.locator("#journalHost .trow-project").first).to_have_text("Family admin")
    projects = page.locator("#journalHost .trow-project").all_inner_texts()
    assert projects and set(projects) == {"Family admin"}, projects
    assert f"project={family['id']}" in page.url and page.url.endswith("#journal"), page.url
    expect(page.locator("#journalFilters .filter-desc")).to_contain_text("Family admin")
    page.click("#journalFilters .filter-clear")
    expect(page.locator("#journalHost .trow-project").first).not_to_have_text("Family admin")

    # 6. Older weeks load on demand, down to the seed's first closing day —
    #    and only then does the journal say it has reached the end.
    page.click(".journal-older")
    expect(_journal_day(page, iso(9))).to_be_visible()
    expect(_trow(page, f".journal-day[data-day='{iso(9)}']", "Return the borrowed drill")).to_be_visible()
    for _ in range(8):
        if page.locator(".journal-end").count():
            break
        page.click(".journal-older")
        page.locator(".journal-older:enabled, .journal-end").first.wait_for()
    expect(page.locator(".journal-end")).to_be_visible()
    expect(_trow(page, "#journalHost", "Buy a birthday gift")).to_be_visible()   # the seed's oldest closings
    page.click("#themeToggle")
    page.screenshot(path=str(shots / "story-18-done-journal-2-desktop.png"))
    page.click("#themeToggle")

    # 7. A row opens the drawer under #journal/task/<id>; closing it keeps the journal.
    kettle = _trow(page, f".journal-day[data-day='{iso(1)}']", "Descale the kettle")
    kettle.locator(".trow-main").click()
    expect(page.locator("#taskDrawer")).to_be_visible()
    assert page.evaluate("location.hash").startswith("#journal/task/"), page.url
    page.keyboard.press("Escape")
    expect(page.locator("#taskDrawer")).to_be_hidden()
    assert page.evaluate("location.hash") == "#journal"
    expect(page.locator("#paneJournal")).to_be_visible()

    # 8. A tab press leaves; the palette lists Journal and brings it back.
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator("#paneJournal")).to_be_hidden()
    expect(page.locator("#paneBoard")).to_be_visible()
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
    assert page.evaluate("location.hash") == ""
    page.click("#paletteBtn")
    page.fill("#paletteInput", ">journal")
    expect(page.locator(".palette-item").first).to_contain_text("Journal")
    page.keyboard.press("Enter")
    expect(page.locator("#paneJournal")).to_be_visible()
    assert page.evaluate("location.hash") == "#journal"
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator("#paneJournal")).to_be_hidden()

    # leave the coding task as the seed had it (the phone leg reads Today)
    page.evaluate(f"fetch('/api/tasks/{watering['id']}', {{method: 'PATCH', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{status: 'doing'}})}})")
    page.wait_for_function(f"() => fetch('/api/tasks/{watering['id']}').then(r => r.json()).then(t => t.status === 'doing')")


# ------------------------------------------------------------- phone leg

def _status(page: Page, base: str, path: str) -> int:
    """The HTTP status of a GET — for the 404 a deleted task must answer with
    (`_get` raises on 4xx, which is the wrong shape for that assertion)."""
    return page.evaluate("p => fetch(p).then(r => r.status)", path)


def _walk_delete_task(page: Page, base: str, shots: Path) -> None:
    """§ #121 — delete a task from the drawer, then a batch from the Select bar.

    The walk makes its own tasks over the API (a small project with two
    children, two loose mistakes) so nothing the seed proves elsewhere is
    touched; a reload on the deep link brings the Board up to date.
    """
    mk = lambda body: page.evaluate(  # noqa: E731
        "b => fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
        "body: JSON.stringify(b)}).then(r => r.json())", body)
    fence = mk({"title": "Repaint the garden fence", "status": "todo"})["id"]
    kid = mk({"title": "Buy the primer", "parent_id": fence})["id"]
    mk({"title": "Sand the posts", "parent_id": fence})
    dupe = mk({"title": "Repaint the fence (duplicate)"})["id"]
    test = mk({"title": "test task, ignore"})["id"]

    # 1. The drawer's foot carries Delete; the dialog names the task and its subtree.
    _clear_toasts(page)
    page.goto(f"{base}/#task/{fence}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Repaint the garden fence")
    drawer.locator(".drawer-delete").click()
    dialog = page.locator("#confirmDialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#confirmTitle")).to_have_text('Delete "Repaint the garden fence"?')
    expect(dialog.locator(".confirm-body")).to_contain_text("Its 2 child tasks go with it.")
    expect(dialog.locator(".confirm-body")).to_contain_text("cannot be undone")
    expect(dialog.locator(".confirm-warn")).to_have_count(0)     # not a synced coding task
    page.screenshot(path=str(shots / "story-19-delete-task-1-desktop.png"))

    # 2. Escape is "no": the drawer stays, the task is still there.
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(drawer).to_be_visible()
    assert _status(page, base, f"/api/tasks/{fence}") == 200

    # 3. Confirm: the subtree is gone, the drawer closes, the hash clears, a toast says how much.
    drawer.locator(".drawer-delete").click()
    expect(dialog).to_be_visible()
    dialog.locator(".confirm-danger").click()
    expect(dialog).to_be_hidden()
    expect(drawer).to_be_hidden()
    assert page.evaluate("location.hash") == ""
    expect(page.locator(".toasts")).to_contain_text('Deleted "Repaint the garden fence" · 3 tasks')
    assert _status(page, base, f"/api/tasks/{fence}") == 404
    assert _status(page, base, f"/api/tasks/{kid}") == 404
    expect(page.locator(f"#boardHost .trow[data-id='{fence}']")).to_have_count(0)

    # 4. A batch of mistakes from the Table's Select bar: one dialog with the count.
    _clear_toasts(page)
    page.click("nav.tabs .tab[data-tab='table']")
    expect(page.locator(f"#tableHost .task-row[data-id='{dupe}']")).to_be_visible()
    page.click("#paneTable [data-select-toggle]")
    page.locator(f"#tableHost .task-row[data-id='{dupe}'] .row-check").check()
    page.locator(f"#tableHost .task-row[data-id='{test}'] .row-check").check()
    page.locator("#tableBulk .bulk-delete").click()
    expect(dialog).to_be_visible()
    expect(dialog.locator("#confirmTitle")).to_have_text("Delete 2 tasks?")
    page.screenshot(path=str(shots / "story-19-delete-task-2-desktop.png"))
    dialog.locator(".confirm-danger").click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".toasts")).to_contain_text("2 tasks deleted")
    expect(page.locator(f"#tableHost .task-row[data-id='{dupe}']")).to_have_count(0)
    expect(page.locator(f"#tableHost .task-row[data-id='{test}']")).to_have_count(0)
    assert _status(page, base, f"/api/tasks/{dupe}") == 404
    # a clean batch clears the selection but stays in Select mode; leave it as found
    expect(page.locator("#tableBulk")).to_be_hidden()
    page.click("#paneTable [data-select-toggle]")
    expect(page.locator("#paneTable [data-select-toggle]")).to_have_attribute("aria-pressed", "false")


def test_phone_today_landing_and_board_carousel(seeded_webapp: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): Today is the landing tab, the Board a
    one-column scroll-snap carousel with the count strip, 44px targets (the
    row's status select is the deliberate compact exception)."""
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
        # 9. Fresh phone → Today (coarse pointer, nothing persisted yet).
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        rows = page.locator("#paneToday section.today .trow")
        expect(rows.first).to_be_visible()
        # the ONE row on the phone: ≥44px tall, the status select compact
        # (≤32px) and never overlapping its neighbours
        assert_min_target(rows)
        selects = rows.locator(".trow-status")
        assert_no_overlap(selects)
        heights = selects.evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and all(h <= 32 for h in heights), heights
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-8-phone.png"))

        # 10. Board: strip of five counts + one column per screen (scroll-snap).
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
        # launcher-density rows (UX round 2, issue #32): every seeded row in
        # the active column stays inside the ≤96px budget
        heights = _col(page, "doing").locator(".trow").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and all(h <= 96 for h in heights), heights
        # touch fallback for the drag: the row's compact status select —
        # right-aligned, ≤32px tall, auto width, its centre on the card's own
        # centre (title + meta) since #74 (UX rounds 1–3, issues #27/#32/#46)
        first_item = _col(page, "doing").locator(".trow").first
        row_select = first_item.locator(".trow-status")
        expect(row_select).to_be_visible()
        sel_box = row_select.bounding_box()
        main_box = first_item.locator(".trow-main").bounding_box()
        item_box = first_item.bounding_box()
        assert sel_box and main_box and item_box
        assert sel_box["height"] <= 32, sel_box                      # compact, never a 44px row of its own
        assert sel_box["width"] < item_box["width"] / 2, (sel_box, item_box)   # auto width, not full-width
        assert sel_box["x"] + sel_box["width"] >= item_box["x"] + item_box["width"] - 16, (sel_box, item_box)
        meta_box = first_item.locator(".trow-meta").bounding_box()
        assert meta_box
        sel_center = sel_box["y"] + sel_box["height"] / 2
        rows_center = (main_box["y"] + meta_box["y"] + meta_box["height"]) / 2
        assert abs(sel_center - rows_center) <= 2, (sel_box, main_box, meta_box)
        # flat list, not a card: no rounded box on the column's list
        assert _col(page, "doing").locator(".board-list").evaluate("el => getComputedStyle(el).borderRadius") == "0px"
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-9-phone.png"))

        # Landing straight on the Board (the tab is remembered now): the nav
        # positions the carousel before the first list has loaded, so an
        # unguarded placement clamps to column one while the strip still reads
        # "Todo". The strip and the column in view must name the same thing.
        page.reload()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        expect(page.locator("#paneBoard .board-strip-btn.active")).to_have_attribute("data-col", "todo")
        page.wait_for_function(
            "() => { const a = document.querySelector('.board-strip-btn.active');"
            "        const w = document.querySelector('.board-columns');"
            "        if (!a || !w) return false;"
            "        const c = document.querySelector(\".board-col[data-col='\" + a.dataset.col + \"']\");"
            "        return c && Math.abs(c.getBoundingClientRect().left - w.getBoundingClientRect().left) < 2; }"
        )
        # and the column on screen really is the one the strip names
        in_view = [k for k in COLUMNS if 0 <= _col(page, k).bounding_box()["x"] < PHONE["width"] - 1]
        assert in_view == ["todo"], in_view

        # 11. § #81 on the phone: the same Select toggle, tap-to-select (no
        #     gesture — the horizontal swipe still belongs to the carousel),
        #     and the bulk bar sized for the strip, clear of the nav pill.
        # the strip's two icon buttons are one pair: same square, both 44px on
        # touch (the toggle used to keep the 36px control height here)
        tog_box = page.locator("#paneBoard [data-select-toggle]").bounding_box()
        add_box = page.locator("#paneBoard [data-quick-add]").bounding_box()
        assert tog_box and add_box
        assert (tog_box["width"], tog_box["height"]) == (add_box["width"], add_box["height"]), (tog_box, add_box)
        assert tog_box["width"] == tog_box["height"] >= 44, tog_box
        assert_no_overlap(page.locator("#paneBoard .pane-top button"))

        page.locator("#paneBoard [data-select-toggle]").tap()
        checks = _col(page, "doing").locator(".trow-check")
        expect(checks.first).to_be_visible()
        assert_min_target(_col(page, "doing").locator(".trow"))
        assert_no_overlap(checks)
        # a tap on the card body ticks it instead of opening the drawer
        _col(page, "doing").locator(".trow").first.locator(".trow-main").tap()
        expect(_col(page, "doing").locator(".trow.is-selected")).to_have_count(1)
        expect(page.locator("#taskDrawer")).to_be_hidden()
        bar = page.locator("#boardBulk")
        expect(bar).to_be_visible()
        bar_box = bar.bounding_box()
        nav_box = page.locator("nav.tabs").bounding_box()
        assert bar_box and nav_box
        # the bar lives in the top strip — it never reaches the floating pill
        assert bar_box["y"] + bar_box["height"] < nav_box["y"], (bar_box, nav_box)
        assert_min_target(bar.locator("button"))
        assert_no_overlap(bar.locator("button"))
        # ONE line, and one height: every control shares the row's centre and
        # the two square buttons match the strip's own (they wrapped to a
        # second line, and the date was a phrase box, before the owner's call)
        boxes = bar.locator("select, button").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect()).map(r => ({y: r.y, h: r.height, w: r.width}))")
        assert len(boxes) == 4, boxes                       # status select · date · delete · ✕
        assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2, boxes
        assert len({round(b["h"]) for b in boxes}) == 1, boxes
        squares = boxes[1:]
        assert all(round(s["w"]) == round(s["h"]) >= 44 for s in squares), squares
        assert bar_box["height"] < 2 * boxes[0]["h"], bar_box   # never wrapped
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(shots / "story-05-board-10-phone.png"))

        # 12. § #102 on the phone: #journal deep-links the journal (no tab
        #     lit), the rows and the head fit the width, the pill stays.
        page.goto(f"{base}/#journal")
        expect(page.locator("#paneJournal")).to_be_visible()
        expect(page.locator("nav.tabs .tab.active")).to_have_count(0)
        expect(page.locator(".journal-day").first).to_be_visible()
        expect(page.locator("nav.tabs")).to_be_visible()
        assert_min_target(page.locator(".journal-toggle .toggle"))
        assert_no_horizontal_overflow(page)
        # no tab is lit — once the pill's 0.16 s fade is over, every button
        # wears the same (un-tinted) fill
        expect(page.locator("nav.tabs .tab.active")).to_have_count(0)
        page.wait_for_function(
            "() => new Set([...document.querySelectorAll('nav.tabs .tab')]"
            ".map(e => getComputedStyle(e).backgroundColor)).size === 1"
        )
        page.screenshot(path=str(shots / "story-18-done-journal-3-phone.png"))
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        expect(page.locator("#paneJournal")).to_be_hidden()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        context.close()
    finally:
        wk.close()
