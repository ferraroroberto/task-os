"""Story 05 — Board day (Step 5/13, issue #6).

    Board tab: the week planner (#396) — Today · Tomorrow · This week · This
    weekend · Next week · Later · No date side by side, the header naming the
    Inbox arrivals and what is overdue — and a drag between two lanes changes
    the due date and nothing else (Undo puts it back) → the Status segment:
    four columns visible at once on the laptop → the top strip's
    text filter narrows the board without opening any disclosure and the +
    opens the quick-add dialog (#80) → project chip
    filters to one project (shared with Today, encoded in the URL) → drag
    a row todo → standby → the counts update and the activity log has the
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
    docs/screenshots/story-05-board-14-desktop.png          (Week mode, #396)

then the phone at 390×844 (WebKit, touch) — Today as the landing tab, the
Board's Week mode as one list of lane sections and its Status mode as a
one-column scroll-snap carousel — with the geometry checks:

    docs/screenshots/story-05-board-8-phone.png   (Today, the landing tab)
    docs/screenshots/story-05-board-9-phone.png   (Board carousel, one column)
    docs/screenshots/story-05-board-14-phone.png  (Board Week mode, one list)
    docs/screenshots/story-05-board-10-phone.png  (§ #81 Select mode + bulk bar)

§ #81 (multi-select, folded into this story rather than a 15th e2e test, the
way #77 rides inside story 09): Select mode across Board and Today over ONE
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

§ #350 (``_walk_today_horizons``, same reason): with the Table gone no open
task may be out of reach, so Today lists them all in four horizons — Today,
Soon, Later, No date — and a task due a year out and a task with no date are
both reached from Today, by scrolling and by the text filter. Story 31 points
here. § #391 rides the same walk: the horizons under `overline` headers with
their counts, the Mine · Issues · All switch (Mine by default, the pick kept
in the URL across a reload) and project sub-headers only where two or more
groups need telling apart. § #393: Later and No date start folded with their
counts (one tap opens each, and a re-render keeps it open), a text filter
opens them, and the due rows carry no header of their own: the page header
names them, and the open count is the text field's placeholder.

    docs/screenshots/story-31-today-horizons-{1,2,3,4}-desktop.png

§ #321 (``_walk_edit_refresh``, same reason): an edit the server confirmed shows
on every visible row without a reload even when an earlier refresh is still in
flight — the title edited with the list reads held back, the due date edited
before they arrive, then both rows (Board, Today) are checked once the late
answers land. No screenshots: the proof is the rows.

UX round 3 (issue #46, the row slimmed by #311): every view renders the ONE
task row (``.trow`` — completion circle, title with its one-line passive meta,
the Move verb on a fine pointer outside the Board's columns (#392), ⋯ kebab)
and shares ONE filter state; "ticking" is the row's circle, on every
pointer, and every other action (status, date, snooze, priority, folder,
AI, issue) is a ⋯ menu item. Today's done tasks ride in the shared list only
for the Board's Done today column: Today keeps showing open tasks (as the
filter sheet says), so a task finished today leaves the Today
list and appears in the Board's Done today column.
"""

from __future__ import annotations

import json
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
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _get,
    assert_action_row_budget,
    assert_date_sheet,
    board_mode,
    close_filter_sheet,
    dismiss_toasts,
    filter_button,
    open_filter_sheet,
    scroll_to_bottom,
    settle,
    shot,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
COLUMNS = ["inbox", "todo", "standby", "done"]
# Week mode's lanes on the anchor, a Monday (#396): the days each holds.
LANES = ["today", "tomorrow", "week", "weekend", "next", "later", "nodate"]


