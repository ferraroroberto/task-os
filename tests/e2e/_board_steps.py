"""Story 05's shared selectors and the desktop Board day, one named step each.

``test_desktop_board_day`` calls these in order; the phone leg and the
keyboard / journal walks live in ``_board_walks``. A step is a slice of the
walk, not an isolated test: it leaves the page where the next one expects it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e._geometry import assert_min_target, assert_no_horizontal_overflow
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
    shot,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
COLUMNS = ["inbox", "todo", "standby", "done"]
# Week mode's lanes on the anchor, a Monday (#396): the days each holds.
LANES = ["today", "tomorrow", "week", "weekend", "next", "later"]


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
    implements, stated here as dates so the two are checked against each other.
    No date closes Later, under its own sub-heading (#414)."""
    if not due:
        return "later"
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


def _walk_drawer_owner(page: Page, base: str, task_id: int, to: str) -> None:
    """Open ``task_id``'s drawer, pick ``to`` in its Owner, prove the write, the
    named activity row and a reload (#476). Leaves the drawer open on it."""
    names = {"p1": "Person 1", "p2": "Person 2"}
    before = _get(base, f"/api/tasks/{task_id}")
    page.goto(f"{base}/#task/{task_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer.locator("#drawerTitle")).to_have_value(before["title"])
    head = drawer.locator(".drawer-fields-main")
    owner = head.locator("select[data-field='owner']")
    expect(owner).to_be_visible()
    expect(owner).to_have_value(before["owner"])
    # one row with status and priority, never under More fields
    ys = head.locator("select").evaluate_all("els => els.map(e => Math.round(e.getBoundingClientRect().y))")
    assert len(ys) == 3 and len(set(ys)) == 1, ys
    with page.expect_response(
        lambda r: r.request.method == "PATCH" and r.url.endswith(f"/api/tasks/{task_id}")
    ) as written:
        owner.select_option(to)
    assert written.value.ok, f"the owner write answered {written.value.status}"
    row = drawer.locator(".activity-row[data-field='owner']").first
    expect(row.locator(".activity-old")).to_have_text(names[before["owner"]])
    expect(row.locator(".activity-new")).to_have_text(names[to])
    assert _get(base, f"/api/tasks/{task_id}")["owner"] == to
    page.reload()
    expect(drawer.locator("#drawerTitle")).to_have_value(before["title"])
    expect(drawer.locator("select[data-field='owner']")).to_have_value(to)


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


# ------------------------------------------------- the desktop day


def _week_lanes(page: Page, base: str) -> None:
    """Today is the landing tab; the Board's six lanes hold exactly their days' tasks."""
    # 1. Today is the landing tab on every pointer (#319); one tab press to the
    #    Board — the week planner (#396): the six lanes of a Monday side
    #    by side, each holding exactly the open tasks due in its days (the
    #    undated ones close Later).
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
        ["Today", "Tomorrow", "This week", "This weekend", "Next week", "Later"])
    mine_open = [t for t in _get(base, "/api/tasks")["items"] if not t.get("issue_ref")]
    for k in LANES:
        want = sorted(t["id"] for t in mine_open if _lane_of(t["due"]) == k)
        got = _lane(page, k).locator(".trow").evaluate_all("els => els.map(e => Number(e.dataset.id))")
        assert sorted(got) == want, (k, got, want)
        expect(_lane(page, k).locator(".board-col-count")).to_have_text(str(len(want)))
    lane_boxes = [_lane(page, k).bounding_box() for k in LANES]
    for a, b in zip(lane_boxes, lane_boxes[1:], strict=False):
        assert abs(a["y"] - b["y"]) < 2 and a["x"] + a["width"] <= b["x"] + 1, (a, b)   # one row, left to right
    # The six lanes share the window and nothing scrolls sideways at any
    # desktop width (#414): the board's own scroller, not just the page.
    for width in (1280, 1920, DESKTOP["width"]):
        page.set_viewport_size({"width": width, "height": DESKTOP["height"]})
        fits = page.locator("#paneBoard .board-week").evaluate("el => [el.scrollWidth, el.clientWidth]")
        assert fits[0] <= fits[1], (width, fits)
        assert_no_horizontal_overflow(page)
    # No date closes Later under its own sub-heading: the dated tasks
    # first, the undated after it, the lane's count holding both.
    due_of = {t["id"]: t["due"] for t in mine_open}
    undated_ids = sorted(i for i, due in due_of.items() if not due)
    assert undated_ids, "the seed has undated tasks"
    later = _lane(page, "later")
    expect(later.locator(".board-list-sub")).to_have_text(["No date"])
    split = later.locator(".board-list").evaluate(
        """ul => { const out = {before: [], after: []}; let seen = false;
                   for (const li of ul.children) {
                     if (li.classList.contains('board-list-sub')) seen = true;
                     else out[seen ? 'after' : 'before'].push(Number(li.dataset.id));
                   }
                   return out; }""")
    assert split["before"] and all(due_of[i] for i in split["before"]), split
    assert sorted(split["after"]) == undated_ids, (split, undated_ids)
    # The header names the exceptions from the lanes' own counts: the Inbox
    # arrivals in the accent, then what is overdue (#396).
    inbox_n = sum(1 for t in mine_open if t["status"] == "inbox")
    overdue_n = sum(1 for t in mine_open if t["due"] and t["due"] < E2E_ANCHOR.isoformat())
    head = page.locator("#homeHeadStatus")
    expect(head).to_have_text(f"{inbox_n} in Inbox · {overdue_n} overdue")
    expect(head.locator('[data-tone="accent"]')).to_have_text(f"{inbox_n} in Inbox")
    expect(head.locator('[data-tone="attention"]')).to_have_text(f"{overdue_n} overdue")
    # Triage works on the Inbox column: it is not on the week planner.
    expect(page.locator("#paneBoard .board-triage")).to_be_hidden()



