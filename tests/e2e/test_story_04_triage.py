"""Story 04 — Monday triage (Step 4/13, issue #5).

    Board filtered status:todo → a row's ⋯ → Move… → Pick a date… opens
    the date picker and the pick lands → the activity log shows old → new with
    time → open a drawer → add a comment containing a link → the link is a
    clickable chip → the + opens the quick-add dialog (#80) → "renew passport
    next friday" → the parsed date shows as a chip → create → file it under a
    project with the drawer's Move to → the breadcrumb appears (the Table and
    its Tree, where this story used to run, were removed in #350).

Walks the story against the **seeded** disposable instance (conftest
``seeded_webapp`` over ``tests/fixtures/seed.py`` — synthetic data, the only
dataset allowed on screen) at 1440×900 desktop, saving the numbered proof
shots the validation record links to:

    docs/screenshots/story-04-triage-{1..8}-desktop.png
    docs/screenshots/story-04-triage-11-desktop.png   (stale window, #101)

then — in the same test function since #96 — the drawer at 390×844 (WebKit,
touch) with the geometry checks:

    docs/screenshots/story-04-triage-9-phone.png   (the Board's rows)
    docs/screenshots/story-04-triage-10-phone.png  (drawer as a full-screen sheet)

UX round 3 (issue #46): the filter state is ONE state shared by every tab and
lives in the URL (``?status=todo`` is the same view on the Board and
Today), so a shared URL no longer moves the tab by itself — the story opens
the Board explicitly.

**Story 13 — start date + snooze (#87)** rides in this file too, as
``_walk_starts_and_snooze`` at the end of the desktop leg plus the phone
assertions in the phone leg. It is a story of its own in
``docs/validation.md``, not a new test: the e2e suite is capped at 15 tests
(CLAUDE.md) and already held 14, and this story walks the same surface —
the filter sheet, the quick-add dialog, a Today row, the drawer. Its shots:

    docs/screenshots/story-13-starts-snooze-{1,2,4,5}-desktop.png
    docs/screenshots/story-13-starts-snooze-{6,7}-phone.png

**Story 30 — Today's split view (#336)** rides here as ``_walk_today_split``
right after the stale-window walk, on the same Today surface: the list in the left
half, the detail pane in the right (empty state until a task opens). Its shots:

    docs/screenshots/story-30-today-split-{1,2,3}-desktop.png

**Story 25 — repeat every N (#229)** rides here too, as
``_walk_recurrence_interval`` right after the story-17 anchor walk it extends
(the same drawer, the same seeded task) plus a phone assertion. Its shots:

    docs/screenshots/story-25-recurrence-interval-1-desktop.png
    docs/screenshots/story-25-recurrence-interval-2-phone.png

**Story 29 — act on a row from its menu (#311)** rides inside
``_walk_starts_and_snooze`` (step 4b): the same Today row, snoozed from its ⋯
kebab (the row has no clock any more) and read in full, through the shared
action runner. Its shots:

    docs/screenshots/story-29-row-actions-{1,2}-desktop.png
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    assert_date_sheet,
    close_filter_sheet,
    dismiss_toasts,
    filter_button,
    open_filter_sheet,
    open_more_fields,
    shot,
    text_contrast,
)

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
LINK = "https://example.com/passport-office"


def _next_friday(today: date) -> date:
    coming = today + timedelta(days=(4 - today.weekday()) % 7)
    return coming + timedelta(days=7)


def _trow(page: Page, title: str, scope: str = ""):
    """The ONE shared task row (rows.js) by exact title, optionally inside ``scope``
    (the seed has both "Renew passports" and the story's "renew passport")."""
    return page.locator(f"{scope} .trow".strip(), has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


# A sideways touch on a row, as synthetic Pointer Events (swipe.js, #311): it
# proves the wiring — which action a side runs — not the feel of the gesture,
# which is the owner's iPhone walk (story 29).
_SWIPE = """(el, [x0, x1]) => {
  const r = el.getBoundingClientRect();
  const y = r.top + r.height / 2;
  const fire = (type, x) => el.dispatchEvent(new PointerEvent(type, {
    pointerId: 7, pointerType: 'touch', isPrimary: true, bubbles: true, clientX: x, clientY: y }));
  fire('pointerdown', x0);
  for (let i = 1; i <= 8; i++) fire('pointermove', x0 + (x1 - x0) * i / 8);
  fire('pointerup', x1);
}"""

# A native date picker is an OS widget no browser automation can see or drive,
# so `showPicker()` is recorded instead: the call is what "the picker opened"
# means from the page's side, and the `change` the test then dispatches on the
# same input is what the user picking a day produces (#107).
_RECORD_SHOW_PICKER = """
window.__pickerOpens = [];
HTMLInputElement.prototype.showPicker = function () { window.__pickerOpens.push(this.className); };
"""


# ----------------------------------------------------------- desktop leg

def test_desktop_triage(seeded_webapp: str, browser: Browser, playwright: Playwright, shots: Path) -> None:
    """The desktop walk, then the phone leg on the same instance.

    One collected test, not two: the phone leg was its own test function until
    #96's calendar story needed a slot under the e2e budget (CLAUDE.md), so it
    is folded in here, the way story 05's was for Step 12 — same steps, same
    order, same shots.
    """
    base = seeded_webapp
    context = browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        page = context.new_page()
        page.add_init_script(_RECORD_SHOW_PICKER)

        # 1. The Board filtered status:todo — via the URL, the shareable view.
        #    The filter is shared by every tab (UX round 3), so the URL never
        #    moves the tab by itself: open the Board, the query survives the switch.
        todo = _get(base, "/api/tasks?status=todo")
        todo_count = todo["count"]
        page.goto(f"{base}/?status=todo")
        page.click("nav.tabs .tab[data-tab='board']")
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        expect(page).to_have_url(f"{base}/?status=todo")
        # the strip's filter button says what is on — its count, and its name
        # in words (#395) — so nothing needs the sheet open to read the state
        button = filter_button(page, "paneBoard")
        expect(button.locator(".filter-count")).to_have_text("1")
        expect(button).to_have_attribute("aria-label", "Filters, 1 on: todo")
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
        expect(page.locator("#paneBoard .board-col:not([hidden])")).to_have_count(1)
        rows = page.locator("#paneBoard .trow[data-id]")
        expect(rows).to_have_count(todo_count)
        shown = {int(i) for i in rows.evaluate_all("els => els.map(e => e.dataset.id)")}
        assert shown == {t["id"] for t in todo["items"]}
        quotes = _trow(page, "Get three quotes", "#paneBoard")
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-04-triage-1-desktop.png")

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
        new_row = _trow(page, "renew passport", "#paneBoard section.board-col[data-col='standby']")
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

        # 7. File it under a project from the drawer's Move to (#350: the Tree
        #    and its drag are gone; this is the one re-parent path, on every
        #    pointer) → moved, toast, breadcrumb, activity.
        family_id = next(p["id"] for p in _get(base, "/api/projects")["items"] if p["title"] == "Family admin")
        new_row.locator(".trow-main").click()
        expect(drawer).to_be_visible()
        open_more_fields(drawer)   # Move to is a rare field (#394)
        expect(drawer.locator("select[data-field='parent']")).to_have_value("")   # top level
        drawer.locator("select[data-field='parent']").select_option(str(family_id))
        expect(page.locator(".toast-success").last).to_contain_text("under Family admin")
        moved = _get(base, f"/api/tasks/{new_id}")
        assert moved["parent_id"] == family_id
        assert [c["title"] for c in moved["breadcrumb"]] == ["Family admin"]
        assert moved["activity"][0]["field"] == "parent"
        expect(drawer.locator(".drawer-crumbs .crumb")).to_have_text(["Family admin"])
        # …and the row says where it lives now (the meta line's project part)
        expect(_trow(page, "renew passport", "#paneBoard").locator(".trow-project")).to_have_text("Family admin")
        shot(page, shots / "story-04-triage-7-desktop.png")
        # a cycle is refused and surfaced as a toast, nothing changes: Home
        # renovation is offered its own child project, Kitchen, and refuses it
        projects = {p["title"]: p["id"] for p in _get(base, "/api/projects")["items"]}
        home_id = projects["Home renovation"]
        page.goto(f"{base}/#task/{home_id}")
        expect(drawer.locator("#drawerTitle")).to_have_value("Home renovation")
        open_more_fields(drawer)
        drawer.locator("select[data-field='parent']").select_option(str(projects["Kitchen"]))
        expect(page.locator(".toast-error").last).to_contain_text("cycle")
        assert _get(base, f"/api/tasks/{home_id}")["parent_id"] is None

        # 8. Deep link: a fresh load of #task/<id> opens the drawer with the breadcrumb.
        page.goto(f"{base}/#task/{new_id}")
        expect(page.locator("#taskDrawer")).to_be_visible()
        expect(page.locator("#taskDrawer .drawer-crumbs .crumb")).to_have_text(["Family admin"])
        dismiss_toasts(page)
        shot(page, shots / "story-04-triage-8-desktop.png")

        # ------------------------------- closed tasks on demand (#309) ----
        _walk_closed_on_demand(page, base)

        # ---------------------------------------------- story 13 (#87) ----
        _walk_starts_and_snooze(page, base, shots)

        # ------------------------------------------- stale window (#101) ----
        _walk_stale_window(page, base, shots)

        # ------------------------------ one task load per hash open (#236) ----
        _walk_hash_open_loads_once(page, base)

        # -------------------------------------- today split view (#336) ----
        _walk_today_split(page, base, shots)

        # --------------------------------------- recurrence anchor (#112) ----
        _walk_recurrence_anchor(page, base, shots)

        # ------------------------------------- recurrence interval (#229) ----
        _walk_recurrence_interval(page, base, shots)
    finally:
        context.close()

    # the same walk in dark, for the paired proof shots
    dark_ctx = browser.new_context(viewport=DESKTOP, color_scheme="dark")
    try:
        dark_page = dark_ctx.new_page()
        dark_page.goto(f"{base}/?status=deferred")
        dark_page.click("nav.tabs .tab[data-tab='board']")   # Today is the landing tab (#319)
        expect(dark_page.locator("#paneBoard")).to_be_visible()
        shot(dark_page, shots / "story-13-starts-snooze-5-desktop.png")
    finally:
        dark_ctx.close()

    _walk_phone_rows_and_drawer_sheet(base, playwright, shots)


# ------------------------------------------ closed tasks on demand (#309)
#
# Riding inside this test because the suite is capped (CLAUDE.md): no shots,
# the default views are unchanged, so the gallery does not move. It runs in its own context — a cold boot, an empty HTTP cache
# — so every recorded response is a 200 with a body to read.

def _flatten(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children") or []))
    return out


def _walk_closed_on_demand(page: Page, base: str) -> None:
    """The boot ships no closed tasks and no descriptions; a closed status in
    the filter is the list's to answer, never a second forest (#309, #350)."""
    ctx = page.context.browser.new_context(viewport=DESKTOP, color_scheme="light")
    try:
        p = ctx.new_page()
        seen = []
        p.on("response", lambda r: seen.append(r) if "/api/" in r.url else None)

        def calls(path: str) -> list:
            return [r for r in seen if urlsplit(r.url).path == path]

        def query(r) -> dict:
            return parse_qs(urlsplit(r.url).query)

        # 1. The cold boot: open forest, slim list, the project list.
        p.goto(f"{base}/")
        # the header names Today's exceptions, never a bare open count (#393)
        expect(p.locator("#homeHeadStatus")).to_have_text(re.compile(r"^\d+ overdue · \d+ due today$"))
        trees = calls("/api/tasks/tree")
        assert trees, "the boot read no forest"
        for r in trees:
            assert query(r).get("descriptions") == ["false"] and "include_closed" not in query(r), r.url
            nodes = _flatten(r.json()["items"])
            assert nodes and all("description" not in n for n in nodes)
            assert not [n for n in nodes if n["status"] in ("done", "cancelled") and not n["children"]],                 "the boot forest carries a closed leaf"
        lists = calls("/api/tasks")
        assert lists, "the boot read no list"
        for r in lists:
            assert query(r).get("descriptions") == ["false"], r.url
            assert all("description" not in t for t in r.json()["items"])
        assert calls("/api/projects"), "the boot did not read the project list"
        # the closed tasks are still there for whoever asks: the default shape
        assert any(t["status"] == "done" for t in _get(base, "/api/tasks?include_closed=true")["items"])

        # 2. A closed status in the filter: the Board shows the closed task off
        #    the filtered list, and nothing ever reads the closed forest.
        p.click("nav.tabs .tab[data-tab='board']")
        expect(_trow(p, "Buy a birthday gift", "#paneBoard")).to_have_count(0)
        open_filter_sheet(p, "paneBoard").locator(".filter-checks[data-name='status'] input[value='done']").check()
        close_filter_sheet(p)
        expect(_trow(p, "Buy a birthday gift", "#paneBoard")).to_be_visible()
        assert [r.url for r in calls("/api/tasks/tree") if "include_closed" in query(r)] == []
    finally:
        ctx.close()


# ------------------------------------------- recurrence anchor (#112)
#
# Riding inside this test for the same reason stories 13–15 do: the suite is
# capped at 15 tests and this walks the drawer the triage story already has
# open. The file's seeded instance also serves the phone leg below, so the walk
# puts the task back the way it found it before returning.


def _walk_recurrence_anchor(page: Page, base: str, shots: Path) -> None:
    """#112 — Repeat is a cadence *and* the fixed day it lands on.

    The seed's "Weekly review" repeats every Friday. The drawer shows both
    selects; completing it from the status select rolls the due to a Friday
    rather than one flat week on, and switching the cadence to one that
    cannot carry a weekday clears the anchor rather than keeping a stale day.

    Screenshot: docs/screenshots/story-17-recurrence-anchor-1-desktop.png
    """
    review = page.request.get(f"{base}/api/tasks?q=Weekly review").json()["items"][0]
    page.goto(f"{base}/#task/{review['id']}")
    open_more_fields(page.locator("#taskDrawer"))   # Repeat is a rare field (#394)
    cadence = page.locator("#taskDrawer select[data-field='recurrence']")
    anchor = page.locator("#taskDrawer select[data-field='recurrence_anchor']")
    expect(cadence).to_have_value("weekly")
    expect(anchor).to_have_value("fri")
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    shot(page, shots / "story-17-recurrence-anchor-1-desktop.png")

    # Complete it: the same task stays open and its new due is a Friday,
    # strictly after both the due it had and today.
    old_due = date.fromisoformat(review["due"])
    page.locator("#taskDrawer select[data-field='status']").select_option("complete")
    expect(page.locator("#taskDrawer input[data-field='due']")).not_to_have_value(review["due"])
    rolled = date.fromisoformat(
        page.locator("#taskDrawer input[data-field='due']").input_value()
    )
    assert rolled.weekday() == 4, f"rolled to {rolled} ({rolled:%A}), expected a Friday"
    assert rolled > old_due and rolled > E2E_ANCHOR

    # A cadence that takes no fixed day drops the anchor — and the picker with
    # it. The picker vanishing is the re-render signal: the drawer only redraws
    # once the PATCH has come back, so the stored value is safe to read here.
    cadence.select_option("quarterly")
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
    open_more_fields(drawer)
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
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    shot(page, shots / "story-25-recurrence-interval-1-desktop.png")

    old_due = date.fromisoformat(review["due"])
    assert old_due.weekday() == 5, f"the seed's review is due {old_due:%A}, the walk expects a Saturday"
    page.locator("#taskDrawer select[data-field='status']").select_option("complete")
    expect(page.locator("#taskDrawer input[data-field='due']")).not_to_have_value(review["due"])
    rolled = date.fromisoformat(page.locator("#taskDrawer input[data-field='due']").input_value())
    assert rolled == old_due + timedelta(weeks=7), f"rolled to {rolled}, expected 7 weeks after {old_due}"
    assert page.request.get(task_url).json()["recurrence_interval"] == 7

    page.request.patch(task_url, data={
        "recurrence": "weekly", "recurrence_anchor": "fri", "recurrence_interval": None,
        "due": review["due"],
    })


# ------------------------------------------------- stale window (#101)


def _walk_stale_window(page: Page, base: str, shots: Path) -> None:
    """#101 — the modified select's inverse windows: *untouched > N days*.
    The seed's dormant task (last touched 45 days back) is the one hit at 30
    days and gone at 60; the URL keeps the window token while the API only
    ever sees the plain date the client computed.

    Screenshot: docs/screenshots/story-04-triage-11-desktop.png
    """
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='board']")
    open_filter_sheet(page, "paneBoard").locator("select[name='updated']").select_option("stale30")
    expect(page).to_have_url(f"{base}/?updated=stale30")
    close_filter_sheet(page)
    rows = page.locator("#paneBoard .trow[data-id]")
    expect(rows).to_have_count(1)
    expect(rows.locator(".trow-title")).to_have_text("Sort the garage shelves")
    expect(filter_button(page, "paneBoard")).to_have_attribute("aria-label", "Filters, 1 on: untouched > 30 days")
    expect(page.locator("#boardFilterText .filter-q")).to_have_attribute("placeholder", "Filter 1 task…")
    shot(page, shots / "story-04-triage-11-desktop.png")
    # the token round-trips: a fresh load of the shared URL is the same view
    page.goto(f"{base}/?updated=stale30")
    page.click("nav.tabs .tab[data-tab='board']")
    expect(rows).to_have_count(1)
    # 60 days back nothing is that old — an honest empty list, not an error
    open_filter_sheet(page, "paneBoard").locator("select[name='updated']").select_option("stale60")
    close_filter_sheet(page)
    expect(rows).to_have_count(0)


# ------------------------------------- one task load per hash open (#236)
#
# Riding here because the suite is capped (CLAUDE.md): no shots. This used to
# close the plan-my-day walk (story 15, removed in #369), which is where the
# race was found, so the check outlived the feature.


def _walk_hash_open_loads_once(page: Page, base: str) -> None:
    """One hash navigation, one load (#236): it fires `popstate` and
    `hashchange`, and while both opened the drawer the slower of the two
    loads — read before an edit — could paint over the edit's own refresh,
    leaving the label on "Starts · in 7d" for a task the server had already
    cleared (1 run in 8, and the rest of the gallery drifted after it)."""
    # Today is the landing tab and the last tab is remembered, so leave the app
    # where the next walk (Today's split view) expects to find it
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    lib_id = int(_get(base, "/api/tasks?q=Return%20library%20books")["items"][0]["id"])
    page.request.patch(f"{base}/api/tasks/{lib_id}", data={"starts": "next week"})
    loads: list[str] = []
    task_path = f"/api/tasks/{lib_id}"

    def on_request(r) -> None:  # noqa: ANN001 — a Playwright Request
        if r.method == "GET" and r.url.endswith(task_path):
            loads.append(r.url)

    page.on("request", on_request)
    page.goto(f"{base}/#task/{lib_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    page.remove_listener("request", on_request)
    assert len(loads) == 1, f"one hash navigation loaded the task {len(loads)} times"
    open_more_fields(drawer)   # Starts is a rare field (#394)
    starts_input = drawer.locator(".field-starts input[data-field='starts']")
    starts_input.fill("")
    starts_input.blur()
    # The field's own label is the *re-render* signal: `dateField` appends
    # " · <caption>" only while the field has a value, so a bare "Starts"
    # means the PATCH came back and the drawer redrew from the response.
    # Asserting on the input alone would pass on the local edit and let the
    # API read below race the write.
    expect(drawer.locator(".field-starts .field-label")).to_have_text("Starts")
    assert _get(base, f"/api/tasks/{lib_id}")["starts"] is None


# ------------------------------------------- story 30 — Today split (#336)

def _walk_today_split(page: Page, base: str, shots: Path) -> None:
    """Today at 1440: the list takes the left half, the detail pane the right.

    The right half is never empty while a task is due (#393, decision 8 of
    #390): a cold load opens the first due task there by itself, with no hash
    written, and the row keymap keeps working beside it. Closing it shows the
    empty state, and the list keeps its half width, so a row's ⋯ stays near its
    title. Opening a task fills that same right half (no overlay), the
    ``#task/<id>`` link works on a cold load. Other tabs keep the 440px panel,
    and the task Today opened by itself does not follow you there.

    Screenshots: docs/screenshots/story-30-today-split-{1,2,3}-desktop.png
    """
    page.goto(f"{base}/")
    pane = page.locator("#paneToday")
    drawer = page.locator("#taskDrawer")
    empty = page.locator("#todayDetailEmpty")
    first = pane.locator("section.today .trow[data-id]").first
    expect(first).to_be_visible()

    # 1. The first due task fills the right half on its own; the URL is still bare.
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(drawer.locator("#drawerTitle")).to_have_value(first.locator(".trow-title").inner_text())
    expect(page).to_have_url(f"{base}/")
    list_box, drawer_box = pane.bounding_box(), drawer.bounding_box()
    assert list_box and drawer_box
    assert list_box["x"] + list_box["width"] <= drawer_box["x"] + 1, (list_box, drawer_box)
    assert 0.35 * DESKTOP["width"] <= list_box["width"] <= 0.6 * DESKTOP["width"], list_box
    assert 0.35 * DESKTOP["width"] <= drawer_box["width"] <= 0.6 * DESKTOP["width"], drawer_box
    kebab = pane.locator(".today-group .trow-kebab").first.bounding_box()
    assert kebab and kebab["x"] + kebab["width"] <= drawer_box["x"], "the ⋯ must sit inside the list half"
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-30-today-split-1-desktop.png")
    # the keymap stays on beside it: a focused row still takes a key
    first.locator(".trow-main").focus()
    page.keyboard.press("?")
    expect(page.locator("#keysHelp")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#keysHelp")).to_be_hidden()
    expect(drawer).to_be_visible()

    # 2. Closed, the empty state holds the right half; ⋯ → Open details fills
    #    it again, and the menu opens whole, inside the window.
    drawer.locator(".drawer-close").click()
    expect(drawer).to_be_hidden()
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("Select a task to see its details")
    empty_box = empty.bounding_box()
    assert empty_box and abs(empty_box["x"] - drawer_box["x"]) <= 1, (empty_box, drawer_box)
    row = pane.locator(".today-group .trow").first
    task_id = int(row.get_attribute("data-id"))
    row.locator(".trow-kebab").click()
    menu = page.locator(".row-menu")
    expect(menu).to_be_visible()
    menu_box = menu.bounding_box()
    assert menu_box and menu_box["x"] >= 0 and menu_box["x"] + menu_box["width"] <= DESKTOP["width"], menu_box
    assert menu_box["y"] >= 0 and menu_box["y"] + menu_box["height"] <= DESKTOP["height"], menu_box
    menu.locator("[data-action='open']").click()
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(page).to_have_url(f"{base}/#task/{task_id}")
    drawer_box, list_box = drawer.bounding_box(), pane.bounding_box()
    assert drawer_box and list_box
    assert abs(drawer_box["x"] - empty_box["x"]) <= 1 and abs(drawer_box["width"] - empty_box["width"]) <= 1, (
        drawer_box, empty_box)
    assert list_box["x"] + list_box["width"] <= drawer_box["x"] + 1, (list_box, drawer_box)
    assert_no_horizontal_overflow(page)
    shot(page, shots / "story-30-today-split-2-desktop.png")

    # 3. The cold deep link opens its own task on Today (the landing tab),
    #    not the first due one, without an overlay.
    drawer.locator(".drawer-close").click()
    expect(drawer).to_be_hidden()
    last_id = int(pane.locator("section.today .trow[data-id]").last.get_attribute("data-id"))
    page.goto(f"{base}/#task/{last_id}")
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(drawer.locator("#drawerTitle")).to_have_value(
        pane.locator(f"section.today .trow[data-id='{last_id}'] .trow-title").inner_text())
    expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "today")
    shot(page, shots / "story-30-today-split-3-desktop.png")

    # 4. The other tabs keep the 440px panel for a task you opened and show no
    #    empty pane; back on Today with nothing open, the first due task again.
    page.click("nav.tabs .tab[data-tab='board']")
    box = drawer.bounding_box()
    assert box and 400 <= box["width"] <= 480, box
    drawer.locator(".drawer-close").click()
    expect(empty).to_be_hidden()
    page.click("nav.tabs .tab[data-tab='today']")
    expect(drawer).to_be_visible()
    expect(empty).to_be_hidden()
    expect(page).to_have_url(f"{base}/")
    # 5. …and the task Today opened by itself stays on Today.
    page.click("nav.tabs .tab[data-tab='board']")
    expect(drawer).to_be_hidden()
    page.click("nav.tabs .tab[data-tab='today']")
    expect(drawer).to_be_visible()


# ---------------------------------------------- story 13 — starts + snooze
#
# Rides inside this file rather than becoming a 15th test: the e2e suite is
# capped at 15 (CLAUDE.md) and sat at 14, and this story is a continuation of
# the same triage surface — the filter card, a Today row, the quick-add dialog.


def _walk_starts_and_snooze(page: Page, base: str, shots: Path) -> None:
    """A task created asleep stays out of the working views until its day, is
    findable under *Deferred*, and a Today row can be pushed away and undone.

    Screenshots: docs/screenshots/story-13-starts-snooze-{1,2,4,5}-desktop.png
    """
    today = E2E_ANCHOR
    starts = (today + timedelta(days=30)).isoformat()
    due = (today + timedelta(days=60)).isoformat()

    # 1. Quick-add both dates off one line — the parser fills two correctable
    #    fields, so nothing about the task is a mystery before it exists.
    page.goto(f"{base}/")
    page.click("nav.tabs .tab[data-tab='today']")
    page.locator("#paneToday .quick-add-btn").click()
    quick_add = page.locator("#quickAdd")
    expect(quick_add).to_be_visible()
    quick_add.locator(".quick-add-input").fill("renew insurance due in 60 days starts in 30 days")
    expect(quick_add.locator(".quick-add-due")).to_have_value(due)
    expect(quick_add.locator(".quick-add-starts")).to_have_value(starts)
    quick_add.locator(".quick-add-status").select_option("todo")
    shot(page, shots / "story-13-starts-snooze-1-desktop.png")
    quick_add.locator(".quick-add-input").press("Enter")
    expect(quick_add).to_be_hidden()
    expect(page.locator(".toast-success").last).to_contain_text("renew insurance")

    created = next(t for t in _get(base, "/api/tasks?status=deferred")["items"]
                   if t["title"] == "renew insurance")
    assert (created["due"], created["starts"]) == (due, starts)

    # 2. It is nowhere in the working views — Today, the Board.
    expect(_trow(page, "renew insurance", "#paneToday")).to_have_count(0)
    page.click("nav.tabs .tab[data-tab='board']")
    expect(page.locator("#paneBoard")).to_be_visible()
    expect(page.locator("#paneBoard").get_by_text("renew insurance", exact=True)).to_have_count(0)

    # 3. Deferred is a visible state, not an absence: the status ticks'
    #    pseudo-value lists exactly the sleeping tasks, each wearing the marker
    #    that says why the working views are quiet about it, and the state is
    #    the URL.
    open_filter_sheet(page, "paneBoard").locator(".filter-checks[data-name='status'] input[value='deferred']").check()
    expect(page).to_have_url(f"{base}/?status=deferred")
    close_filter_sheet(page)
    expect(filter_button(page, "paneBoard")).to_have_attribute("aria-label", "Filters, 1 on: deferred")
    rows = page.locator("#paneBoard .trow[data-id]")
    # the seed's own deferred task plus the one just created — and nothing else
    expect(rows).to_have_count(2)
    titles = rows.locator(".trow-title").all_inner_texts()
    assert sorted(titles) == ["Book boiler service", "renew insurance"], titles
    expect(rows.locator(".trow-starts")).to_have_count(2)
    # #392: a neutral exception chip — the clock says "snoozed until", the day follows
    snoozed = _trow(page, "renew insurance", "#paneBoard").locator(".trow-starts")
    expect(snoozed).to_have_text(re.compile(r"^\d+ \w{3}$"))
    expect(snoozed).to_have_attribute("data-tone", "neutral")
    expect(snoozed).to_have_attribute("title", re.compile(r"^Snoozed until \w{3} \d+ \w{3}$"))
    dismiss_toasts(page)
    shot(page, shots / "story-13-starts-snooze-2-desktop.png")
    open_filter_sheet(page, "paneBoard").locator(".filter-clear").click()
    close_filter_sheet(page)
    expect(page).to_have_url(f"{base}/")

    # 4. Snooze from a Today row's menu: pick an option, the task leaves, the
    #    toast names the day it went to — and Undo puts it straight back.
    page.click("nav.tabs .tab[data-tab='today']")
    row = _trow(page, "School enrolment forms", "#paneToday")
    expect(row).to_be_visible()
    task_id = int(row.get_attribute("data-id"))
    # The completion circle is an .icon-button over the vendored action-row (project-scaffolding#339);
    # it keeps its own success tone, pressed and on hover, over their attention / ink.
    done = row.locator(".trow-done")
    want = page.evaluate("""() => { const p = document.createElement('i'); p.style.color = 'var(--success)';
      document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; }""")
    done.hover()
    assert done.evaluate("el => getComputedStyle(el).color") == want
    page.mouse.move(0, 0)
    pressed = done.evaluate("""el => { el.setAttribute('aria-pressed', 'true'); const c = getComputedStyle(el).color;
      el.setAttribute('aria-pressed', 'false'); return c; }""")
    assert pressed == want
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None
    row.locator(".trow-kebab").click()
    page.locator(".row-menu [data-action='snooze']").click()
    menu = page.locator(".snooze-pop .snooze-menu")
    expect(menu).to_be_visible()
    expect(menu.locator(".snooze-opt")).to_have_count(4)   # 3 phrases + pick a date
    shot(page, shots / "story-13-starts-snooze-4-desktop.png")
    menu.get_by_text("Next week", exact=True).click()

    next_week = (today + timedelta(days=7)).isoformat()
    toast = page.locator(".toast-success").last
    expect(toast).to_contain_text("Snoozed to")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] == next_week
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_have_count(0)
    # the change is in the log like any other field change
    assert "starts" in [a["field"] for a in _get(base, f"/api/tasks/{task_id}")["activity"]]

    toast.locator(".toast-action").click()
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_be_visible()
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None

    # 4b. Story 29 (#311): the row's ⋯ menu, read in full. The kebab lists the
    #     row's actions — the shared table's, offered only where they apply,
    #     then the task's own links — and its Snooze… opens the date picker,
    #     commits through the same runner (toast + Undo), and the keyboard
    #     reaches the menu with `.`.
    row = _trow(page, "School enrolment forms", "#paneToday")
    kebab = row.locator(".trow-kebab")
    expect(kebab).to_have_attribute("aria-haspopup", "menu")
    dismiss_toasts(page)
    kebab.click()
    menu = page.locator(".row-menu")
    expect(menu).to_be_visible()
    expect(kebab).to_have_attribute("aria-expanded", "true")
    actions = menu.locator(".row-menu-item").evaluate_all("els => els.map(e => e.dataset.action)")
    assert actions[:3] == ["complete", "change-date", "snooze"], actions
    assert "reopen" not in actions and "status-todo" not in actions   # open task, already todo
    assert actions[-1] == "open"
    expect(menu.locator(".row-menu-item").first).to_be_focused()
    shot(page, shots / "story-29-row-actions-1-desktop.png")
    menu.locator("[data-action='snooze']").click()
    expect(menu).to_be_hidden()
    picker = page.locator(".snooze-pop .snooze-menu")
    expect(picker).to_be_visible()
    picker.get_by_text("Tomorrow", exact=True).click()
    tomorrow = (today + timedelta(days=1)).isoformat()
    toast = page.locator(".toast-success").last
    expect(toast).to_contain_text("Snoozed to")
    expect(toast.locator(".toast-action")).to_have_text("Undo (Z)")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] == tomorrow
    toast.locator(".toast-action").click()
    expect(_trow(page, "School enrolment forms", "#paneToday")).to_be_visible()
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None
    # `.` on a focused row opens its menu; Escape closes it, focus back on the kebab
    _trow(page, "School enrolment forms", "#paneToday").locator(".trow-main").focus()
    page.keyboard.press(".")
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(_trow(page, "School enrolment forms", "#paneToday").locator(".trow-kebab")).to_be_focused()
    dismiss_toasts(page)

    # 4c. Story 29 (#311): Settings → Row actions sets, on this device, what a
    #     swipe runs and what the menu lists. Swipe left → Snooze…, Cycle
    #     priority out of the menu, Snooze… moved to the top: the row's menu
    #     follows, a swipe left opens the snooze picker, and the action a
    #     swipe runs cannot be taken out of the menu (WCAG 2.5.1). Reset puts
    #     the plan's defaults back.
    page.click("#settingsBtn")
    card = page.locator("#rowActionsCard")
    card.locator("summary").click()
    meta = page.locator("#rowActionsMeta")
    expect(meta).to_have_text("Default")
    page.select_option("#swipeLeftSelect", "snooze")
    lst = page.locator("#rowMenuList")
    expect(lst.locator("[data-action='snooze'] .row-actions-tick")).to_have_attribute("aria-pressed", "true")
    expect(lst.locator("[data-action='snooze'] .row-actions-tick")).to_be_disabled()
    expect(lst.locator("[data-action='snooze'] .row-actions-hint")).to_have_text("used by swipe left")
    lst.locator("[data-action='priority'] .row-actions-tick").click()
    expect(lst.locator("[data-action='priority'] .row-actions-tick")).to_have_attribute("aria-pressed", "false")
    # every control on the card is a real 44px target (the design review's TOUCH-01)
    assert_min_target(lst.locator(".row-actions-tick, .row-actions-move"))
    # …and their glyphs sit on the icons.size inline step (the design review's COMP-02)
    sizes = lst.locator(".row-actions-tick svg, .row-actions-move svg").evaluate_all(
        "els => els.map(e => Math.round(e.getBoundingClientRect().width))")
    assert set(sizes) == {16}, sizes
    for _ in range(3):                                   # 4th in the default list → 1st
        lst.locator("[data-action='snooze'] [data-move='up']").click()
    expect(lst.locator(".row-actions-item").first).to_have_attribute("data-action", "snooze")
    expect(lst.locator("[data-action='snooze'] [data-move='up']")).to_be_disabled()
    expect(meta).to_have_text("Custom")
    stored = page.evaluate("JSON.parse(localStorage.getItem('task-os.rowactions'))")
    assert stored["left"] == "snooze" and stored["menu"][0] == "snooze" and "priority" not in stored["menu"], stored
    card.scroll_into_view_if_needed()
    shot(page, shots / "story-29-row-actions-2-desktop.png")
    page.click("nav.tabs .tab[data-tab='today']")
    row = _trow(page, "School enrolment forms", "#paneToday")
    row.locator(".trow-kebab").click()
    actions = page.locator(".row-menu .row-menu-item").evaluate_all("els => els.map(e => e.dataset.action)")
    assert actions[0] == "snooze" and "priority" not in actions, actions
    page.keyboard.press("Escape")
    expect(page.locator(".row-menu")).to_have_count(0)
    row.locator(".trow-main").evaluate(_SWIPE, [900, 300])          # synthetic touch: the wiring
    picker = page.locator(".snooze-pop .snooze-menu")
    expect(picker).to_have_attribute("data-field", "starts")
    page.keyboard.press("Escape")
    expect(picker).to_have_count(0)
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None    # a cancelled pick writes nothing
    page.click("#settingsBtn")
    page.click("#rowActionsReset")
    expect(meta).to_have_text("Default")
    assert page.evaluate("localStorage.getItem('task-os.rowactions')") is None
    page.click("nav.tabs .tab[data-tab='today']")

    # 5. The drawer edits Starts with Due's control, one behaviour; Starts
    #    sits under More fields since #394.
    page.goto(f"{base}/#task/{task_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    open_more_fields(drawer)
    starts_input = drawer.locator(".field-starts input[data-field='starts']")
    expect(starts_input).to_be_visible()
    expect(drawer.locator(".field-due input[data-field='due']")).to_be_visible()
    starts_input.fill("in 3 days")
    starts_input.blur()
    expect(starts_input).to_have_value((today + timedelta(days=3)).isoformat())
    assert _get(base, f"/api/tasks/{task_id}")["starts"] == (today + timedelta(days=3)).isoformat()
    assert_no_horizontal_overflow(page)

    # Put the seeded task back the way this walk found it: `seeded_webapp` is
    # shared with the phone leg below, so a task left asleep here would vanish
    # from its Today.
    starts_input.fill("")
    starts_input.blur()
    expect(starts_input).to_have_value("")
    assert _get(base, f"/api/tasks/{task_id}")["starts"] is None


# ------------------------------------------------------------- phone leg

def _walk_phone_rows_and_drawer_sheet(base: str, playwright: Playwright, shots: Path) -> None:
    """390-wide WebKit (iOS-class): the Board's Todo column as the shared rows,
    drawer full-screen, 44px targets (the row's completion circle and ⋯ kebab are
    each a full 44x44 box either side of the open target, #311)."""
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
        page.goto(f"{base}/?status=todo")
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        expect(page.locator("nav.tabs .tab.active")).to_have_attribute("data-tab", "board")
        rows = page.locator("#paneBoard .trow[data-id]")
        expect(rows).to_have_count(_get(base, "/api/tasks?status=todo")["count"])
        # the ONE shared row (circle + title, the one passive meta line with the
        # project in it, the ⋯ menu — no status select on the row since #311)
        watering = _trow(page, "Fix watering schedule drift", "#paneBoard")
        expect(watering.locator(".trow-project")).to_have_text("Side project: garden-bot")
        expect(watering.locator(".trow-due")).to_be_visible()
        expect(watering).to_have_attribute("data-status", "todo")
        expect(rows.locator(".trow-status")).to_have_count(0)
        assert_no_horizontal_overflow(page)
        # the top strip (#80, #395): the text filter, the filter button, the
        # Select toggle and the + sit side by side on one line, all at the
        # touch floor, with effective rectangles that never overlap; pressed,
        # the toggle says its name in accent-text on the accent tint, 4.5:1
        # (WCAG 1.4.3): a word, not a glyph's 3:1 (#339)
        strip = page.locator("#paneBoard .filter-q, #paneBoard .filter-open, #paneBoard [data-select-toggle], #paneBoard .quick-add-btn")
        tops = strip.evaluate_all("els => els.map(e => Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2))")
        assert max(tops) - min(tops) <= 2, tops                         # one line
        assert_min_target(strip)
        assert_no_overlap(strip)
        page.locator("#paneBoard [data-select-toggle]").tap()
        pressed = page.locator("#paneBoard [data-select-toggle][aria-pressed='true'] .strip-label")
        expect(pressed).to_be_visible()
        assert text_contrast(pressed) >= 4.5, text_contrast(pressed)
        page.locator("#paneBoard [data-select-toggle]").tap()
        expect(page.locator("#paneBoard [data-select-toggle]")).to_have_attribute("aria-pressed", "false")
        page.locator("#paneBoard .quick-add-btn").tap()
        expect(page.locator("#quickAdd")).to_be_visible()
        assert_min_target(page.locator("#quickAdd .quick-add-input"))
        page.keyboard.press("Escape")
        expect(page.locator("#quickAdd")).to_be_hidden()
        # rows are >=44px tall; a touch screen draws no completion circle
        # (#350: a swipe right or the drawer's status closes a task), so the
        # row's one control is the ⋯ kebab, a real 44x44 box that never
        # overlaps the open target (#311)
        assert_min_target(rows)
        expect(rows.locator(".trow-done").first).to_be_hidden()
        assert_min_target(rows.locator(".trow-kebab"))
        assert_no_overlap(rows.locator(".trow-main, .trow-kebab"))
        sizes = rows.locator(".trow-kebab").evaluate_all(
            "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })")
        assert sizes and all(w == 44 and h == 44 for w, h in sizes), sizes
        # #74 round 2, #392: nothing on the meta line makes a card taller. An
        # exception chip sits on the one meta line like every other part, so a
        # row that wears one is exactly as tall as a plain one; the folder
        # glyph that used to be the case here left the row for its menu.
        by_flag = rows.evaluate_all(
            "els => els.map(e => [!!e.querySelector('.trow-flag'),"
            " Math.round(e.getBoundingClientRect().height)])")
        assert any(f for f, _ in by_flag) and any(not f for f, _ in by_flag), by_flag
        # (the list's first row has no hairline above it, so it is 1px shorter:
        # the claim is that a chip row is no taller than a plain one)
        plain_h = {h for f, h in by_flag if not f}
        assert {h for f, h in by_flag if f} <= plain_h, by_flag
        # #311: the row is title-over-meta · kebab, level with each other, no
        # taller than 60px (+ the hairline) with its meta line, the kebab at
        # the row's right edge
        main_box = watering.locator(".trow-main").bounding_box()
        kebab_box = watering.locator(".trow-kebab").bounding_box()
        row_box = watering.bounding_box()
        assert main_box and kebab_box and row_box
        assert row_box["height"] <= 61, row_box
        row_mid = row_box["y"] + row_box["height"] / 2
        assert abs((kebab_box["y"] + kebab_box["height"] / 2) - row_mid) <= 8, (kebab_box, row_box)
        assert main_box["x"] + main_box["width"] <= kebab_box["x"] + 1, (main_box, kebab_box)
        assert abs((kebab_box["x"] + kebab_box["width"]) - (row_box["x"] + row_box["width"])) <= 8, (kebab_box, row_box)
        shot(page, shots / "story-04-triage-9-phone.png")
        # (after the shot: the pill hides while a dialog is up, and a capture
        # right after one closes can catch the frosted bar mid-repaint)
        # the filter sheet (#395): every filter and the sort in one place, sort
        # first; status holds the five statuses + `deferred` (#87) + `blocked`
        # (#100), the pseudo-values that show the sleeping and the locked tasks
        # the working views leave out, the URL's one ticked; on the phone the
        # ticks sit two per line, every one a 44px target, none overlapping
        sheet = open_filter_sheet(page, "paneBoard")
        names = sheet.locator(".filter-sheet-row").evaluate_all("els => els.map(e => e.dataset.name)")
        assert names == ["sort", "status", "project", "person", "due", "updated"], names
        status = sheet.locator(".filter-checks[data-name='status']")
        expect(status.locator("input[name='status']")).to_have_count(7)
        expect(status.locator("input[name='status'][value='deferred']")).to_have_count(1)
        expect(status.locator("input[name='status'][value='blocked']")).to_have_count(1)
        expect(status.locator("input[name='status'][value='todo']")).to_be_checked()
        ticks = sheet.locator(".filter-check")
        assert_min_target(ticks)
        assert_no_overlap(ticks)
        lefts = sorted(set(status.locator(".filter-check").evaluate_all(
            "els => els.map(e => Math.round(e.getBoundingClientRect().x))")))
        assert len(lefts) == 2, lefts                                   # two columns
        assert_min_target(sheet.locator(".filter-select, .detail-close, .filter-done"))
        # a sheet that outgrows the phone scrolls: its footer ends the sheet
        # rather than riding pinned over the last rows, where it overlapped a
        # select's tap area (TOUCH-02, the live walk after #404 — the seed's
        # sheet fits, so the cause is asserted, not the overlap)
        assert sheet.locator(".filter-actions").evaluate("el => getComputedStyle(el).position") == "static"
        assert_no_overlap(sheet.locator(".filter-select, .filter-check, .filter-done"))
        close_filter_sheet(page)

        # the drawer is a full-screen sheet; the pill is hidden while it is up
        _trow(page, "Get three quotes", "#paneBoard").locator(".trow-main").tap()
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        box = drawer.bounding_box()
        assert box and box["width"] >= PHONE["width"] - 1 and box["height"] >= PHONE["height"] - 1, box
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "hidden"
        assert_min_target(drawer.locator(".drawer-close"))
        assert_min_target(drawer.locator(".field-control:visible"))
        assert_min_target(drawer.locator(".comment-send"))
        # the quick moves are two by two on the phone, each a whole target (#394)
        assert_min_target(drawer.locator(".quick-move"))
        assert_no_overlap(drawer.locator(".quick-move"))
        # UX round 2 (#32): the composer keeps the Ctrl+Enter hint; Send stays
        # on the Description "Edit" tier (ghost, same rendered height).
        expect(drawer.locator(".comment-input")).to_have_attribute(
            "placeholder", "Add a comment… (Ctrl+Enter to send)")
        send_box = drawer.locator(".comment-send").bounding_box()
        edit_box = drawer.locator(".drawer-tools .button-ghost").first.bounding_box()
        assert send_box and edit_box and abs(send_box["height"] - edit_box["height"]) <= 1, (send_box, edit_box)
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-04-triage-10-phone.png")
        # …and every field under More fields is a whole target too, once opened
        open_more_fields(drawer)
        assert_min_target(drawer.locator(".field-control"))
        assert_no_horizontal_overflow(page)
        drawer.locator(".drawer-close").tap()
        expect(drawer).to_be_hidden()
        assert page.locator("nav.tabs").evaluate("el => getComputedStyle(el).visibility") == "visible"

        # --------------------------------------------- story 13 (#87) ----
        # The snooze control is a real touch target on the phone — this is the
        # device where "not today" is most often decided — and its popover
        # never pushes the page sideways.
        page.goto(f"{base}/")          # drop the story's ?status=todo first
        page.locator("nav.tabs .tab[data-tab='today']").tap()
        expect(page.locator("#paneToday")).to_be_visible()
        today_row = page.locator("#paneToday .today-group .trow").first
        expect(today_row).to_be_visible()
        # the row has no clock any more (#311): snooze lives in the ⋯ menu,
        # whose kebab is a touch target clear of the open target
        # (the rows on screen: Later and No date start folded, #393)
        assert_min_target(page.locator("#paneToday .today-group .trow-kebab:visible"))
        assert_no_overlap(page.locator("#paneToday .today-group .trow-main:visible, "
                                       "#paneToday .today-group .trow-kebab:visible"))
        today_row.locator(".trow-kebab").tap()
        page.locator(".row-menu [data-action='snooze']").tap()
        menu = page.locator("dialog#dateDialog .snooze-menu.date-sheet")
        expect(menu).to_be_visible()
        assert_min_target(menu.locator(".snooze-opt"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-13-starts-snooze-6-phone.png")
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()

        # the sleeping seed task wears its marker wherever it still shows
        page.goto(f"{base}/?status=deferred")
        page.locator("nav.tabs .tab[data-tab='board']").tap()
        page.locator("#paneBoard .board-strip-btn[data-col='todo']").tap()   # it is a todo task
        sleeping = _trow(page, "Book boiler service", "#paneBoard")
        expect(sleeping).to_be_visible()
        expect(sleeping.locator(".trow-starts")).to_have_text(re.compile(r"^\d+ \w{3}$"))
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-13-starts-snooze-7-phone.png")

        # --------------------------------------------- story 25 (#229) ----
        # "Every [7] weeks" on the phone the PWA lives on: the interval input
        # is a real touch target with a digit keypad, beside its unit, and the
        # Repeat composer never pushes the sheet sideways.
        review = _get(base, "/api/tasks?q=Weekly%20review")["items"][0]
        task_url = f"{base}/api/tasks/{review['id']}"
        page.request.patch(task_url, data={"recurrence_anchor": "sat", "recurrence_interval": 7})
        page.goto(f"{base}/#task/{review['id']}")
        drawer = page.locator("#taskDrawer")
        expect(drawer).to_be_visible()
        open_more_fields(drawer)
        every = drawer.locator("input[data-field='recurrence_interval']")
        expect(every).to_have_value("7")
        expect(every).to_have_attribute("inputmode", "numeric")
        expect(drawer.locator(".field-unit")).to_have_text("weeks")
        assert_min_target(every)
        assert_no_overlap(drawer.locator("select[data-field='recurrence'], "
                                         "input[data-field='recurrence_interval'], "
                                         "select[data-field='recurrence_anchor']"))
        every.scroll_into_view_if_needed()
        assert_no_horizontal_overflow(page)
        shot(page, shots / "story-25-recurrence-interval-2-phone.png")
        page.request.patch(task_url, data={"recurrence_anchor": "fri", "recurrence_interval": None})
        context.close()
    finally:
        wk.close()
