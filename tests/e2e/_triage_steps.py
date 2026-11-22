"""Story 04's desktop walk, one named step each.

``test_desktop_triage`` calls these in order. A step is a slice of the walk,
not an isolated test: it leaves the page where the next one expects it, and the
``surface()`` captures sit in the test body between the steps.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, expect

from tests.e2e._geometry import assert_no_horizontal_overflow
from tests.e2e._ui import (
    assert_crumb_trail,
    assert_date_sheet,
    board_mode,
    close_filter_sheet,
    filter_button,
    open_filter_sheet,
    pick_prop,
)
from tests.e2e._work_root import E2E_WORK_ROOT
from tests.e2e.conftest import E2E_ANCHOR, _get, dismiss_toasts, shot

LINK = "https://example.com/passport-office"


def _next_friday(today: date) -> date:
    coming = today + timedelta(days=(4 - today.weekday()) % 7)
    return coming + timedelta(days=7)


def _trow(page: Page, title: str, scope: str = ""):
    """The ONE shared task row (rows.js) by exact title, optionally inside ``scope``
    (the seed has both "Renew passports" and the story's "renew passport")."""
    return page.locator(f"{scope} .trow".strip(), has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first

def _filtered_board(page: Page, base: str, shots: Path) -> object:
    """The Board filtered status:todo through the URL. Returns the Get three quotes row."""
    # 1. The Board filtered status:todo — via the URL, the shareable view.
    #    The filter is shared by every tab (UX round 3), so the URL never
    #    moves the tab by itself: open the Board, the query survives the switch.
    # the Board's default scope is Mine (#396): a synced issue's task is not on it
    todo = [t for t in _get(base, "/api/tasks?status=todo")["items"] if not t.get("issue_ref")]
    todo_count = len(todo)
    page.goto(f"{base}/?status=todo")
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
    board_mode(page, "status")
    expect(page).to_have_url(f"{base}/?status=todo")
    # the strip's filter button says what is on — its count, and its name
    # in words (#395) — so nothing needs the sheet open to read the state
    button = filter_button(page, "paneBoard")
    expect(button.locator(".filter-count")).to_have_text("1")
    expect(button).to_have_attribute("aria-label", "Filter, 1 on: todo")
    # the sheet it opens leads with the sort; status is ticks in place, the
    # URL's one ticked (#48)
    sheet = open_filter_sheet(page, "paneBoard")
    expect(sheet.locator(".filter-sheet-row").first).to_have_attribute("data-name", "sort")
    status = sheet.locator(".filter-checks[data-name='status']")
    expect(status.locator("input[name='status']:checked")).to_have_count(1)
    expect(status.locator("input[name='status'][value='todo']")).to_be_checked()
    close_filter_sheet(page)
    # the count's one home is the text field's placeholder (#393)
    expect(page.locator("#boardFilterText .filter-q")).to_have_attribute(
        "placeholder", f"Filter {todo_count} tasks…")
    # a real status pill narrows the columns: only Todo is up, holding the list
    expect(page.locator("#paneBoard .board-status .board-col:not([hidden])")).to_have_count(1)
    rows = page.locator("#paneBoard .trow[data-id]")
    expect(rows).to_have_count(todo_count)
    shown = {int(i) for i in rows.evaluate_all("els => els.map(e => e.dataset.id)")}
    assert shown == {t["id"] for t in todo}
    quotes = _trow(page, "Get three quotes", "#paneBoard")
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-04-triage-1-desktop.png")
    return quotes

def _change_due_from_row(page: Page, base: str, shots: Path, quotes) -> tuple:
    """Move… → Pick a date… opens the picker and the pick lands. Returns the task id and both dates."""
    # 2. Change a due date from the row — ⋯ → Move… → Pick a date…
    #    opens the native calendar (#107, #311). `showPicker()` opens an OS
    #    widget no browser automation can drive, so the walk proves the two
    #    halves that are observable: the pick really does call it (stubbed at
    #    page load in `_RECORD_SHOW_PICKER`), and the day it commits really
    #    does PATCH.
    task_id = int(quotes.get_attribute("data-id"))
    old_due = _get(base, f"/api/tasks/{task_id}")["due"]
    page.evaluate("window.__pickerOpens = []")
    quotes.locator(".trow-kebab").click()
    page.locator(".row-menu [data-action='change-date']").click()
    dates = page.locator(".snooze-pop .snooze-menu")
    # the date sheet (#391): push-outs first, each phrase beside its date
    assert_date_sheet(dates, base)
    assert dates.locator(".snooze-opt[data-phrase='tomorrow'] .snooze-opt-date").get_attribute(
        "data-date") == (E2E_ANCHOR + timedelta(days=1)).isoformat()
    dates.locator(".snooze-pick").click()
    assert page.evaluate("window.__pickerOpens") == ["due-date"], "Pick a date… did not open the picker"
    new_due = (E2E_ANCHOR + timedelta(days=14)).isoformat()
    dates.locator(".due-date").evaluate(
        "(el, v) => { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); }", new_due
    )
    expect(page.locator(f"#paneBoard .trow[data-id='{task_id}'] .trow-due")).to_have_attribute("title", new_due)
    assert _get(base, f"/api/tasks/{task_id}")["due"] == new_due
    dismiss_toasts(page)
    shot(page, shots / "story-04-triage-2-desktop.png")
    return task_id, old_due, new_due

def _open_drawer_with_activity(page: Page, base: str, shots: Path, task_id: int, old_due: str, new_due: str) -> object:
    """The drawer opens beside the list and its log shows due: old → new. Returns the drawer."""
    # 3. Open the drawer → activity shows due: old → new with actor + time.
    page.locator(f"#paneBoard .trow[data-id='{task_id}'] .trow-main").click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(page).to_have_url(f"{base}/?status=todo#task/{task_id}")
    expect(drawer.locator("#drawerTitle")).to_have_value("Get three quotes")
    expect(drawer.locator(".drawer-crumbs .crumb")).to_have_text(["Home renovation", "Kitchen"])
    first_act = drawer.locator(".activity-row").first
    expect(first_act).to_have_attribute("data-field", "due")
    expect(first_act.locator(".activity-old")).to_have_text(old_due)
    expect(first_act.locator(".activity-new")).to_have_text(new_due)
    expect(first_act.locator(".activity-meta")).to_contain_text("Casey")  # X-Actor default from the sample config
    # The list stays visible beside the drawer (side panel, not an overlay).
    board_box = page.locator("#boardHost").bounding_box()
    drawer_box = drawer.bounding_box()
    assert board_box and drawer_box and board_box["x"] + board_box["width"] <= drawer_box["x"] + 1
    assert drawer_box["width"] >= 400
    shot(page, shots / "story-04-triage-3-desktop.png")
    return drawer

def _drawer_quick_moves_and_comment(
    page: Page, context: BrowserContext, base: str, shots: Path, drawer, task_id: int, new_due: str
) -> None:
    """The drawer's due chips re-date, then a comment's link is a chip that opens a new tab."""
    # 3b. Due sits under Status as the date sheet's own chip grid: each
    #     phrase over the date it resolves to; one tap re-dates and marks
    #     that chip, then the Due row's typed field puts the date back.
    due_input = drawer.locator(".field-due input[data-field='due']")
    moves = drawer.locator(".drawer-due")
    assert_date_sheet(moves, base)
    next_week = moves.locator(".snooze-opt[data-phrase='next week']")
    pushed = next_week.locator(".snooze-opt-date").get_attribute("data-date")
    next_week.click()
    expect(due_input).to_have_attribute("data-date", pushed)
    expect(moves.locator(".snooze-opt[data-phrase='next week']")).to_have_attribute("aria-current", "date")
    assert _get(base, f"/api/tasks/{task_id}")["due"] == pushed
    expect(drawer.locator(".activity-row").first.locator(".activity-new")).to_have_text(pushed)
    due_input.fill(new_due)
    due_input.press("Enter")
    expect(due_input).to_have_attribute("data-date", new_due)
    expect(drawer.locator(".activity-row").first.locator(".activity-new")).to_have_text(new_due)
    assert _get(base, f"/api/tasks/{task_id}")["due"] == new_due
    # the rare fields wait behind More fields, the log behind Activity, both
    # closed on a fresh load
    expect(drawer.locator("details.drawer-more")).not_to_have_attribute("open", "")
    expect(drawer.locator("details.drawer-activity")).not_to_have_attribute("open", "")
    expect(drawer.locator("input[data-field='starts']")).to_be_hidden()

    # 4. Add a comment containing a link → the comment's words are the link, newest first.
    # Send is the drawer's one primary button; Notes edit in place on a tap.
    expect(drawer.locator(".comment-input")).to_have_attribute("placeholder", "Comment or paste a link…")
    expect(drawer.locator(".comment-send")).to_have_class(re.compile(r"\bbutton-primary\b"))
    expect(drawer.locator(".button-primary")).to_have_count(1)
    expect(drawer.locator(".drawer-desc-view")).to_have_attribute("aria-label", "Edit notes")
    drawer.locator(".comment-input").fill(f"Office booked, details at {LINK} — bring photos")
    drawer.locator(".comment-input").press("Control+Enter")
    newest = drawer.locator(".comment").first
    expect(newest.locator(".comment-body")).to_contain_text("Office booked")
    # a comment with exactly one link IS that link (#768): the words around the URL
    # are the anchor, the raw URL is never shown, and nothing is signed with our own name
    chip = newest.locator("a.comment-link")
    expect(chip).to_have_attribute("href", LINK)
    expect(chip).to_have_attribute("target", "_blank")
    expect(chip).to_have_attribute("rel", "noopener")
    expect(newest.locator(".comment-body")).not_to_contain_text("https://")
    expect(newest.locator(".comment-author")).to_have_count(0)
    expect(newest.locator("a.chip")).to_have_count(0)
    expect(newest.locator(".comment-when")).to_have_attribute("title", re.compile(r"· ui$"))
    comments = _get(base, f"/api/tasks/{task_id}/comments")["items"]
    assert comments[-1]["origin"] == "ui" and LINK in comments[-1]["body"]
    shot(page, shots / "story-04-triage-4-desktop.png")
    # click the link: opens the new tab (the target is stubbed —
    # the suite never depends on the network)
    context.route(LINK, lambda route: route.fulfill(status=200, content_type="text/html", body="<title>stub</title>ok"))
    with context.expect_page() as popup_info:
        chip.click()
    popup = popup_info.value
    popup.wait_for_load_state()
    assert popup.url == LINK, popup.url
    popup.close()
    walk_old_comment_dates(page, base, drawer, task_id)
    drawer.locator(".drawer-close").click()
    expect(drawer).to_be_hidden()

def assert_comment_date_gap(drawer, forms: int = 3) -> None:
    """Every visible comment's date keeps a clear gap before its text, and the texts align.

    The thread is the one `_age_comments` left: today's time, a this-year short
    date and a previous-year date that carries the year (the longest form).
    """
    rows = drawer.locator(".comment")
    expect(rows).to_have_count(forms)
    texts = drawer.locator(".comment .comment-when").all_inner_texts()
    assert any(re.fullmatch(r"\d{1,2} \w{3} \d{2}", t) for t in texts), texts   # the year form is on screen
    boxes = rows.evaluate_all(
        """rows => rows.map(r => {
            const range = document.createRange();   // the glyphs' own box: the <time> box stays track-wide while its text spills
            range.selectNodeContents(r.querySelector('.comment-when'));
            const b = r.querySelector('.comment-body').getBoundingClientRect();
            return {whenRight: range.getBoundingClientRect().right, bodyLeft: b.left};
        })""")
    for text, box in zip(texts, boxes, strict=True):
        assert box["bodyLeft"] - box["whenRight"] >= 4, (text, box)    # a gap, not a touch
    assert len({round(b["bodyLeft"]) for b in boxes}) == 1, boxes      # the bodies stay aligned


def walk_old_comment_dates(page: Page, base: str, drawer, task_id: int) -> None:
    """Re-date the open task's seeded comments across years, assert the date gap, put them back.

    The API stamps every comment "now", so a previous-year comment needs the
    stored timestamp moved: the oldest two go to last December, the third to
    January, the one this walk typed stays today's. The original stamps are
    restored afterwards and the drawer re-opened, so nothing later in the story
    (or its shots) sees the re-dated thread.
    """
    db = E2E_WORK_ROOT / "seeded-test_story_04_triage" / "tasks.db"
    year = date.today().year
    stamps = [f"{year - 1}-12-12T09:30:00+00:00", f"{year - 1}-12-17T09:30:00+00:00", f"{year}-01-07T09:30:00+00:00"]
    items = _get(base, f"/api/tasks/{task_id}/comments")["items"][:3]
    assert len(items) == 3, items

    def stamp(values: list[str]) -> None:
        with sqlite3.connect(db, timeout=10) as conn:
            for c, ts in zip(items, values, strict=True):
                conn.execute("UPDATE comments SET ts = ? WHERE id = ?", (ts, c["id"]))
        # close and re-open through the URL hash: the drawer re-reads its thread
        # while the list behind it keeps its scroll, which a reload would reset
        drawer.locator(".drawer-close").evaluate("el => el.click()")
        expect(drawer).to_be_hidden()
        page.evaluate("id => { location.hash = '#task/' + id; }", task_id)
        expect(drawer).to_be_visible()
        expect(drawer.locator(".comment")).not_to_have_count(0)

    stamp(stamps)
    try:
        assert_comment_date_gap(drawer)
    finally:
        stamp([c["ts"] for c in items])


def _quick_add_fill(page: Page, shots: Path) -> tuple:
    """The + opens quick-add; the typed phrase parses into the due field. Returns the dialog, input, date."""
    # 5. Quick-add (#80): the + in the top strip opens the one dialog;
    #    "renew passport next friday" parses into the editable Due field,
    #    and the rest of the first-moment fields are right there — no second
    #    trip through the drawer to set a description, a status, a folder
    #    or a link.
    page.locator("#paneBoard .quick-add-btn").click()
    quick_add = page.locator("#quickAdd")
    expect(quick_add).to_be_visible()
    qa = quick_add.locator(".quick-add-input")
    qa.fill("renew passport next friday")
    friday = _next_friday(E2E_ANCHOR).isoformat()
    expect(quick_add.locator(".quick-add-due")).to_have_value(friday)
    # To Do is the default for a task added by hand (#148) — Inbox is for
    # what arrives on its own, and this one is being typed.
    expect(quick_add.locator(".quick-add-status")).to_have_value("todo")
    quick_add.locator(".quick-add-desc").fill("both passports, town hall appointment")
    # Pick something the default is NOT, so this still proves the select is
    # honoured rather than agreeing with the default by accident.
    quick_add.locator(".quick-add-status").select_option("standby")
    quick_add.locator(".quick-add-folder").fill("{onedrive}/house")
    quick_add.locator(".quick-add-link-url").fill("https://example.com/passport-form")
    quick_add.locator(".quick-add-link-label").fill("application form")
    shot(page, shots / "story-04-triage-5-desktop.png")
    return quick_add, qa, friday

def _quick_add_create(page: Page, base: str, shots: Path, quick_add, qa, friday: str) -> tuple:
    """Enter creates the task with every field set. Returns its row and id."""
    # 6. Enter creates it with everything set and closes the dialog; the new
    #    row is focused (default filter = open).
    qa.press("Enter")
    expect(quick_add).to_be_hidden()
    expect(page.locator("#toast")).to_contain_text("renew passport")
    # the todo filter hides a standby task — clear to see it, as a user would
    open_filter_sheet(page, "paneBoard").locator(".filter-clear").click()
    expect(page).to_have_url(f"{base}/")
    # Clear is the resting filter: the sheet draws only Todo ticked (the strip's Todo pill), nothing counted
    expect(page.locator("#filterSheet .filter-checks[data-name='status'] input:checked")).to_have_count(1)
    expect(page.locator("#filterSheet .filter-checks[data-name='status'] input[value='todo']")).to_be_checked()
    close_filter_sheet(page)
    expect(filter_button(page, "paneBoard").locator(".filter-count")).to_be_hidden()
    new_row = _trow(page, "renew passport", "#paneBoard .board-status section.board-col[data-col='standby']")
    expect(new_row).to_be_visible()
    new_id = int(new_row.get_attribute("data-id"))
    created = _get(base, f"/api/tasks/{new_id}")
    assert created["due"] == friday and created["parent_id"] is None
    # every field the dialog offered landed on the task in one go (#80)
    assert created["status"] == "standby"
    assert created["description"] == "both passports, town hall appointment"
    assert created["folder_ref"] == "{onedrive}/house"
    assert [(link_["url"], link_["label"]) for link_ in created["links"]] == [
        ("https://example.com/passport-form", "application form")
    ]
    expect(new_row.locator(".trow-due")).to_have_attribute("title", friday)
    dismiss_toasts(page)
    shot(page, shots / "story-04-triage-6-desktop.png")
    return new_row, new_id

def _change_parent_picker(page: Page, base: str, shots: Path, new_row, new_id: int, drawer) -> tuple:
    """File the task under a project from the drawer head's Change parent picker."""
    # 7. File it under a project from the drawer head's Change parent
    #    (#468; #350: the Tree and its drag are gone, and the More-fields
    #    Move to select with them — this is the one re-parent path, on
    #    every pointer) → moved, toast, breadcrumb, activity.
    family_id = next(p["id"] for p in _get(base, "/api/projects")["items"] if p["title"] == "Family admin")
    new_row.locator(".trow-main").click()
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("renew passport")
    expect(drawer.locator(".drawer-crumbs .crumb-root")).to_have_text("Top level")
    assert_crumb_trail(drawer)                                         # the trail is the picker's button
    expect(drawer.locator("select[data-field='parent']")).to_have_count(0)   # one way, not two
    drawer.locator(".drawer-change-parent").click()
    picker = page.locator("#parentDialog")
    expect(picker).to_be_visible()
    expect(picker.locator(".parent-none")).to_have_count(0)            # nothing to remove yet
    offered = picker.locator(".parent-opt .parent-opt-title").all_inner_texts()
    assert "renew passport" not in offered and "Family admin" in offered, offered   # never itself
    picker.locator(".parent-filter").fill("family")
    expect(picker.locator(".parent-opt:visible .parent-opt-title").first).to_have_text("Family admin")
    shot(page, shots / "story-04-triage-12-desktop.png")
    return family_id, picker

def _parent_move_remove_and_cycle(
    page: Page, base: str, shots: Path, new_id: int, family_id: int, picker, drawer
) -> None:
    """Pick, remove and re-pick a parent; a cycle the server refuses is a toast; a deep link opens it."""
    picker.locator(f".parent-opt[data-id='{family_id}']").click()
    expect(picker).to_be_hidden()
    expect(page.locator("#toast")).to_contain_text("under Family admin")
    moved = _get(base, f"/api/tasks/{new_id}")
    assert moved["parent_id"] == family_id
    assert [c["title"] for c in moved["breadcrumb"]] == ["Family admin"]
    assert moved["activity"][0]["field"] == "parent"
    expect(drawer.locator(".drawer-crumbs .crumb")).to_have_text(["Family admin"])
    # …and the row says where it lives now (the project pill before the title)
    expect(_trow(page, "renew passport", "#paneBoard").locator(".trow-pill-project")).to_have_text("Family admin")
    shot(page, shots / "story-04-triage-7-desktop.png")
    # The Parent row opens the same picker, the parent just used under Recent and
    # No parent beside it: back to the top level in one tap, no confirmation
    expect(drawer.locator(".prop-row[data-field='parent'] .prop-val")).to_have_text("Family admin")
    drawer.locator(".prop-row[data-field='parent']").click()
    expect(picker.locator(".parent-recent .parent-opt-title")).to_have_text(["Family admin", "No parent (top level)"])
    picker.locator(".parent-none").click()
    expect(page.locator("#toast")).to_contain_text("to the top level")
    expect(drawer.locator(".drawer-crumbs .crumb-root")).to_have_text("Top level")
    assert _get(base, f"/api/tasks/{new_id}")["parent_id"] is None
    # …and back under the project from the keyboard: filter, Enter picks the first match
    drawer.locator(".drawer-change-parent").click()
    picker.locator(".parent-filter").fill("family admin")
    picker.locator(".parent-filter").press("Enter")
    expect(picker).to_be_hidden()
    expect(drawer.locator(".drawer-crumbs .crumb")).to_have_text(["Family admin"])
    assert _get(base, f"/api/tasks/{new_id}")["parent_id"] == family_id
    # The picker never offers a task's own descendants: Home renovation's
    # child project, Kitchen, is not on its list. The server stays the
    # authority all the same: a cycle that appears after the picker was
    # drawn (Kitchen filed away, offered, then filed back under Home
    # renovation by someone else) is refused and surfaced as a toast.
    projects = {p["title"]: p["id"] for p in _get(base, "/api/projects")["items"]}
    home_id, kitchen_id = projects["Home renovation"], projects["Kitchen"]
    page.goto(f"{base}/#task/{home_id}")
    expect(drawer.locator("#drawerTitle")).to_have_value("Home renovation")
    drawer.locator(".drawer-change-parent").click()
    expect(picker).to_be_visible()
    assert "Kitchen" not in picker.locator(".parent-opt .parent-opt-title").all_inner_texts()
    page.keyboard.press("Escape")
    expect(picker).to_be_hidden()
    moved_away = page.request.post(f"{base}/api/tasks/{kitchen_id}/move", data={"parent_id": None})
    assert moved_away.ok, moved_away.text()
    page.reload()
    expect(drawer.locator("#drawerTitle")).to_have_value("Home renovation")
    drawer.locator(".drawer-change-parent").click()
    expect(picker.locator(f".parent-opt[data-id='{kitchen_id}']")).to_have_count(1)
    back = page.request.post(f"{base}/api/tasks/{kitchen_id}/move", data={"parent_id": home_id})
    assert back.ok, back.text()
    picker.locator(f".parent-opt[data-id='{kitchen_id}']").click()
    expect(page.locator("#toast.error")).to_contain_text("cycle")
    assert _get(base, f"/api/tasks/{home_id}")["parent_id"] is None
    assert _get(base, f"/api/tasks/{kitchen_id}")["parent_id"] == home_id

    # 8. Deep link: a fresh load of #task/<id> opens the drawer with the breadcrumb.
    page.goto(f"{base}/#task/{new_id}")
    expect(page.locator("#taskDrawer")).to_be_visible()
    expect(page.locator("#taskDrawer .drawer-crumbs .crumb")).to_have_text(["Family admin"])
    dismiss_toasts(page)
    shot(page, shots / "story-04-triage-8-desktop.png")


# Where story 25's first shot frames the open drawer: its Repeat row 300 px below
# the drawer's top edge, whatever the drawer was scrolled to getting there.
_FRAME_REPEAT_JS = """() => {
  const d = document.querySelector('#taskDrawer');
  const row = d.querySelector(".prop-row[data-field='recurrence']");
  const top = row.getBoundingClientRect().top - d.getBoundingClientRect().top + d.scrollTop;
  d.scrollTop = Math.round(top) - 300;
}"""


def _done_rolls(page: Page, base: str, task_id: int) -> date:
    """Done on a recurring task: the drawer closes, the toast names the next
    date and offers Undo; returns the due it rolled to."""
    drawer = page.locator("#taskDrawer")
    drawer.locator(".drawer-status [data-status='done']").click()
    expect(drawer).to_be_hidden()
    expect(page.locator("#toast")).to_contain_text("Completed — next:")
    return date.fromisoformat(_get(base, f"/api/tasks/{task_id}")["due"])


def _walk_recurrence_anchor(page: Page, base: str, shots: Path) -> None:
    """#112 — Repeat is a cadence *and* the fixed day it lands on.

    The seed's "Weekly review" repeats every Friday. The drawer's Repeat row
    shows the cadence with its On row under it; Done rolls the due to a Friday
    rather than one flat week on, and switching the cadence to one that
    cannot carry a weekday clears the anchor rather than keeping a stale day.

    Screenshot: docs/screenshots/story-17-recurrence-anchor-1-desktop.png
    """
    review = page.request.get(f"{base}/api/tasks?q=Weekly review").json()["items"][0]
    page.goto(f"{base}/#task/{review['id']}")
    drawer = page.locator("#taskDrawer")
    cadence = drawer.locator(".prop-row[data-field='recurrence']")
    anchor = drawer.locator("select[data-field='recurrence_anchor']")
    expect(cadence).to_have_attribute("data-value", "weekly")
    expect(anchor).to_have_value("fri")
    page.evaluate("document.getElementById('toast').hidden = true")
    shot(page, shots / "story-17-recurrence-anchor-1-desktop.png")

    # Done: its new due is a Friday, strictly after both the due it had and today.
    old_due = date.fromisoformat(review["due"])
    rolled = _done_rolls(page, base, review["id"])
    assert rolled.weekday() == 4, f"rolled to {rolled} ({rolled:%A}), expected a Friday"
    assert rolled > old_due and rolled > E2E_ANCHOR

    # A cadence that takes no fixed day drops the anchor — and its row with
    # it. The row vanishing is the re-render signal: the drawer only redraws
    # once the PATCH has come back, so the stored value is safe to read here.
    page.goto(f"{base}/#task/{review['id']}")
    expect(anchor).to_have_value("fri")
    pick_prop(page, drawer, "recurrence", "quarterly")
    expect(anchor).to_have_count(0)
    assert page.request.get(
        f"{base}/api/tasks/{review['id']}"
    ).json()["recurrence_anchor"] is None

    # Restore over the API, not the UI — the rest of this file reads the same
    # seeded DB; one synchronous call cannot race.
    page.request.patch(f"{base}/api/tasks/{review['id']}", data={
        "recurrence": "weekly", "recurrence_anchor": "fri", "due": review["due"],
    })


def _walk_recurrence_interval(page: Page, base: str, shots: Path) -> None:
    """#229 — Repeat every N: "every 7 weeks on Saturday".

    The seed's "Weekly review" is due on a Saturday. The drawer's Every field
    takes 7 and the On picker Saturday; the row behind the drawer reads the
    composed label, and completing the task lands exactly 7 weeks on — a
    Saturday, never the coming one. Restored over the API afterwards, like
    the anchor walk before it.

    Screenshot: docs/screenshots/story-25-recurrence-interval-1-desktop.png
    """
    review = page.request.get(f"{base}/api/tasks?q=Weekly review").json()["items"][0]
    task_url = f"{base}/api/tasks/{review['id']}"
    page.goto(f"{base}/")
    page.goto(f"{base}/#task/{review['id']}")
    drawer = page.locator("#taskDrawer")
    every = drawer.locator("input[data-field='recurrence_interval']")
    expect(every).to_have_value("")
    expect(drawer.locator(".field-unit")).to_have_text("weeks")

    def patched(r) -> bool:  # noqa: ANN001 — a Playwright Response
        return r.request.method == "PATCH" and r.url.endswith(f"/api/tasks/{review['id']}")

    every.fill("7")
    with page.expect_response(patched) as resp:
        every.press("Enter")
    assert resp.value.json()["recurrence_interval"] == 7
    with page.expect_response(patched) as resp:
        drawer.locator("select[data-field='recurrence_anchor']").select_option("sat")
    assert resp.value.json()["recurrence_anchor"] == "sat"
    # the re-rendered list behind the drawer speaks the same words the CLI prints
    label = "'every 7 weeks on Saturday'"
    expect(page.locator(f".trow-recur[title={label}], .due-recur[title={label}]").first).to_be_attached()
    expect(every).to_have_value("7")
    # The Every field already reads 7 before the drawer's re-render lands, so that
    # check settles nothing: the new activity rows, named in the drawer's words, are what the redraw adds (#459).
    expect(drawer.locator(".activity-row").nth(0)).to_contain_text("repeat on")
    expect(drawer.locator(".activity-row").nth(1)).to_contain_text("repeat every")
    page.evaluate("document.getElementById('toast').hidden = true")
    # Frame the drawer rather than inherit its scroll offset (#459). Where it ends
    # up is whatever Playwright's scroll-into-view and the redraws between them
    # left, against a layout that was still moving (the drawer's content grows by
    # tens of pixels as each redraw lands), so one capture sat 46 px off the
    # baseline with every pixel of content identical. Park the Repeat row at
    # the offset the baseline shows it, in the settled layout.
    page.evaluate(_FRAME_REPEAT_JS)
    shot(page, shots / "story-25-recurrence-interval-1-desktop.png")

    old_due = date.fromisoformat(review["due"])
    assert old_due.weekday() == 5, f"the seed's review is due {old_due:%A}, the walk expects a Saturday"
    rolled = _done_rolls(page, base, review["id"])
    assert rolled == old_due + timedelta(weeks=7), f"rolled to {rolled}, expected 7 weeks after {old_due}"
    assert page.request.get(task_url).json()["recurrence_interval"] == 7

    page.request.patch(task_url, data={
        "recurrence": "weekly", "recurrence_anchor": "fri", "recurrence_interval": None,
        "due": review["due"],
    })


# ------------------------------------------------- stale window (#101)