def _trow(page: Page, scope: str, title: str):
    """The ONE shared task row (rows.js) by exact title inside ``scope``."""
    return page.locator(f"{scope} .trow", has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _card(page: Page, title: str):
    return _trow(page, "#paneBoard", title)


def _today_row(page: Page, title: str):
    # the due list only — Soon / Later / No date are the sibling disclosures
    return _trow(page, "#paneToday section.today", title)


def _col(page: Page, key: str):
    """A Status-mode column."""
    return page.locator(f"#paneBoard .board-status .board-col[data-col='{key}']")


def _lane(page: Page, key: str):
    """A Week-mode lane (#396)."""
    return page.locator(f"#paneBoard .board-week .board-col[data-col='{key}']")


def _counts(page: Page) -> dict[str, int]:
    return {k: int(_col(page, k).locator(".board-col-count").inner_text()) for k in COLUMNS}


def _mine(columns: dict) -> dict:
    """/api/board's columns in the Board's default Mine scope: no synced issue's task (#391)."""
    return {k: [t for t in col if not t.get("issue_ref")] for k, col in columns.items()}


def _lane_of(due: str | None) -> str:
    """The lane a due date falls in on the anchor Monday — the rule weekLanes()
    implements, stated here as dates so the two are checked against each other."""
    if not due:
        return "nodate"
    days = (date.fromisoformat(due) - E2E_ANCHOR).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 4:
        return "week"        # Wednesday … Friday
    if days <= 6:
        return "weekend"
    if days <= 13:
        return "next"
    return "later"


# ----------------------------------------------------------- desktop leg

def test_desktop_board_day(seeded_webapp: str, browser: Browser, playwright: Playwright, shots: Path) -> None:
    """The desktop walk, then the phone leg on the same instance.

    One collected test, not two: the phone leg was its own test function until
    Step 12's team story needed a slot under the e2e budget (CLAUDE.md), so it
    is folded in here — same steps, same order, same shots.
    """
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. Today is the landing tab on every pointer (#319); one tab press to the
        #    Board — the week planner (#396): the seven lanes of a Monday side
        #    by side, each holding exactly the open tasks due in its days.
        page.goto(f"{base}/")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        page.click("nav.tabs .tab[data-tab='board']")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        modes = page.locator("#paneBoard .board-modes .segmented-item")
        expect(modes).to_have_text(["Week", "Status"])
        expect(modes.first).to_have_attribute("aria-pressed", "true")       # Week is the default
        lanes = page.locator("#paneBoard .board-week .board-col:not([hidden])")
        assert lanes.evaluate_all("els => els.map(e => e.dataset.col)") == LANES
        expect(lanes.locator(".board-col-label")).to_have_text(
            ["Today", "Tomorrow", "This week", "This weekend", "Next week", "Later", "No date"])
        mine_open = [t for t in _get(base, "/api/tasks")["items"] if not t.get("issue_ref")]
        for k in LANES:
            want = sorted(t["id"] for t in mine_open if _lane_of(t["due"]) == k)
            got = _lane(page, k).locator(".trow").evaluate_all("els => els.map(e => Number(e.dataset.id))")
            assert sorted(got) == want, (k, got, want)
            expect(_lane(page, k).locator(".board-col-count")).to_have_text(str(len(want)))
        lane_boxes = [_lane(page, k).bounding_box() for k in LANES]
        for a, b in zip(lane_boxes, lane_boxes[1:], strict=False):
            assert abs(a["y"] - b["y"]) < 2 and a["x"] + a["width"] <= b["x"] + 1, (a, b)   # one row, left to right
        # The header names the exceptions from the lanes' own counts: the Inbox
        # arrivals in the accent, then what is overdue (#396).
        inbox_n = sum(1 for t in mine_open if t["status"] == "inbox")
        overdue_n = sum(1 for t in mine_open if t["due"] and t["due"] < E2E_ANCHOR.isoformat())
        head = page.locator("#homeHeadStatus")
        expect(head).to_have_text(f"{inbox_n} in Inbox · {overdue_n} overdue")
        expect(head.locator(".is-accent")).to_have_text(f"{inbox_n} in Inbox")
        expect(head.locator(".is-attention")).to_have_text(f"{overdue_n} overdue")
        # Triage works on the Inbox column: it is not on the week planner.
        expect(page.locator("#paneBoard .board-triage")).to_be_hidden()
        # A drag between two lanes changes the due date and nothing else: the
        # row lands on the lane's first day, through the date sheet's own Move.
        booking = _trow(page, "#paneBoard .board-week", "Book appointment")
        bkid = int(booking.get_attribute("data-id"))
        before = _get(base, f"/api/tasks/{bkid}")
        assert _lane_of(before["due"]) == "tomorrow", before["due"]
        booking.drag_to(_lane(page, "weekend"))
        landed = _lane(page, "weekend").locator(f".trow[data-id='{bkid}']")
        expect(landed).to_be_visible()
        saturday = (E2E_ANCHOR + timedelta(days=5)).isoformat()
        after = _get(base, f"/api/tasks/{bkid}")
        assert after["due"] == saturday, after["due"]
        changed = {k for k in before if k not in ("due", "updated_at", "activity") and before[k] != after[k]}
        assert not changed, changed                                   # only the due date moved
        act = after["activity"][0]
        assert (act["field"], act["old_value"], act["new_value"]) == ("due", before["due"], saturday), act
        expect(page.locator(".toasts")).to_contain_text("Due Sat 12 Sep")
        shot(page, shots / "story-05-board-14-desktop.png")
        page.locator(".toasts").get_by_role("button", name=re.compile("^Undo")).click()
        expect(_lane(page, "tomorrow").locator(f".trow[data-id='{bkid}']")).to_be_visible()
        assert _get(base, f"/api/tasks/{bkid}")["due"] == before["due"]
        dismiss_toasts(page)

        #    …then the Status segment: four columns side by side, full width, the
        #    empty one collapsed to its header (#396).
        board_mode(page, "status")
        cols = page.locator("#paneBoard .board-status .board-col")
        expect(cols).to_have_count(4)
        assert cols.evaluate_all("els => els.map(e => e.dataset.col)") == COLUMNS
        boxes = [cols.nth(i).bounding_box() for i in range(4)]
        assert all(b and b["width"] > 200 for b in boxes[:3]), boxes
        for a, b in zip(boxes, boxes[1:], strict=False):
            assert a["x"] + a["width"] <= b["x"] + 1, (a, b)   # left to right, no overlap
        assert abs(boxes[0]["y"] - boxes[3]["y"]) < 2                # one row
        assert boxes[3]["x"] + boxes[3]["width"] > DESKTOP["width"] - 40  # uses the full width
        api = _mine(_get(base, "/api/board")["columns"])
        counts = _counts(page)
        assert counts == {k: len(api[k]) for k in COLUMNS}, counts
        assert counts["done"] == 0                                    # seed's done tasks are old
        expect(_col(page, "done").locator(".board-col-label")).to_have_text("Done today")
        expect(_col(page, "done")).to_have_class(re.compile(r"\bis-empty\b"))   # collapsed: its header alone
        assert boxes[3]["width"] < boxes[0]["width"] / 2, boxes
        # Status mode with Inbox tasks: Triage sits on the mode line, not in a column head
        expect(page.locator("#paneBoard .board-bar .board-triage")).to_be_visible()
        expect(page.locator("#paneBoard .board-col .board-triage")).to_have_count(0)
        # a row = circle · title · kebab, with one passive meta line under the
        # title on #392's budget: due · exception chips · project · the child
        # and comment COUNTS — never the comment body (UX round 2, issue #32;
        # the ONE row of round 3, #46; #311). The folder, AI and issue links
        # and the person are not on it: the row menu opens each link.
        quotes = _card(page, "Get three quotes")
        expect(quotes).to_have_attribute("data-status", "todo")
        expect(quotes.locator(".trow-project")).to_have_text("Home renovation")
        expect(quotes.locator(".trow-person")).to_have_count(0)
        kitchen = _card(page, "Kitchen")
        expect(kitchen.locator(".trow-meta .trow-folder")).to_have_count(0)
        expect(kitchen.locator(".trow-meta a, .trow-meta button")).to_have_count(0)   # passive text, not links
        expect(kitchen.locator(".trow-prio")).to_have_text("High")                     # the one priority mark
        expect(kitchen.locator(".trow-prio")).to_have_attribute("data-tone", "neutral")
        expect(kitchen.locator(".trow-move")).to_have_count(0)    # a Board column has no room for the verb
        kitchen.locator(".trow-kebab").click()
        expect(page.locator(".row-menu [data-action='folder']")).to_be_visible()   # the action lives in the menu
        page.keyboard.press("Escape")
        expect(page.locator(".row-menu")).to_have_count(0)
        # a synced issue's task is behind the Issues scope (#391)
        expect(_card(page, "Fix watering schedule drift")).to_have_count(0)
        page.locator("#boardScope .segmented-item[data-scope='issues']").click()
        watering = _card(page, "Fix watering schedule drift")
        expect(watering.locator(".trow-meta .trow-issue")).to_have_count(0)
        _open_issue_from_menu(page, watering, "garden-bot/issues/12")
        expect(watering.locator(".trow-comments")).to_have_text("1")
        page.locator("#boardScope .segmented-item[data-scope='mine']").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.locator("#paneBoard .trow-comments").first).to_have_text(re.compile(r"^\d+$"))
        expect(page.locator("#paneBoard .t-comment")).to_have_count(0)   # the body bloated the cards
        expect(_card(page, "Repair fence").locator(".trow-due")).to_have_class(re.compile("due-overdue"))
        expect(_card(page, "Renew passports").locator(".trow-kids")).to_have_text("2")
        # flat regions, not cards: no rounded box on a column (issue #32)
        for k in COLUMNS:
            assert _col(page, k).evaluate("el => getComputedStyle(el).borderRadius") == "0px", k
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-1-desktop.png")

        # 2. The top strip (#80): the text filter is on screen without opening
        #    anything — typing filters the board live — and the + opens the one
        #    quick-add dialog, whose Escape discards the draft.
        q = page.locator("#boardFilterText .filter-q")
        expect(q).to_be_visible()
        sheet = page.locator("#filterSheet")
        expect(sheet).to_be_hidden()                             # the sheet is not up
        q.fill("passport")
        expect(page).to_have_url(f"{base}/?q=passport")
        expect(_card(page, "Renew passports")).to_be_visible()
        expect(_card(page, "Repair fence")).to_have_count(0)
        expect(sheet).to_be_hidden()                             # never had to open
        # the text is the field's own, never a count on the filter button (#395)
        expect(filter_button(page, "paneBoard").locator(".filter-count")).to_be_hidden()
        # a column the filter empties collapses to its header (#396)…
        empty_cols = [k for k, n in _counts(page).items() if n == 0]
        assert empty_cols, "the filter left no Board column empty to show"
        for k in empty_cols:
            expect(_col(page, k)).to_have_class(re.compile(r"\bis-empty\b"))
        # …and a filter that empties them all offers the way forward (#339):
        # one empty state, its action the quick-add dialog
        q.fill("no task is called this")
        empty = page.locator("#paneBoard .board-empty")
        expect(empty.locator(".empty-state-message")).to_have_text("Nothing on the board")
        empty.locator(".empty-state-action").click()
        expect(page.locator("#quickAdd")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#quickAdd")).to_be_hidden()
        q.fill("")
        expect(page).to_have_url(f"{base}/")
        page.locator("#paneBoard .quick-add-btn").click()
        quick_add = page.locator("#quickAdd")
        expect(quick_add).to_be_visible()
        quick_add.locator(".quick-add-input").fill("Order fence paint tomorrow")
        tomorrow = (E2E_ANCHOR + timedelta(days=1)).isoformat()
        expect(quick_add.locator(".quick-add-due")).to_have_value(tomorrow)
        page.keyboard.press("Escape")                            # discards the draft
        expect(quick_add).to_be_hidden()
        assert not any(t["title"].startswith("Order fence paint")
                       for col in _get(base, "/api/board")["columns"].values() for t in col)

        # 3. Project filter → only that project's descendants; the URL carries it;
        #    Today's sheet shows the same selection (one shared state).
        home = next(t for t in api["todo"] if t["title"] == "Home renovation")
        sheet = open_filter_sheet(page, "paneBoard")
        sheet.locator("select[name='project']").select_option(str(home["id"]))
        expect(page).to_have_url(f"{base}/?project={home['id']}")
        expect(sheet.locator(".filter-clear")).to_be_visible()
        close_filter_sheet(page)
        expect(filter_button(page, "paneBoard")).to_have_attribute("aria-label", "Filters, 1 on: Home renovation")
        filtered = _mine(_get(base, f"/api/board?project={home['id']}")["columns"])
        expect(_col(page, "todo").locator(".board-col-count")).to_have_text(str(len(filtered["todo"])))
        assert _counts(page) == {k: len(filtered[k]) for k in COLUMNS}
        shown = page.locator("#paneBoard .board-list .trow").evaluate_all("els => els.map(e => Number(e.dataset.id))")
        allowed = {t["id"] for col in filtered.values() for t in col}
        assert shown and set(shown) <= allowed
        shot(page, shots / "story-05-board-2-desktop.png")
        page.click("nav.tabs .tab[data-tab='today']")
        expect(filter_button(page, "paneToday")).to_have_attribute("aria-label", "Filters, 1 on: Home renovation")
        expect(open_filter_sheet(page, "paneToday").locator("select[name='project']")).to_have_value(str(home["id"]))
        close_filter_sheet(page)
        page.click("nav.tabs .tab[data-tab='board']")
        open_filter_sheet(page, "paneBoard").locator(".filter-clear").click()
        close_filter_sheet(page)
        expect(page).to_have_url(f"{base}/")
        expect(_col(page, "todo").locator(".board-col-count")).to_have_text(str(len(api["todo"])))

        # 4. Drag a row todo → standby: PATCH status, counts update, activity row.
        quotes = _card(page, "Get three quotes")
        qid = int(quotes.get_attribute("data-id"))
        assert quotes.evaluate("el => el.closest('.board-col').dataset.col") == "todo"
        # both ends in the viewport first (a page that scrolls under the
        # pointer mid-drag would pick up whichever row slides under it)
        _col(page, "standby").scroll_into_view_if_needed()
        quotes.drag_to(_col(page, "standby"))
        moved = _col(page, "standby").locator(f".trow[data-id='{qid}']")
        expect(moved).to_be_visible()
        expect(moved).to_have_attribute("data-status", "standby")
        expect(_col(page, "todo").locator(".board-col-count")).to_have_text(str(len(api["todo"]) - 1))
        expect(_col(page, "standby").locator(".board-col-count")).to_have_text(str(len(api["standby"]) + 1))
        detail = _get(base, f"/api/tasks/{qid}")
        assert detail["status"] == "standby"
        act = detail["activity"][0]
        assert (act["field"], act["old_value"], act["new_value"]) == ("status", "todo", "standby")
        log = _get(base, f"/api/activity?task={qid}&limit=1")["items"][0]
        assert log["field"] == "status" and log["new_value"] == "standby"
        shot(page, shots / "story-05-board-3-desktop.png")

        # 5. Row click → the drawer, activity log shows the move.
        moved.locator(".trow-main").click()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        expect(page).to_have_url(f"{base}/#task/{qid}")
        expect(drawer.locator("#drawerTitle")).to_have_value("Get three quotes")
        first_act = drawer.locator(".activity-row").first
        expect(first_act).to_have_attribute("data-field", "status")
        expect(first_act.locator(".activity-old")).to_have_text("todo")
        expect(first_act.locator(".activity-new")).to_have_text("standby")
        # side panel: the columns stay visible to its left
        drawer_box = drawer.bounding_box()
        first_col = _col(page, "inbox").bounding_box()
        assert drawer_box and first_col and first_col["x"] + first_col["width"] < drawer_box["x"]
        shot(page, shots / "story-05-board-4-desktop.png")
        drawer.locator(".drawer-close").click()
        expect(drawer).to_be_hidden()

        # 6. Today: due ≤ today grouped by root project, overdue first, sorted
        #    by due then priority within a group — recurring or not (#116).
        page.click("nav.tabs .tab[data-tab='today']")
        expect(page.locator("#paneToday")).to_be_visible()
        today = _get(base, "/api/today")
        # One header and one count (#393): the page header names the
        # exceptions in the attention tone, the due rows carry no header of
        # their own, and the open count is the text field's placeholder.
        head = page.locator("#homeHeadStatus")
        expect(head).to_have_text(
            f"{today['counts']['overdue']} overdue · {today['counts']['today']} due today"
        )
        expect(head).to_have_class(re.compile(r"\bis-attention\b"))
        expect(page.locator("#paneToday section.today .today-head")).to_have_count(0)
        expect(filter_button(page, "paneToday")).to_have_attribute("aria-label", "Filters")
        open_rows = page.locator("#paneToday .trow[data-id]").count()
        expect(page.locator("#todayFilterText .filter-q")).to_have_attribute(
            "placeholder", f"Filter {open_rows} tasks…")
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
        # the ONE row here too (#46): the circle and kebab on every row, no
        # snooze clock (#311); the project is NOT repeated on the meta line —
        # the group already names it
        school = _today_row(page, "School enrolment forms")
        expect(school).to_be_visible()
        expect(school).to_have_attribute("data-status", "todo")
        expect(school.locator(".trow-done")).to_have_attribute("aria-pressed", "false")
        expect(school.locator(".trow-kebab")).to_be_visible()
        expect(page.locator("#paneToday section.today .trow .snooze-summary")).to_have_count(0)
        expect(school.locator(".trow-person")).to_have_count(0)     # the drawer's field (#392)
        expect(page.locator("#paneToday .trow-project")).to_have_count(0)
        soon = page.locator(".today-soon")
        assert soon.evaluate("el => el.open") is True                 # open by default (#253)
        # Today opens on Mine (#391): the synced issues are behind the switch,
        # so Soon counts the week's tasks that are not issues
        mine_week = sum(1 for g in today["week"] for t in g["items"] if not t.get("issue_ref"))
        assert mine_week < today["counts"]["week"]                    # the seed has an issue due this week
        expect(soon.locator(".collapse-count")).to_have_text(str(mine_week))
        shot(page, shots / "story-05-board-5-desktop.png")

        # 6b. Move (#392): on a fine pointer every open row carries the one
        #     visible verb — a 44px icon button between the title and the
        #     kebab, unpainted at rest like the kebab (COMP-05), still inside
        #     the action-row budget — and re-dating is one tap plus one choice:
        #     Move → a push-out phrase. Undo puts the date back, so the walk
        #     below sees the seed's Today.
        today_rows = page.locator("#paneToday section.today .trow")
        assert_action_row_budget(today_rows)
        verb = school.locator(".trow-move")
        expect(verb).to_be_visible()
        assert verb.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        assert_min_target(verb)
        order = school.evaluate(
            "r => Array.from(r.children).map(c => Array.from(c.classList).find(k => k.startsWith('trow-')))")
        assert order.index("trow-main") < order.index("trow-move") < order.index("trow-kebab"), order
        sid = int(school.get_attribute("data-id"))
        verb.click()
        sheet = page.locator(".snooze-pop .snooze-menu[data-field='due']")
        expect(sheet).to_be_visible()
        assert_date_sheet(sheet, base)
        expect(school).to_have_class(re.compile(r"\bis-key-target\b"))     # the row it moves stays marked
        shot(page, shots / "story-05-board-13-desktop.png")
        tomorrow = (E2E_ANCHOR + timedelta(days=1)).isoformat()
        sheet.locator(".snooze-opt[data-phrase='tomorrow']").click()
        moved = page.locator(".toast-success").last
        expect(moved).to_contain_text("Due ")
        assert _get(base, f"/api/tasks/{sid}")["due"] == tomorrow
        expect(page.locator(f"#paneToday section.today .today-group .trow[data-id='{sid}']")).to_have_count(0)
        moved.locator(".toast-action").click()
        expect(_today_row(page, "School enrolment forms")).to_be_visible()
        assert _get(base, f"/api/tasks/{sid}")["due"] == E2E_ANCHOR.isoformat()
        dismiss_toasts(page)

        # 7. Mark a recurring task complete (the row's circle: on a recurring
        #    task it rolls instead of closing, issue #54) → its due rolls a
        #    cadence forward, it leaves the due list and shows up under
        #    Soon with the new date.
        vocab = _today_row(page, "Vocabulary review")
        vid = int(vocab.get_attribute("data-id"))
        assert _get(base, f"/api/tasks/{vid}")["recurrence"] == "weekly"
        expect(vocab.locator(".trow-done")).to_have_attribute("aria-pressed", "false")
        vocab.locator(".trow-done").click()
        expect(page.locator(".toasts")).to_contain_text("Completed")
        expect(page.locator(".toast-action").first).to_have_text("Undo (Z)")
        next_due = (E2E_ANCHOR + timedelta(days=7)).isoformat()
        expect(page.locator(f"#paneToday section.today .trow[data-id='{vid}']")).to_have_count(0)
        rolled = _get(base, f"/api/tasks/{vid}")
        assert rolled["due"] == next_due and rolled["status"] == "todo"
        assert rolled["activity"][0]["field"] == "due"
        rolled_row = soon.locator(f".trow[data-id='{vid}']")
        expect(rolled_row).to_be_visible()
        expect(rolled_row).to_have_attribute("data-status", "todo")
        expect(rolled_row.locator(".trow-due")).to_have_attribute("title", next_due)
        expect(head).to_contain_text(f"{today['counts']['today'] - 1} due today")
        rolled_row.scroll_into_view_if_needed()
        shot(page, shots / "story-05-board-6-desktop.png")

        # 7b. The same recurring task, set "done" instead of completed: closes
        #     for good — no further roll, off the recurring series from here
        #     (issue #54's other half). The row's circle only rolls it, so the
        #     close-for-good lives in the drawer's status select (#311).
        rolled_row.locator(".trow-main").click()
        drawer = page.locator("#taskDrawer")
        # the pane already shows Today's first due task (#393): wait for this one
        expect(drawer.locator("#drawerTitle")).to_have_value("Vocabulary review")
        drawer.locator("select[data-field='status']").select_option("done")
        page.keyboard.press("Escape")
        expect(drawer).to_be_hidden()
        expect(soon.locator(f".trow[data-id='{vid}']")).to_have_count(0)
        closed = _get(base, f"/api/tasks/{vid}")
        assert closed["status"] == "done" and closed["due"] == next_due
        assert closed["done_at"] is not None

        # 8. Mark a plain overdue task done → done today: it leaves the Today
        #    list (open tasks only) and the Board's Done today column gains
        #    it, alongside 6b's now-closed recurring task (both done today).
        books = _today_row(page, "Return library books")
        bid = int(books.get_attribute("data-id"))
        books.locator(".trow-done").click()
        expect(page.locator(f"#paneToday section.today .trow[data-id='{bid}']")).to_have_count(0)
        done = _get(base, f"/api/tasks/{bid}")
        assert done["status"] == "done" and done["done_at"][:10] == E2E_ANCHOR.isoformat()
        page.click("nav.tabs .tab[data-tab='board']")
        expect(_col(page, "done").locator(f".trow[data-id='{bid}']")).to_be_visible()
        expect(_col(page, "done").locator(".board-col-count")).to_have_text("2")
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-7-desktop.png")

        # ---------------------------------------------- § #81 bulk select
        # 9. Select mode: tick three cards across three columns, bulk-change
        #    their status, and prove the selection is ONE store — it survives
        #    the trip to Today, whose bar counts the same three.
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
        # .icon-button's 34px against the select's 36px. The select is measured by
        # its painted box: its element is the 44px hit target, the 36px control
        # drawn inside a transparent border band (#281).
        boxes = bar.locator("select, button").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e);"
            " const t = e.tagName === 'SELECT' ? parseFloat(cs.borderTopWidth) : 0;"
            " const b = e.tagName === 'SELECT' ? parseFloat(cs.borderBottomWidth) : 0;"
            " return {y: r.y + t, h: r.height - t - b, w: r.width}; })")
        assert len(boxes) == 4, boxes                        # Move · status select · delete · ✕
        # Move is the bar's first action, as it is the row's (#392)
        expect(bar.locator("select, button").first).to_have_class(re.compile(r"\bbulk-move\b"))
        assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2, boxes
        assert len({round(b["h"]) for b in boxes}) == 1, boxes
        assert all(round(s["w"]) == round(s["h"]) for s in boxes[:1] + boxes[2:]), boxes
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-10-desktop.png")

        # 10. The selection carries to Today: its own Select bar is up, counting
        #     the same three — one store, not a set per view.
        page.click("nav.tabs .tab[data-tab='today']")
        expect(page.locator("#paneToday [data-select-toggle]")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#todayBulk .bulk-count")).to_have_attribute("aria-label", "3 selected")
        _clear_toasts(page)
        shot(page, shots / "story-05-board-11-desktop.png")
        page.click("nav.tabs .tab[data-tab='board']")

        # 11. Bulk-change the status → all three move, each with its own
        #     activity row, exactly as three single-task edits would have.
        page.locator("#boardBulk .bulk-status").select_option("standby")
        expect(page.locator("#boardBulk")).to_be_hidden()          # applied, selection cleared
        for i in ids:
            detail = _get(base, f"/api/tasks/{i}")
            assert detail["status"] == "standby", detail
            log = next(a for a in detail["activity"] if a["field"] == "status")
            assert log["new_value"] == "standby", log
        # Select mode is still on — the next pick needs no second trip to the toggle
        expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "true")

        # 12. A bulk move (#392): the bar's Move opens the one date sheet a row
        #     opens — the push-outs, each beside its date — and a pick moves the
        #     whole selection in one tap plus one choice.
        page.locator(f"#paneBoard .trow[data-id='{ids[0]}'] .trow-check").check()
        page.locator(f"#paneBoard .trow[data-id='{ids[1]}'] .trow-check").check()
        page.locator("#boardBulk .bulk-move").click()
        sheet = page.locator(".snooze-pop .snooze-menu[data-field='due']")
        expect(sheet).to_be_visible()
        expect(sheet).to_have_attribute("aria-label", "Move 2 selected tasks to another date")
        expect(sheet.locator(".snooze-clear")).to_be_visible()      # a selection may clear its dates
        target = _get(base, "/api/dates?phrases=next%20week")["dates"]["next week"]
        sheet.locator(".snooze-opt[data-phrase='next week']").click()
        expect(page.locator("#boardBulk")).to_be_hidden()
        assert [_get(base, f"/api/tasks/{i}")["due"] for i in ids[:2]] == [target, target]

        # 13. A batch that partially fails names the id rather than dropping
        #     it silently — the task deleted in another tab (#81).
        page.locator(f"#paneBoard .trow[data-id='{ids[0]}'] .trow-check").check()
        page.locator(f"#paneBoard .trow[data-id='{ids[1]}'] .trow-check").check()
        page.evaluate(f"fetch('/api/tasks/{ids[1]}', {{method: 'DELETE'}})")
        page.locator("#boardBulk .bulk-status").select_option("todo")
        expect(page.locator(".toasts")).to_have_text(re.compile(rf"1 updated .* 1 failed .*#{ids[1]}"))
        assert _get(base, f"/api/tasks/{ids[0]}")["status"] == "todo"
        shot(page, shots / "story-05-board-12-desktop.png")

        # 14. Leaving Select mode puts the pane back exactly as it was.
        page.click("#paneBoard [data-select-toggle]")
        expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "false")
        expect(page.locator("#paneBoard .trow-check")).to_have_count(0)
        expect(page.locator("#paneBoard [data-quick-add]")).to_be_visible()

        _walk_keyboard_actions(page, base, shots)
        _walk_done_journal(page, base, shots)
        _walk_delete_task(page, base, shots)
        _walk_edit_refresh(page, base)
        _walk_today_horizons(page, base, shots)
        assert errors == [], errors
    finally:
        context.close()
    _walk_phone_today_landing_and_board_carousel(base, playwright, shots)


