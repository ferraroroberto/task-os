"""Story 04's desktop walk, one named step each.

``test_desktop_triage`` calls these in order. A step is a slice of the walk,
not an isolated test: it leaves the page where the next one expects it, and the
``surface()`` captures sit in the test body between the steps.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, expect

from tests.e2e._geometry import assert_no_horizontal_overflow
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _get,
    assert_date_sheet,
    assert_on_crumb_line,
    board_mode,
    close_filter_sheet,
    dismiss_toasts,
    filter_button,
    open_filter_sheet,
    shot,
)

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
    expect(dates).to_have_attribute("data-field", "due")
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
    expect(first_act.locator(".activity-meta")).to_contain_text("Roberto")  # X-Actor default from the sample config
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
    """The drawer's due quick-moves re-date, then a comment's link is a chip that opens a new tab."""
    # 3b. Due leads the drawer with the date sheet's phrases as one-tap
    #     moves (#394): push-outs first, each with the date it resolves to;
    #     one tap re-dates, then the typed field puts the date back.
    due_input = drawer.locator(".field-due input[data-field='due']")
    moves = drawer.locator(".quick-moves")
    assert_date_sheet(moves, base)
    next_week = moves.locator(".snooze-opt[data-phrase='next week']")
    pushed = next_week.locator(".snooze-opt-date").get_attribute("data-date")
    next_week.click()
    expect(due_input).to_have_value(pushed)
    assert _get(base, f"/api/tasks/{task_id}")["due"] == pushed
    expect(drawer.locator(".activity-row").first.locator(".activity-new")).to_have_text(pushed)
    due_input.fill(new_due)
    due_input.press("Enter")
    expect(due_input).to_have_value(new_due)
    # fill() already set the field, so the value check above waits for nothing:
    # the activity row is what appears once the write has landed (#411).
    expect(drawer.locator(".activity-row").first.locator(".activity-new")).to_have_text(new_due)
    assert _get(base, f"/api/tasks/{task_id}")["due"] == new_due
    # the rare fields wait behind More fields, closed on a fresh load
    expect(drawer.locator("details.drawer-more")).not_to_have_attribute("open", "")
    expect(drawer.locator("input[data-field='starts']")).to_be_hidden()

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
    shot(page, shots / "story-04-triage-4-desktop.png")
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
    expect(page.locator(".toast-success").last).to_contain_text("renew passport")
    # the todo filter hides a standby task — clear to see it, as a user would
    open_filter_sheet(page, "paneBoard").locator(".filter-clear").click()
    expect(page).to_have_url(f"{base}/")
    expect(page.locator("#filterSheet .filter-checks[data-name='status'] input:checked")).to_have_count(0)
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
    expect(drawer.locator(".drawer-crumbs .crumb-root")).to_have_text("top level")
    expect(drawer.locator(".drawer-remove-parent")).to_have_count(0)   # nothing to remove yet
    assert_on_crumb_line(drawer)                                       # #486: on the breadcrumb's line
    expect(drawer.locator("select[data-field='parent']")).to_have_count(0)   # one way, not two
    drawer.locator(".drawer-change-parent").click()
    picker = page.locator("#parentDialog")
    expect(picker).to_be_visible()
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
    expect(page.locator(".toast-success").last).to_contain_text("under Family admin")
    moved = _get(base, f"/api/tasks/{new_id}")
    assert moved["parent_id"] == family_id
    assert [c["title"] for c in moved["breadcrumb"]] == ["Family admin"]
    assert moved["activity"][0]["field"] == "parent"
    expect(drawer.locator(".drawer-crumbs .crumb")).to_have_text(["Family admin"])
    # …and the row says where it lives now (the meta line's project part)
    expect(_trow(page, "renew passport", "#paneBoard").locator(".trow-project")).to_have_text("Family admin")
    shot(page, shots / "story-04-triage-7-desktop.png")
    # Remove parent: one tap from the head, no confirmation, back to the top level
    drawer.locator(".drawer-remove-parent").click()
    expect(page.locator(".toast-success").last).to_contain_text("to the top level")
    expect(drawer.locator(".drawer-crumbs .crumb-root")).to_have_text("top level")
    expect(drawer.locator(".drawer-remove-parent")).to_have_count(0)
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
    expect(page.locator(".toast-error").last).to_contain_text("cycle")
    assert _get(base, f"/api/tasks/{home_id}")["parent_id"] is None
    assert _get(base, f"/api/tasks/{kitchen_id}")["parent_id"] == home_id

    # 8. Deep link: a fresh load of #task/<id> opens the drawer with the breadcrumb.
    page.goto(f"{base}/#task/{new_id}")
    expect(page.locator("#taskDrawer")).to_be_visible()
    expect(page.locator("#taskDrawer .drawer-crumbs .crumb")).to_have_text(["Family admin"])
    dismiss_toasts(page)
    shot(page, shots / "story-04-triage-8-desktop.png")