def _week_lane_drag_and_clear(page: Page, base: str, shots: Path) -> None:
    """A drag between lanes moves the due date only; the sheet's No date clears it."""
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
    # The "Undone" toast is raised after the inverse write lands: waiting on it
    # keeps the API read below off a slower runner's race (#411).
    expect(page.locator(".toasts")).to_contain_text("Undone")
    expect(_lane(page, "tomorrow").locator(f".trow[data-id='{bkid}']")).to_be_visible()
    assert _get(base, f"/api/tasks/{bkid}")["due"] == before["due"]
    dismiss_toasts(page)
    #    Clearing a date is the Move sheet's "No date" (no lane drops on it):
    #    the task lands under Later's No date sub-heading, Undo brings it back.
    ceiling = _trow(page, "#paneBoard .board-week", "Repaint ceiling")
    cid = int(ceiling.get_attribute("data-id"))
    ceiling_due = _get(base, f"/api/tasks/{cid}")["due"]
    assert ceiling_due and _lane_of(ceiling_due) == "later", ceiling_due
    ceiling.locator(".trow-kebab").click()
    page.locator(".row-menu [data-action='change-date']").click()
    page.locator(".snooze-pop .snooze-menu[data-field='due'] .snooze-clear").click()
    expect(page.locator(".toasts")).to_contain_text("Due date cleared")
    assert _get(base, f"/api/tasks/{cid}")["due"] is None
    expect(_lane(page, "later").locator(f".board-list-sub ~ .trow[data-id='{cid}']")).to_have_count(1)
    page.locator(".toasts").get_by_role("button", name=re.compile("^Undo")).click()
    expect(page.locator(".toasts")).to_contain_text("Undone")
    assert _get(base, f"/api/tasks/{cid}")["due"] == ceiling_due
    expect(_lane(page, "later").locator(f".board-list-sub ~ .trow[data-id='{cid}']")).to_have_count(0)
    dismiss_toasts(page)



def _status_columns(page: Page, base: str, shots: Path) -> dict:
    """The Status segment: four columns side by side. Returns the Mine board's columns."""
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
    return api



def _top_strip(page: Page, base: str) -> None:
    """The text filter narrows the board without a disclosure; the + opens quick-add."""
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



def _project_filter(page: Page, base: str, shots: Path, api: dict) -> None:
    """A project filter shows only its descendants, rides the URL and is shared with Today."""
    # 3. Project filter → only that project's descendants; the URL carries it;
    #    Today's sheet shows the same selection (one shared state).
    home = next(t for t in api["todo"] if t["title"] == "Home renovation")
    sheet = open_filter_sheet(page, "paneBoard")
    sheet.locator("select[name='project']").select_option(str(home["id"]))
    expect(page).to_have_url(f"{base}/?project={home['id']}")
    expect(sheet.locator(".filter-clear")).to_be_visible()
    close_filter_sheet(page)
    expect(filter_button(page, "paneBoard")).to_have_attribute("aria-label", "Filter, 1 on: Home renovation")
    filtered = _mine(_get(base, f"/api/board?project={home['id']}")["columns"])
    expect(_col(page, "todo").locator(".board-col-count")).to_have_text(str(len(filtered["todo"])))
    assert _counts(page) == {k: len(filtered[k]) for k in COLUMNS}
    shown = page.locator("#paneBoard .board-list .trow").evaluate_all("els => els.map(e => Number(e.dataset.id))")
    allowed = {t["id"] for col in filtered.values() for t in col}
    assert shown and set(shown) <= allowed
    shot(page, shots / "story-05-board-2-desktop.png")
    page.click("nav.tabs .tab[data-tab='today']")
    expect(filter_button(page, "paneToday")).to_have_attribute("aria-label", "Filter, 1 on: Home renovation")
    expect(open_filter_sheet(page, "paneToday").locator("select[name='project']")).to_have_value(str(home["id"]))
    close_filter_sheet(page)
    page.click("nav.tabs .tab[data-tab='board']")
    open_filter_sheet(page, "paneBoard").locator(".filter-clear").click()
    close_filter_sheet(page)
    expect(page).to_have_url(f"{base}/")
    expect(_col(page, "todo").locator(".board-col-count")).to_have_text(str(len(api["todo"])))



def _drag_row_and_open_drawer(page: Page, base: str, shots: Path, api: dict) -> None:
    """Drag a row todo to standby, then open it: the drawer's log shows the move."""
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