def _clear_toasts(page: Page) -> None:
    """Toasts stack and outlive a step, so each assertion below reads only its
    own: drop what is on screen before pressing the next key."""
    page.evaluate("document.getElementById('toasts').replaceChildren()")


def _open_issue_from_menu(page: Page, row, fragment: str) -> None:
    """The row's issue glyph is passive; the link is the ⋯ menu's ``issue``
    item, which opens the forge in a new tab. ``window.open`` is recorded
    rather than followed (no network, no popup left behind)."""
    # a function, not an expression: Playwright invokes an expression whose value
    # is a function, which would record one stray argument-less call
    page.evaluate("() => { window.__opened = []; window.open = (...a) => { window.__opened.push(a); return null; }; }")
    row.locator(".trow-kebab").click()
    page.locator(".row-menu [data-action='issue']").click()
    opened = page.evaluate("window.__opened")
    assert len(opened) == 1 and fragment in opened[0][0], opened
    assert opened[0][1:] == ["_blank", "noopener"], opened
    expect(page.locator(".row-menu")).to_have_count(0)


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
    shot(page, shots / "story-16-keyboard-triage-1-desktop.png")
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
    assert _get(base, f"/api/tasks/{rid}")["due"] == (E2E_ANCHOR + timedelta(days=1)).isoformat()

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
    picks = ["Write README", "Garden"]                          # todo · standby
    for title in picks:
        _card(page, title).locator(".trow-check").check()
    ids = [int(_card(page, t).get_attribute("data-id")) for t in picks]
    assert [_get(base, f"/api/tasks/{i}")["status"] for i in ids] == ["todo", "standby"]
    page.evaluate(f"document.querySelector('.trow[data-id=\"{ids[0]}\"] .trow-main').focus()")
    _clear_toasts(page)
    page.keyboard.press("1")
    expect(page.locator(".toasts")).to_have_text(re.compile("2 tasks"))
    assert [_get(base, f"/api/tasks/{i}")["status"] for i in ids] == ["inbox", "inbox"]
    shot(page, shots / "story-16-keyboard-triage-2-desktop.png")
    _clear_toasts(page)
    page.keyboard.press("z")
    expect(page.locator(".toasts")).to_have_text(re.compile("Undone"))
    assert [_get(base, f"/api/tasks/{i}")["status"] for i in ids] == ["todo", "standby"]
    # the ticks survive a keyed action (several keys, one set), so Escape is
    # what leaves Select mode — the toggle is hidden while the bar is up
    expect(page.locator(f"#paneBoard .trow[data-id='{ids[0]}']")).to_have_class(re.compile("is-selected"))
    page.keyboard.press("Escape")
    expect(page.locator("#boardBulk")).to_be_hidden()

    # 22. …and a Search hit, which may be a task outside the filtered list —
    #     the prior values then come from a fetch, not from what is on screen.
    page.click("nav.tabs .tab[data-tab='search']")
    page.fill("#searchInput", "README")
    tasks_group = page.locator(".search-group[data-kind='tasks']")
    expect(tasks_group).to_have_attribute("open", "")          # a group with hits opens (#395)
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
    # 9 keyed actions + the row menu's . + Z + ?, then the five "getting around"
    # keys; the keyless actions (reopen, cancelled) live in the row menu (#311)
    expect(page.locator("#keysHelp .keys-rows").first.locator(".keys-row")).to_have_count(12)
    expect(page.locator("#keysHelp .keys-rows").first).to_contain_text("Complete task")
    expect(page.locator("#keysHelp")).to_contain_text("Getting around")
    shot(page, shots / "story-16-keyboard-triage-3-desktop.png")
    page.keyboard.press("Escape")
    expect(page.locator("#keysHelp")).to_be_hidden()

    # the same sheet in the dark theme (the modal's backdrop swallows a click
    # on the header toggle, so the theme flips between openings)
    page.click("#themeToggle")
    page.keyboard.press("?")
    expect(page.locator("#keysHelp")).to_be_visible()
    shot(page, shots / "story-16-keyboard-triage-4-desktop.png")
    page.keyboard.press("Escape")
    page.click("#themeToggle")

    page.keyboard.press("Control+K")
    page.fill("#paletteInput", ">priority")
    expect(page.locator(".palette-item").first).to_contain_text("Cycle priority")
    expect(page.locator(".palette-item").first.locator("kbd")).to_have_text("P")
    shot(page, shots / "story-16-keyboard-triage-5-desktop.png")
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
    today = E2E_ANCHOR
    iso = lambda days_ago: (today - timedelta(days=days_ago)).isoformat()  # noqa: E731
    watering = _get(base, "/api/tasks?q=watering%20schedule")["items"][0]
    assert watering["status"] == "todo", watering["status"]       # the keyboard walk put it back

    # 1. The Done column's head links to the journal: no tab lit, #journal in the URL.
    _clear_toasts(page)
    page.click("nav.tabs .tab[data-tab='board']")
    page.click("#paneBoard .board-status .board-col[data-col='done'] .board-col-link")
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
    expect(kettle).to_have_attribute("data-status", "done")
    expect(kettle.locator(".trow-done")).to_have_attribute("aria-pressed", "true")
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
    expect(drift.locator(".trow-meta .trow-issue")).to_have_count(0)   # #392: the link is the menu's
    _open_issue_from_menu(page, drift, "garden-bot/issues/12")   # a closed task's menu still carries the link
    expect(drift.locator(".trow-project")).to_have_text("Side project: garden-bot")
    shot(page, shots / "story-18-done-journal-1-desktop.png")

    # 4. The cancelled switch drops the muted rows (and the count follows).
    page.click(".journal-toggle .toggle")
    expect(page.locator("#journalHost .trow[data-status='cancelled']")).to_have_count(0)
    expect(_journal_day(page, iso(2)).locator(".today-group-count")).to_have_text("1 done")
    page.click(".journal-toggle .toggle")
    expect(page.locator("#journalHost .trow[data-status='cancelled']")).to_have_count(1)

    # 5. The shared filters apply and ride the URL; the controls that say
    #    nothing about a closed task are not there.
    family = _get(base, "/api/tasks?q=family%20admin")["items"][0]
    sheet = open_filter_sheet(page, "paneJournal")
    names = sheet.locator(".filter-sheet-row").evaluate_all("els => els.map(e => e.dataset.name)")
    assert names == ["project", "person"], names
    sheet.locator("select[name='project']").select_option(str(family["id"]))
    close_filter_sheet(page)
    expect(page.locator("#journalHost .trow-project").first).to_have_text("Family admin")
    projects = page.locator("#journalHost .trow-project").all_inner_texts()
    assert projects and set(projects) == {"Family admin"}, projects
    assert f"project={family['id']}" in page.url and page.url.endswith("#journal"), page.url
    expect(filter_button(page, "paneJournal")).to_have_attribute("aria-label", "Filters, 1 on: Family admin")
    open_filter_sheet(page, "paneJournal").locator(".filter-clear").click()
    close_filter_sheet(page)
    expect(page.locator("#journalHost .trow-project").first).not_to_have_text("Family admin")

    # 5b. The boot forest no longer carries closed tasks (#309), so a project
    #     whose children are all closed is a leaf there — the filter still
    #     lists it, because the list comes from /api/projects. The project is
    #     made and removed here, so the seed (and the gallery) stay as seeded.
    json_h = {"content-type": "application/json"}
    shut = page.request.post(f"{base}/api/tasks", data=json.dumps({"title": "Spent project"}), headers=json_h).json()
    child = page.request.post(f"{base}/api/tasks", data=json.dumps({"title": "Spent step", "parent_id": shut["id"]}),
                              headers=json_h).json()
    closed = page.request.patch(f"{base}/api/tasks/{child['id']}", data=json.dumps({"status": "done"}), headers=json_h)
    assert closed.ok, closed.text()
    page.goto(f"{base}/?_e2e=spent#journal")     # a fresh boot reads /api/projects again
    listed = [o.strip() for o in open_filter_sheet(page, "paneJournal").locator("select[name='project'] option").all_inner_texts()]
    assert "Spent project" in listed, listed
    close_filter_sheet(page)
    assert page.request.delete(f"{base}/api/tasks/{shut['id']}").ok
    page.goto(f"{base}/?_e2e=spent-gone#journal")   # the board in memory still held it
    expect(page.locator("#paneJournal")).to_be_visible()
    expect(filter_button(page, "paneJournal")).to_have_attribute("aria-label", "Filters")   # …as the walk left it

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
    shot(page, shots / "story-18-done-journal-2-desktop.png")
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
    page.keyboard.press("Control+K")
    page.fill("#paletteInput", ">journal")
    expect(page.locator(".palette-item").first).to_contain_text("Journal")
    page.keyboard.press("Enter")
    expect(page.locator("#paneJournal")).to_be_visible()
    assert page.evaluate("location.hash") == "#journal"
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator("#paneJournal")).to_be_hidden()

    # leave the coding task as the seed had it (the phone leg reads Today)
    page.evaluate(f"fetch('/api/tasks/{watering['id']}', {{method: 'PATCH', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{status: 'todo'}})}})")
    page.wait_for_function(f"() => fetch('/api/tasks/{watering['id']}').then(r => r.json()).then(t => t.status === 'todo')")


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
    # The drawer is its own scroller and Delete sits at its foot, so the click
    # would scroll the panel by however much the layout happened to need at
    # that instant — and the Issue section below it arrives on a fetch. The
    # shot behind the dialog was then a coin toss between two offsets: 163,962
    # px apart between two runs of one commit (#225). Park it at the end first
    # and prove it stayed there (#166), so the click scrolls nothing.
    scroll_to_bottom(page, drawer)
    drawer.locator(".drawer-delete").click()
    dialog = page.locator("#confirmDialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#confirmTitle")).to_have_text('Delete "Repaint the garden fence"?')
    expect(dialog.locator(".confirm-body")).to_contain_text("Its 2 child tasks go with it.")
    expect(dialog.locator(".confirm-body")).to_contain_text("cannot be undone")
    expect(dialog.locator(".confirm-warn")).to_have_count(0)     # not a synced coding task
    shot(page, shots / "story-19-delete-task-1-desktop.png")

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

    # 4. A batch of mistakes from the Board's Select bar: one dialog with the count.
    _clear_toasts(page)
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator(f"#boardHost .trow[data-id='{dupe}']")).to_be_visible()
    page.click("#paneBoard [data-select-toggle]")
    page.locator(f"#boardHost .trow[data-id='{dupe}'] .trow-check").check()
    page.locator(f"#boardHost .trow[data-id='{test}'] .trow-check").check()
    page.locator("#boardBulk .bulk-delete").click()
    expect(dialog).to_be_visible()
    expect(dialog.locator("#confirmTitle")).to_have_text("Delete 2 tasks?")
    shot(page, shots / "story-19-delete-task-2-desktop.png")
    dialog.locator(".confirm-danger").click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".toasts")).to_contain_text("2 tasks deleted")
    expect(page.locator(f"#boardHost .trow[data-id='{dupe}']")).to_have_count(0)
    expect(page.locator(f"#boardHost .trow[data-id='{test}']")).to_have_count(0)
    assert _status(page, base, f"/api/tasks/{dupe}") == 404
    # a clean batch clears the selection but stays in Select mode; leave it as found
    expect(page.locator("#boardBulk")).to_be_hidden()
    page.click("#paneBoard [data-select-toggle]")
    expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "false")


