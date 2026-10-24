"""Story 05's keyboard, done-journal and phone walks, split into named steps.

Each ``_walk_*`` driver keeps the name the story file calls; the steps under it
are the slices of one walk and leave the page where the next one starts.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from tests.e2e._board_steps import (
    COLUMNS,
    PHONE,
    _assert_scope_switch_spans_row,
    _card,
    _clear_toasts,
    _col,
    _open_issue_from_menu,
    _trow,
    _walk_drawer_owner,
)
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
)
from tests.e2e._surface import surface
from tests.e2e.conftest import (
    E2E_ANCHOR,
    _get,
    board_mode,
    close_filter_sheet,
    filter_button,
    open_filter_sheet,
    shot,
)


def _walk_keyboard_actions(page: Page, base: str, shots: Path) -> None:
    """§ #99 — a keyboard-only triage, with undo, on the Board.

    Story 16 in ``docs/validation.md`` points here. The keys act on the row
    that has focus (or on the ticked set), so the walk focuses rows the way a
    user's Tab does and then only presses keys.
    """
    rid = _keys_row_actions(page, base, shots)
    _keys_set_search_and_help(page, base, shots, rid)



def _keys_row_actions(page: Page, base: str, shots: Path) -> int:
    """Priority, due and complete by key with undo, and the guards. Returns the README task's id."""
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
    return rid



def _keys_set_search_and_help(page: Page, base: str, shots: Path, rid: int) -> None:
    """The same keys over a ticked set and a Search hit, then the `?` sheet and the palette."""
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
    surface(page, "app.keys-help")
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
    surface(page, "app.palette")
    page.keyboard.press("Escape")
    expect(page.locator("#palette")).to_be_hidden()



def _journal_day(page: Page, day: str):
    return page.locator(f".journal-day[data-day='{day}']")



def _iso_ago(days_ago: int) -> str:
    return (E2E_ANCHOR - timedelta(days=days_ago)).isoformat()



def _walk_done_journal(page: Page, base: str, shots: Path) -> None:
    """§ #102 — the done journal, from the Board's Done column.

    Runs after the keyboard walk, so today already holds what the story
    closed; the seed adds yesterday (two done), two days back (one done, one
    cancelled) and nine days back (the week before). One task is completed
    through the API mid-walk — the coding task with the issue chip — and
    restored at the end, so the phone leg's Today reads as seeded.
    """
    watering = _journal_days_and_filters(page, base, shots)
    _journal_older_drawer_palette(page, base, shots, watering)



def _journal_days_and_filters(page: Page, base: str, shots: Path) -> dict:
    """Open the journal from the Done column, read its days, close a task, filter. Returns the coding task."""
    iso = _iso_ago
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
    surface(page, "journal.done-days")

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
    expect(filter_button(page, "paneJournal")).to_have_attribute("aria-label", "Filter, 1 on: Family admin")
    open_filter_sheet(page, "paneJournal").locator(".filter-clear").click()
    close_filter_sheet(page)
    expect(page.locator("#journalHost .trow-project").first).not_to_have_text("Family admin")
    return watering



def _journal_older_drawer_palette(page: Page, base: str, shots: Path, watering: dict) -> None:
    """Older weeks, the drawer under #journal, a tab press and the palette leave and return."""
    iso = _iso_ago
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
    expect(filter_button(page, "paneJournal")).to_have_attribute("aria-label", "Filter")   # …as the walk left it

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
        _phone_today_landing(wk, page, base, shots)
        _phone_board_week(page, shots)
        _phone_board_status(page, shots)
        _phone_board_reload(page)
        _phone_select_and_owner(page, base, shots)
        _phone_journal(page, base, shots)
        context.close()
    finally:
        wk.close()



def _phone_today_landing(wk: Browser, page: Page, base: str, shots: Path) -> None:
    """Fresh phone lands on Today: 44px rows, the scope switch, and its dark raised fill."""
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
        # Each fill as the eye sees it: painted over the first opaque
        # backdrop behind the switch on a 1px canvas, so the translucent
        # track is composited and every CSS colour syntax (rgb(), color(srgb
        # …) from a color-mix) lands on one 0-255 scale (#412: the raw
        # computed strings put a 0-1 track beside a 0-255 fill).
        lums = dpage.evaluate(
            """() => {
              const sw = document.querySelector('#todayScope .scope-switch');
              const picked = sw.querySelector('.segmented-item[aria-pressed="true"]');
              const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
              const paint = fills => {
                ctx.clearRect(0, 0, 1, 1);
                fills.forEach(f => { ctx.fillStyle = f; ctx.fillRect(0, 0, 1, 1); });
                return ctx.getImageData(0, 0, 1, 1).data;
              };
              let back = sw.parentElement;
              while (back && paint([getComputedStyle(back).backgroundColor])[3] !== 255) back = back.parentElement;
              const base = getComputedStyle(back || document.documentElement).backgroundColor;
              const track = getComputedStyle(sw).backgroundColor;
              const lum = d => 0.2126 * d[0] + 0.7152 * d[1] + 0.0722 * d[2];
              return {track: lum(paint([base, track])),
                      picked: lum(paint([base, track, getComputedStyle(picked).backgroundColor]))};
            }"""
        )
        assert lums["picked"] > lums["track"], lums   # raised, not sunk
    finally:
        dark.close()



def _phone_board_week(page: Page, shots: Path) -> None:
    """Board, Week mode: one list of stacked lane sections."""
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



def _phone_board_status(page: Page, shots: Path) -> None:
    """Board, Status mode: the count strip and one scroll-snap column per screen."""
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



def _phone_board_reload(page: Page) -> None:
    """A reload on the Board places the carousel on the column the strip names."""
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



def _phone_select_and_owner(page: Page, base: str, shots: Path) -> None:
    """Select mode by tap with its bulk bar, then the full-screen drawer's Owner."""
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
    assert_min_target(bar.locator("button, .bulk-owner"))
    assert_no_overlap(bar.locator("button, .bulk-owner"))
    # ONE line, and one height: every control shares the row's centre and
    # the two square buttons match the strip's own (they wrapped to a
    # second line, and the date was a phrase box, before the owner's call)
    boxes = bar.locator("select, button").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect()).map(r => ({y: r.y, h: r.height, w: r.width}))")
    assert len(boxes) == 5, boxes      # Move · status select · Set owner… (#476) · delete · ✕
    assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2, boxes
    assert len({round(b["h"]) for b in boxes}) == 1, boxes
    squares = boxes[:1] + boxes[2:]
    assert all(round(s["w"]) == round(s["h"]) >= 44 for s in squares), squares
    assert bar_box["height"] < 2 * boxes[0]["h"], bar_box   # never wrapped
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-05-board-10-phone.png")

    # 11b. #476 on the phone: the full-screen drawer's head carries the
    #      Owner too, and a pick there hands the task over and holds.
    bar.locator(".bulk-exit").tap()                  # the bar holds the strip: its ✕ leaves
    expect(bar).to_be_hidden()
    picked = int(_col(page, "standby").locator(".trow").first.get_attribute("data-id"))
    current = _get(base, f"/api/tasks/{picked}")["owner"]
    _walk_drawer_owner(page, base, picked, "p1" if current == "p2" else "p2")
    assert_min_target(page.locator("#taskDrawer select[data-field='owner']"))
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-05-board-15-phone.png")



def _phone_journal(page: Page, base: str, shots: Path) -> None:
    """#journal deep-links the journal; its rows and head fit the width."""
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