def _today_due_list(page: Page, base: str, shots: Path) -> tuple:
    """Today lists due and overdue by project. Returns today's payload, header, Soon and a row."""
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
    expect(filter_button(page, "paneToday")).to_have_attribute("aria-label", "Filter")
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
    return today, head, soon, school



def _move_verb_sheet(page: Page, base: str, shots: Path, school) -> tuple:
    """On a fine pointer every open row carries Move; it opens the one date sheet."""
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
    expect(verb).to_have_class(re.compile(r"\baction-row-verb\b"))     # the vendored verb, no local un-painting
    assert verb.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
    assert verb.evaluate("e => getComputedStyle(e).borderTopWidth") == "0px"
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
    return sheet, sid



def _move_verb_apply(page: Page, base: str, sheet, sid: int) -> None:
    """A push-out phrase re-dates the row; Undo puts the seed's date back."""
    tomorrow = (E2E_ANCHOR + timedelta(days=1)).isoformat()
    # The toast is raised only after the write *and* a full refresh, so wait
    # for them in the order they happen: the POST lands (bounded by the
    # context's 15 s, not the 5 s of one `expect`), the list is redrawn
    # without the row, then the toast. A single 5 s wait on the toast read a
    # slow write as "no toast", which is not what the story is about.
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/api/tasks/bulk")
    ) as written:
        sheet.locator(".snooze-opt[data-phrase='tomorrow']").click()
    assert written.value.ok, f"the Move write answered {written.value.status}"
    expect(page.locator(f"#paneToday section.today .today-group .trow[data-id='{sid}']")).to_have_count(0)
    moved = page.locator(".toast-success").last
    expect(moved).to_contain_text("Due ")
    assert _get(base, f"/api/tasks/{sid}")["due"] == tomorrow
    moved.locator(".toast-action").click()
    expect(_today_row(page, "School enrolment forms")).to_be_visible()
    assert _get(base, f"/api/tasks/{sid}")["due"] == E2E_ANCHOR.isoformat()
    dismiss_toasts(page)



def _complete_recurring_then_done(page: Page, base: str, shots: Path, today: dict, head, soon) -> None:
    """Completing a recurring task rolls it, done closes it, a plain task lands in Done today."""
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



def _select_three_cards(page: Page, base: str, shots: Path) -> list[int]:
    """Select mode: tick three cards across three columns. Returns their ids."""
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
    assert len(boxes) == 5, boxes      # Move · status select · Set owner… (#476) · delete · ✕
    # Move is the bar's first action, as it is the row's (#392)
    expect(bar.locator("select, button").first).to_have_class(re.compile(r"\bbulk-move\b"))
    assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2, boxes
    assert len({round(b["h"]) for b in boxes}) == 1, boxes
    assert all(round(s["w"]) == round(s["h"]) for s in boxes[:1] + boxes[2:]), boxes
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-05-board-10-desktop.png")
    return ids



def _bulk_status_and_owner(page: Page, base: str, shots: Path, ids: list[int]) -> None:
    """The selection is one store across views; bulk status and Set owner act on it."""
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

    # 11b. Set owner… (#476): two members, so the bar offers them; one pick
    #      hands the selection to the second member, each with its row.
    page.locator(f"#paneBoard .trow[data-id='{ids[0]}'] .trow-check").check()
    page.locator(f"#paneBoard .trow[data-id='{ids[2]}'] .trow-check").check()
    owner_sel = page.locator("#boardBulk .bulk-owner-select")
    expect(page.locator("#boardBulk .bulk-owner")).to_be_visible()
    assert owner_sel.locator("option").all_inner_texts() == ["Set owner…", "Person 1", "Person 2"]
    owner_sel.select_option("p2")
    expect(page.locator("#boardBulk")).to_be_hidden()
    for i in (ids[0], ids[2]):
        detail = _get(base, f"/api/tasks/{i}")
        assert detail["owner"] == "p2", detail
        log = next(a for a in detail["activity"] if a["field"] == "owner")
        assert (log["old_value"], log["new_value"]) == ("p1", "p2"), log
    assert _get(base, f"/api/tasks/{ids[1]}")["owner"] == "p1"
    # 11c. The page opened on the owner's own tasks (#477), so the two just
    #      handed to the second member are off the Board; Everyone, one tap
    #      away, brings them back — the rest of the walk goes on under it.
    for i in (ids[0], ids[2]):
        expect(page.locator(f"#paneBoard .trow[data-id='{i}']")).to_have_count(0)
    expect(page.locator("#boardWhose .whose-switch .segmented-item[aria-pressed='true']")).to_have_text("Mine")
    page.locator("#boardWhose .whose-switch .segmented-item[data-whose='everyone']").click()
    for i in (ids[0], ids[2]):
        expect(page.locator(f"#paneBoard .trow[data-id='{i}']")).to_have_count(1)



def _bulk_move_and_partial_failure(page: Page, base: str, shots: Path, ids: list[int]) -> None:
    """A bulk Move re-dates the set; a batch that partly fails names the id; Select mode leaves."""
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