def _in_view(page: Page) -> list[str]:
    """The Status columns whose left edge is inside the phone's viewport (an
    empty column is collapsed away there, so it has no box)."""
    boxes = {k: _col(page, k).bounding_box() for k in COLUMNS}
    return [k for k, b in boxes.items() if b and 0 <= b["x"] < PHONE["width"] - 1]


def _walk_phone_today_landing_and_board_carousel(base: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): Today is the landing tab; the Board's Week
    mode one list of lane sections, its Status mode a one-column scroll-snap
    carousel with the count strip; 44px targets (the row's circle and ⋯ kebab
    included, #311)."""
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
        # the ONE row on the phone: ≥44px tall, no completion circle on a
        # touch screen (#350 — the swipe and the drawer's status close a task),
        # the ⋯ kebab a real 44px box (#311) never overlapping the open target
        assert_min_target(rows)
        expect(rows.locator(".trow-done").first).to_be_hidden()
        assert_min_target(rows.locator(".trow-kebab"))
        assert_no_overlap(rows.locator(".trow-kebab"))
        heights = rows.locator(".trow-kebab").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and all(h == 44 for h in heights), heights
        first_today = rows.first
        assert_no_overlap([first_today.locator(c) for c in (".trow-main", ".trow-kebab")])
        assert_no_horizontal_overflow(page)
        # #399: the scope switch is on the phone's Today, the row's full width,
        # its segments real touch targets
        _assert_scope_switch_spans_row(page)
        assert_min_target(page.locator("#todayScope .segmented-item"))
        assert_no_overlap(page.locator("#todayScope .segmented-item"))
        shot(page, shots / "story-05-board-8-phone.png")

        # …and raised in dark when the theme follows the system: nothing is
        # stored, so the pre-paint stamp reads the OS scheme (#399)
        dark = wk.new_context(
            viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True,
            color_scheme="dark",
        )
        try:
            dpage = dark.new_page()
            dpage.goto(f"{base}/")
            expect(dpage.locator("html")).to_have_attribute("data-theme", "dark")
            _assert_scope_switch_spans_row(dpage)
            lums = dpage.evaluate(
                """() => {
                  const lum = c => { const m = c.match(/\\d+(\\.\\d+)?/g).map(Number);
                                     return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]; };
                  const sw = document.querySelector('#todayScope .scope-switch');
                  return {track: lum(getComputedStyle(sw).backgroundColor),
                          picked: lum(getComputedStyle(
                            sw.querySelector('.segmented-item[aria-pressed="true"]')).backgroundColor)};
                }"""
            )
            assert lums["picked"] > lums["track"], lums   # raised, not sunk
        finally:
            dark.close()

        # 10. Board, Week mode (#396): one list, the lanes stacked as its
        #     sections under their headers, the empty ones out of the way — no
        #     carousel and no strip; the row's swipe and menu move a task.
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        expect(page.locator("#paneBoard")).to_be_visible()
        expect(page.locator("#paneBoard .board-strip")).to_be_hidden()
        week = page.locator("#paneBoard .board-week")
        sections = week.locator(".board-col:not([hidden]):not(.is-empty)")
        assert sections.count() >= 3
        wbox = week.bounding_box()
        sboxes = [sections.nth(i).bounding_box() for i in range(sections.count())]
        for a, b in zip(sboxes, sboxes[1:], strict=False):
            assert abs(a["x"] - b["x"]) < 2 and a["y"] + a["height"] <= b["y"] + 1, (a, b)   # stacked
        assert all(abs(b["width"] - wbox["width"]) < 2 for b in sboxes), (wbox, sboxes)
        expect(sections.first.locator(".board-col-title")).to_be_visible()
        assert_min_target(week.locator(".trow"))
        assert_min_target(page.locator("#paneBoard .board-bar .segmented-item"))
        assert_no_overlap(page.locator("#paneBoard .board-bar .segmented-item"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-14-phone.png")

        #     …Status mode: strip of counts + one column per screen
        #     (scroll-snap). Every column holds a task by now — the desktop
        #     walk closed two today — so none is collapsed (story 07 shows one).
        board_mode(page, "status")
        strip = page.locator("#paneBoard .board-strip-btn")
        expect(strip).to_have_count(4)
        expect(page.locator("#paneBoard .board-strip-btn.is-empty")).to_have_count(0)
        assert_min_target(strip)
        assert_no_overlap(strip)
        columns = page.locator("#paneBoard .board-status")
        assert columns.evaluate("el => getComputedStyle(el).scrollSnapType").startswith("x")
        wrap = columns.bounding_box()
        first = _col(page, "inbox").bounding_box()
        assert wrap and first and abs(first["width"] - wrap["width"]) < 2, (wrap, first)
        # exactly one column inside the viewport at a time
        visible = _in_view(page)
        assert len(visible) == 1, visible
        # tap the strip → the carousel scrolls to that column and marks it active
        page.locator(".board-strip-btn[data-col='standby']").tap()
        expect(page.locator(".board-strip-btn[data-col='standby']")).to_have_class(re.compile(r"\bactive\b"))
        page.wait_for_function(
            "() => Math.abs(document.querySelector(\".board-status .board-col[data-col='standby']\").getBoundingClientRect().left"
            " - document.querySelector('.board-status').getBoundingClientRect().left) < 2"
        )
        # the row budget (UX round 2, issue #32; slimmed to 60px + the hairline
        # with a meta line by #311): every seeded row in the active column stays
        # inside the ≤61px ceiling. #32's own acceptance criterion names this a phone-width
        # (390px, PHONE above) Board-row contract — not asserted at 320px
        # (#110's geometry sweep found rows over budget there, e.g. a long
        # title whose meta line wraps to more lines at the narrower width).
        heights = _col(page, "standby").locator(".trow").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and all(h <= 61 for h in heights), heights
        # touch fallback for the drag: the row's ⋯ kebab menu carries the status
        # items (#311) — the open target and the kebab are separate 44px-tall
        # cells in a line, the kebab flush with the row's right edge (UX rounds
        # 1-3, issues #27/#32/#46); no circle on a touch screen (#350)
        first_item = _col(page, "standby").locator(".trow").first
        expect(first_item.locator(".trow-done")).to_be_hidden()
        main_box = first_item.locator(".trow-main").bounding_box()
        kebab_box = first_item.locator(".trow-kebab").bounding_box()
        item_box = first_item.bounding_box()
        assert main_box and kebab_box and item_box
        assert (kebab_box["width"], kebab_box["height"]) == (44, 44), kebab_box
        assert main_box["x"] + main_box["width"] <= kebab_box["x"] + 1, (main_box, kebab_box)
        assert item_box["x"] + item_box["width"] - (kebab_box["x"] + kebab_box["width"]) <= 8, (kebab_box, item_box)
        assert_no_overlap([first_item.locator(c) for c in (".trow-main", ".trow-kebab")])
        first_item.locator(".trow-kebab").tap()
        menu = page.locator(".row-menu")
        expect(menu).to_be_visible()
        expect(menu.locator("[data-action='status-todo']")).to_be_visible()
        expect(menu.locator("[data-action='status-inbox']")).to_be_visible()
        expect(menu.locator("[data-action='status-standby']")).to_have_count(0)   # the column it is already in
        page.keyboard.press("Escape")
        expect(menu).to_have_count(0)
        # flat list, not a card: no rounded box on the column's list
        assert _col(page, "standby").locator(".board-list").evaluate("el => getComputedStyle(el).borderRadius") == "0px"
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-9-phone.png")

        # Landing straight on the Board (the tab is remembered now): the nav
        # positions the carousel before the first list has loaded, so an
        # unguarded placement clamps to column one while the strip still reads
        # "Todo". The strip and the column in view must name the same thing.
        page.reload()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        expect(page.locator("#paneBoard .board-strip-btn.active")).to_have_attribute("data-col", "todo")
        page.wait_for_function(
            "() => { const a = document.querySelector('.board-strip-btn.active');"
            "        const w = document.querySelector('.board-status');"
            "        if (!a || !w) return false;"
            "        const c = w.querySelector(\".board-col[data-col='\" + a.dataset.col + \"']\");"
            "        return c && Math.abs(c.getBoundingClientRect().left - w.getBoundingClientRect().left) < 2; }"
        )
        # and the column on screen really is the one the strip names
        in_view = _in_view(page)
        assert in_view == ["todo"], in_view

        # 11. § #81 on the phone: the same Select toggle, tap-to-select (no
        #     gesture — the horizontal swipe still belongs to the carousel),
        #     and the bulk bar sized for the strip, clear of the nav pill.
        # the strip's two buttons are one pair: the same height, 44px on touch
        # (the toggle used to keep the 36px control height here); the toggle
        # says "Select" in words, so it is as wide as its label (#339)
        toggle = page.locator("#paneBoard [data-select-toggle]")
        expect(toggle).to_have_text("Select")
        tog_box = toggle.bounding_box()
        add_box = page.locator("#paneBoard [data-quick-add]").bounding_box()
        assert tog_box and add_box
        assert tog_box["height"] == add_box["height"] == add_box["width"] >= 44, (tog_box, add_box)
        assert tog_box["width"] >= 44, tog_box
        assert_no_overlap(page.locator("#paneBoard .pane-top button"))

        page.locator("#paneBoard [data-select-toggle]").tap()
        checks = _col(page, "standby").locator(".trow-check")
        expect(checks.first).to_be_visible()
        assert_min_target(_col(page, "standby").locator(".trow"))
        assert_no_overlap(checks)
        # a tap on the card body ticks it instead of opening the drawer
        _col(page, "standby").locator(".trow").first.locator(".trow-main").tap()
        expect(_col(page, "standby").locator(".trow.is-selected")).to_have_count(1)
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
        assert len(boxes) == 4, boxes                       # Move · status select · delete · ✕
        assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2, boxes
        assert len({round(b["h"]) for b in boxes}) == 1, boxes
        squares = boxes[:1] + boxes[2:]
        assert all(round(s["w"]) == round(s["h"]) >= 44 for s in squares), squares
        assert bar_box["height"] < 2 * boxes[0]["h"], bar_box   # never wrapped
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-05-board-10-phone.png")

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
        shot(page, shots / "story-18-done-journal-3-phone.png")
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        expect(page.locator("#paneJournal")).to_be_hidden()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
        context.close()
    finally:
        wk.close()


# Wraps the page's own fetch so a list read is answered by the server at once
# and handed to the app late — the order the network does not promise (#321).
# In the page, not a Playwright route: a route handler that sleeps is a callback
# in flight, and one still sleeping when the context closes fails the teardown.
_HOLD_LIST_READS = r"""() => {
  const real = window.fetch.bind(window);
  const hold = window.__hold = {on: false, held: 0, delivered: 0};
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init && init.method) || 'GET';
    const lists = /\/api\/(tasks\?|tasks\/tree|today)/.test(url);
    if (!hold.on || method !== 'GET' || !lists) return real(input, init);
    hold.held += 1;
    return real(input, init).then(function (res) {
      return new Promise(function (resolve) {
        setTimeout(function () { hold.delivered += 1; resolve(res); }, 1500);
      });
    });
  };
}"""


def _walk_today_horizons(page: Page, base: str, shots: Path) -> None:
    """§ #350 (story 31) — no open task is out of Today's reach.

    With the Table gone, Today lists every open task in four horizons — Today,
    Soon (the next seven days), Later and No date — and the strip's text filter
    works across all of them. A task due a year out and a task with no date are
    reached from Today by scrolling, then each by its text alone. The walk makes
    both over the API and deletes them after, so the seed stays whole.
    """
    def make(body: dict) -> int:
        return page.evaluate(
            "b => fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
            "body: JSON.stringify(b)}).then(r => r.json()).then(t => t.id)", body)

    far_due = (E2E_ANCHOR + timedelta(days=365)).isoformat()
    far = make({"title": "Renew the residence card", "due": far_due, "status": "todo"})
    loose = make({"title": "Sort the attic boxes", "status": "todo"})
    try:
        page.goto(f"{base}/")
        page.click("nav.tabs .tab[data-tab='today']")
        pane = page.locator("#paneToday")
        # 1. Later and No date start closed with their counts (#393, decision 6
        #    of #390); one tap opens each, and a re-render keeps it open.
        later = pane.locator(".today-far")
        nodate = pane.locator(".today-nodate")
        assert later.evaluate("el => el.open") is False and nodate.evaluate("el => el.open") is False
        expect(pane.locator(".today-soon")).to_have_js_property("open", True)
        _clear_toasts(page)
        nodate.scroll_into_view_if_needed()
        shot(page, shots / "story-31-today-horizons-4-desktop.png")      # folded, counts showing
        for horizon in (later, nodate):
            n = int(horizon.locator(".section-count").inner_text())
            assert n == horizon.locator(".trow[data-id]").count() and n >= 1
            horizon.locator(".collapse-summary").click()
            expect(horizon).to_have_js_property("open", True)
        page.locator("#paneToday .scope-switch .segmented-item").nth(2).click()   # All: a re-render
        page.locator("#paneToday .scope-switch .segmented-item").nth(0).click()   # back to Mine
        expect(later).to_have_js_property("open", True)
        expect(nodate).to_have_js_property("open", True)
        far_row = later.locator(f".trow[data-id='{far}']")
        loose_row = nodate.locator(f".trow[data-id='{loose}']")
        far_row.scroll_into_view_if_needed()
        expect(far_row).to_be_in_viewport()
        expect(far_row.locator(".trow-due")).to_have_attribute("title", far_due)
        loose_row.scroll_into_view_if_needed()
        expect(loose_row).to_be_in_viewport()
        expect(loose_row.locator(".trow-due")).to_have_count(0)
        # the horizons come in order, nearest first, and every open task the
        # filter shows is in exactly one of them; each header is the overline
        # role (caps from CSS, so the text itself stays sentence case) with its
        # count beside it (#391)
        heads = pane.locator(".today-horizon .collapse-title")
        order = heads.evaluate_all("els => els.map(e => e.textContent)")
        assert order == ["Soon", "Later", "No date"], order
        assert heads.evaluate_all("els => els.every(e => e.classList.contains('overline') "
                                  "&& getComputedStyle(e).textTransform === 'uppercase')")
        expect(later.locator(".section-count")).to_have_text(re.compile(r"^\d+$"))
        _clear_toasts(page)
        nodate.scroll_into_view_if_needed()
        shot(page, shots / "story-31-today-horizons-1-desktop.png")
        # 2. The text filter reaches both from the top strip
        q = page.locator("#todayFilterText .filter-q")
        listed = pane.locator(".today-group .trow[data-id]")
        q.fill("residence card")
        expect(listed).to_have_count(1)
        expect(later.locator(f".trow[data-id='{far}']")).to_be_visible()
        q.fill("attic")
        expect(listed).to_have_count(1)
        expect(nodate.locator(f".trow[data-id='{loose}']")).to_be_visible()
        expect(page).to_have_url(re.compile(r"[?&]q=attic"))
        # under a text filter an empty section says nothing matches it, never
        # "all clear": the day may be full, the filter just hides it (#339)
        for empty in (pane.locator("section.today .empty-state"), pane.locator(".today-soon .empty-state")):
            expect(empty).to_contain_text("matches “attic”")
            expect(empty).not_to_contain_text("all clear")
        nodate.locator(f".trow[data-id='{loose}']").scroll_into_view_if_needed()
        shot(page, shots / "story-31-today-horizons-2-desktop.png")
        q.fill("")
        _walk_scope_switch(page, base, shots)
    finally:
        for tid in (far, loose):
            page.evaluate("id => fetch('/api/tasks/' + id, {method: 'DELETE'})", tid)


_SWITCH_BOXES_JS = """() => {
  const box = e => { const r = e.getBoundingClientRect(); return {x: r.x, w: r.width, h: r.height}; };
  const host = document.getElementById('todayScope');
  const group = host.querySelector('.scope-switch');
  return {host: box(host), group: box(group),
          items: [...group.querySelectorAll('.segmented-item')].map(box)};
}"""


def _assert_scope_switch_spans_row(page: Page) -> None:
    """§ #399 — the switch is on screen and spans the width of its row.

    The row is the switch's host (the pane's own width); the three segments
    share the track equally. Pixel tolerance 1 (sub-pixel layout), never the
    360px the switch used to stop at.
    """
    switch = page.locator("#todayScope .segmented.scope-switch")
    expect(switch).to_be_visible()
    expect(switch.locator(".segmented-item")).to_have_count(3)
    b = page.evaluate(_SWITCH_BOXES_JS)
    assert abs(b["group"]["w"] - b["host"]["w"]) <= 1, b
    assert abs(b["group"]["x"] - b["host"]["x"]) <= 1, b
    widths = [i["w"] for i in b["items"]]
    assert max(widths) - min(widths) <= 1, widths
    # the track's 3px inset on each side is the only width the segments do not use
    assert abs(sum(widths) + 6 - b["group"]["w"]) <= 1, b


def _walk_scope_switch(page: Page, base: str, shots: Path) -> None:
    """§ #391 — Today's Mine · Issues · All switch, one URL key, Mine by default.

    The seed's one synced coding task (it carries an issue_ref) is the Issues
    scope; everything else is Mine. The pick survives a reload through
    ``?scope=``, and Mine writes no key at all. Under Issues the Soon horizon
    holds a single project's group, so it draws no sub-header and the row
    names its project on the meta line instead.
    """
    pane = page.locator("#paneToday")
    switch = page.locator("#todayScope .segmented.scope-switch")
    pressed = switch.locator(".segmented-item[aria-pressed='true']")
    rows = pane.locator(".today-group .trow[data-id]")
    open_items = _get(base, "/api/tasks")["items"]
    issue_ids = sorted(t["id"] for t in open_items if t.get("issue_ref"))
    assert issue_ids, "the seed carries one synced coding task"
    # 1. Mine is the default: on screen, and absent from the URL
    expect(pressed).to_have_text("Mine")
    expect(page).not_to_have_url(re.compile(r"[?&]scope="))
    _assert_scope_switch_spans_row(page)   # #399: the row's full width on desktop
    for tid in issue_ids:
        expect(pane.locator(f".trow[data-id='{tid}']")).to_have_count(0)
    # 2. Issues: only the synced tasks, the pick written to the URL
    switch.locator(".segmented-item[data-scope='issues']").click()
    expect(pressed).to_have_text("Issues")
    expect(page).to_have_url(re.compile(r"[?&]scope=issues"))
    expect(rows).to_have_count(len(issue_ids))
    assert sorted(int(i) for i in rows.evaluate_all("els => els.map(e => e.dataset.id)")) == issue_ids
    # 3. …and kept across a reload
    page.reload()
    expect(pressed).to_have_text("Issues")
    expect(rows).to_have_count(len(issue_ids))
    # one group in the horizon: no sub-header, the row names its project
    expect(pane.locator(".today-group-title")).to_have_count(0)
    expect(rows.first.locator(".trow-project")).to_be_visible()
    _clear_toasts(page)
    shot(page, shots / "story-31-today-horizons-3-desktop.png")
    # 4. All, then back to Mine, which drops the key again
    switch.locator(".segmented-item[data-scope='all']").click()
    expect(page).to_have_url(re.compile(r"[?&]scope=all"))
    for tid in issue_ids:
        expect(pane.locator(f".trow[data-id='{tid}']")).to_have_count(1)
    switch.locator(".segmented-item[data-scope='mine']").click()
    expect(pressed).to_have_text("Mine")
    expect(page).not_to_have_url(re.compile(r"[?&]scope="))


def _walk_edit_refresh(page: Page, base: str) -> None:
    """§ #321 — a late read from an earlier refresh must not undo a newer edit.

    Every edit's ``refreshAll()`` follows the last one's, and the network does
    not answer in order: the read issued before the second edit landed used to
    resolve *after* the one issued once it had, and the older snapshot then sat
    on the rows until a reload. The walk holds the list reads of the first
    edit's refresh (the server answers them at once — it is the delivery that
    is late), makes the second edit while they are held, and only checks the
    rows after the held answers have been delivered, so a stale overwrite has
    already happened by the time it is looked for.
    """
    made = page.evaluate(
        "b => fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
        "body: JSON.stringify(b)}).then(r => r.json())",
        {"title": "Renew the parking permit", "status": "todo", "due": E2E_ANCHOR.isoformat()})
    tid = made["id"]
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")   # the last tab left is remembered, not Today
    expect(_today_row(page, "Renew the parking permit")).to_be_visible()   # due today → the due list
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator(f"#boardHost .trow[data-id='{tid}']")).to_be_visible()
    page.evaluate(_HOLD_LIST_READS)

    def counts() -> dict:
        return page.evaluate("window.__hold")

    page.locator(f"#boardHost .trow[data-id='{tid}'] .trow-title").click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()

    # 1. The title, with its refresh's list reads held back.
    page.evaluate("window.__hold.on = true")
    drawer.locator("#drawerTitle").fill("Renew the residents' permit")
    drawer.locator("#drawerTitle").press("Enter")
    for _ in range(100):
        if counts()["held"]:
            break
        page.wait_for_timeout(50)
    assert counts()["held"], "the first edit's refresh never read the list"
    # …every read of that refresh, not only the first to arrive: wait until the
    # batch stops growing before the hold is lifted.
    seen = -1
    while seen != counts()["held"]:
        seen = counts()["held"]
        page.wait_for_timeout(250)

    # 2. The due date, while those reads are still held: a phrase, the way the
    #    drawer takes one. Its refresh is answered at once.
    page.evaluate("window.__hold.on = false")
    due = drawer.locator("input[data-field='due']")
    due.fill("in 30 days")
    later = (E2E_ANCHOR + timedelta(days=30)).isoformat()
    # (#364) Enter fires a PATCH, and a read taken right after the key can beat
    # it on a busy box and see the old date. The walk waits on that PATCH's
    # response — and parks the request first, so the stale window is certain
    # rather than occasional: the read below must still see the old date, and
    # only the answered PATCH may make it the new one.
    parked: list = []

    def park_patch(route):
        if route.request.method == "PATCH":
            parked.append(route)
        else:
            route.continue_()

    page.route(f"**/api/tasks/{tid}", park_patch)
    try:
        with page.expect_response(
            lambda r: r.request.method == "PATCH" and r.url.endswith(f"/api/tasks/{tid}")
        ) as patched:
            due.press("Enter")
            for _ in range(100):
                if parked:
                    break
                page.wait_for_timeout(50)
            assert parked, "the due edit never sent its PATCH"
            assert _get(base, f"/api/tasks/{tid}")["due"] != later, "the PATCH was not held"
            parked.pop().continue_()
        assert patched.value.ok, patched.value.status
    finally:
        for route in parked:
            route.continue_()
        page.unroute(f"**/api/tasks/{tid}", park_patch)
    assert _get(base, f"/api/tasks/{tid}")["due"] == later

    # 3. Let every held answer land, then settle — the stale overwrite, if there
    #    is one, has happened by now.
    for _ in range(200):
        state = counts()
        if state["delivered"] >= state["held"]:
            break
        page.wait_for_timeout(50)
    assert state["delivered"] >= state["held"], "held reads were never delivered"
    settle(page)

    # 4. Board: the new title and the new due on the one row, no reload.
    row = page.locator(f"#boardHost .trow[data-id='{tid}']")
    expect(row.locator(".trow-title")).to_have_text("Renew the residents' permit")
    expect(row).to_contain_text("in 4w")
    expect(drawer.locator("#drawerTitle")).to_have_value("Renew the residents' permit")

    # 5. Today: the task moved out of the due list with its date.
    page.click("nav.tabs .tab[data-tab='today']")
    expect(_today_row(page, "Renew the residents' permit")).to_have_count(0)
    expect(_today_row(page, "Renew the parking permit")).to_have_count(0)

    # 6. Leave the instance as found: the phone leg shares it, and one more
    #    task would move its counts and the shots that show them.
    page.evaluate(f"fetch('/api/tasks/{tid}', {{method: 'DELETE'}})")
