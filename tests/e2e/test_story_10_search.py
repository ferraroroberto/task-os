"""Story 10 — find anything (Step 10/13, issue #11).

    The Search tab opens on one box and a hint, no group waiting empty
    (#395) → a word that matches nothing folds every kind into one line →
    type a word → one open group per kind with hits, Tasks · Folders · Emails
    · Issues (task hits are the ONE shared row, narrowed by the scope switch
    and the filter sheet; folder / email / issue hits are the same row shape,
    the title IS the link, no buttons — #48) → open a task from its row → the drawer
    beside the results → a folder hit's title hands its ref to the opener →
    ↓ ↓ Enter walks the rows → Ctrl+K → type a word → Enter opens the task →
    `>` lists the commands, Today first as in the nav → "Go to Board" switches the tab. On the phone the
    same box and the palette as a full-width sheet → a typo or a half-remembered query still finds the
    task, under a *Similar matches* / *Partial matches* sub-heading.

Walks the story against a **disposable seeded instance** whose four indexes
are all fixtures: ``{onedrive}`` → a temp tree, ``search.folder_explorer_url`` →
a fake folder-explorer (``tests/fixtures/folder_explorer_fake.py``) serving that
tree's folders and the synthetic mails of ``tests/fixtures/emails_fixture.py``
(never the real mailbox or the real folder-explorer), the issue provider → the file-backed fake (never ``gh``). 1440×900
Chromium then a 390-wide touch context, saving the proof shots the
validation record links to:

    docs/screenshots/story-10-search-1-desktop.png   "kitchen": four open groups, in the centred 772px measure
    docs/screenshots/story-10-search-2-desktop.png   drawer open beside the results
    docs/screenshots/story-10-search-4-desktop.png   Ctrl+K: jump to a task
    docs/screenshots/story-10-search-5-desktop.png   Ctrl+K: > commands (dark)
    docs/screenshots/story-10-search-6-phone.png     phone: results
    docs/screenshots/story-10-search-7-phone.png     phone: the palette sheet
    docs/screenshots/story-10-search-10-phone.png    phone: Today's search field with its Todo pill (light)
    docs/screenshots/story-10-search-11-phone.png    phone: the same, widened to every status (dark)

A shot number is the step it belongs to, so the set skips 3: that step used
to be "New task on a folder hit", which #48 removed along with the per-hit
buttons. Step 3 is still walked (the opener hand-off and the ↓ ↓ Enter
keyboard leg) — it just has nothing left worth a picture.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e._port_pool import post_json
from tests.e2e._surface import surface
from tests.e2e._ui import assert_control_boundaries, close_filter_sheet, open_filter_sheet
from tests.e2e.conftest import (
    E2E_ANCHOR,
    FAKE_ISSUES,
    INTERCEPT,
    _get,
    _post,
    booted,
    e2e_workdir,
    shot,
)
from tests.fixtures.folder_explorer_fake import FakeFolderExplorer, fixture_mails, folders_under

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
KITCHEN_ISSUE = {
    "repo": "example/home-dashboard", "number": 7, "title": "Kitchen lights automation", "state": "open",
    "url": "https://github.com/example/home-dashboard/issues/7", "labels": ["enhancement", "kitchen"],
    "updated_at": "2026-08-16T12:00:00Z", "body": "Turn the kitchen lights on with the motion sensor.",
}


class SearchInstance:
    def __init__(self, base: str, od: Path, db: Path, fe: FakeFolderExplorer) -> None:
        self.fe = fe
        self.base = base
        self.od = od
        self.od_fwd = od.as_posix()
        self.db = db


@pytest.fixture(scope="module")
def search_webapp() -> Iterator[SearchInstance]:
    """Seeded instance; every index a fixture under one temp tree."""
    from tests.fixtures.seed import seed_db

    work = e2e_workdir("search")
    od = work / "od"
    for rel in ("house/kitchen/plans", "house/garden", "house/bathroom", "admin/car", "admin/school", "task-os"):
        (od / rel).mkdir(parents=True)
    seed_db(work / "tasks.db", E2E_ANCHOR)
    fe = FakeFolderExplorer(folders=folders_under(od), emails=fixture_mails(od))
    cfg = write_test_config(
        work / "config.json",
        folder_explorer_url=fe.url,
        placeholders={"onedrive": od.as_posix(), "user": "sam"},
    )
    forge = work / "forge.json"
    forge.write_text(json.dumps({"issues": [*FAKE_ISSUES, KITCHEN_ISSUE], "error": None}, indent=1), encoding="utf-8")
    try:
        with booted(work, work / "tasks.db", cfg,
                    extra_env={"TASKOS_ISSUE_PROVIDER": "fake", "TASKOS_ISSUE_FAKE_PATH": str(forge)}) as base:
            _post(base, "/api/issues/sync")            # warm the issue cache (and make the fake's tasks)
            yield SearchInstance(base, od, work / "tasks.db", fe)
    finally:
        fe.stop()


def _task_post(base: str, body: dict) -> dict:
    return post_json(base, "/api/tasks", body, timeout=60)


def _open_group(page: Page, kind: str):
    """A result group: there only when its kind has hits, and open (#395)."""
    g = page.locator(f".search-group[data-kind='{kind}']")
    expect(g).to_be_visible()
    expect(g).to_have_attribute("open", "")
    return g


def _task_hit(page: Page, title: str):
    """A task hit = the ONE shared row (rows.js) by exact title."""
    return page.locator(".search-group[data-kind='tasks'] .search-hit.trow",
                        has=page.locator(".trow-title", has_text=re.compile(rf"^{re.escape(title)}$"))).first


def _empty_search_tab(page: Page, box) -> None:
    """Before a query: one box and a hint."""
    # before a query: one box and a hint — no group shells waiting empty, and
    # with every index set up, nothing to fold (J-09, #395)
    expect(page.locator(".search-hint")).to_have_text(re.compile(r"^Searches your tasks, folders, emails and issues"))
    expect(page.locator(".search-group")).to_have_count(0)
    expect(page.locator(".search-fold")).to_have_count(0)
    # a word that matches nothing: no group at all, every kind named on the one
    # folded line instead of four cards each saying "nothing"
    box.fill("zzqxnothing")
    expect(page.locator("#searchMeta")).to_have_text("0 hits · open only")
    expect(page.locator(".search-group")).to_have_count(0)
    expect(page.locator(".search-fold")).to_have_text("No matches in tasks (open only), folders, emails and issues")
    # the clear button shows only while the box holds text, is a 44px target,
    # and one tap empties the query and the count and keeps the caret in the box
    clear = page.get_by_role("button", name="Clear search")
    expect(clear).to_be_visible()
    target = clear.bounding_box()
    assert target and target["width"] >= 44 and target["height"] >= 44, target
    clear.click()
    expect(box).to_have_value("")
    expect(box).to_be_focused()
    expect(page.locator("#searchMeta")).to_have_text("")
    expect(clear).to_be_hidden()
    expect(page.locator(".search-hint")).to_be_visible()
    box.fill("zzqxnothing")                                       # leave the box as the next steps expect it
    expect(page.locator("#searchMeta")).to_have_text("0 hits · open only")
    # the box carries the filter button (the sheet narrows the task hits), the
    # scope switch is the line under it; the sheet leads with the sort and
    # holds every filter (#395)
    sheet = open_filter_sheet(page, "paneSearch")
    names = sheet.locator(".filter-sheet-row").evaluate_all("els => els.map(e => e.dataset.name)")
    assert names == ["sort", "status", "project", "person", "due", "updated"], names
    close_filter_sheet(page)
    expect(page.locator("#searchScope .segmented-item[aria-pressed='true']")).to_have_text("Tasks")


def _four_groups_for_a_word(page: Page, shots: Path, box):
    """Step 1: a word finds four groups, each headed by its kind and count."""
    # 1. type a word → four groups, open, each headed by its kind and count,
    #    all populated. Mine is the default scope: the synced issue's task is
    #    cut from the task hits (the Issues group still lists it), which the
    #    count says as "N of M"
    box.fill("kitchen")
    groups = page.locator(".search-group")
    expect(groups).to_have_count(4)
    for kind in ("tasks", "folders", "emails", "issues"):
        g = _open_group(page, kind)
        expect(g.locator(".search-group-count")).to_have_text(re.compile(r"^\d+( of \d+)?$"))
        expect(g.locator(".search-group-count")).to_have_attribute("aria-label", re.compile(r"^\d+ hits?$"))
        expect(g.locator(".search-hit").first).to_be_visible()
    expect(page.locator("#searchMeta")).to_have_text(re.compile(r"^\d+ hits · open only$"))   # no milliseconds anywhere
    expect(page.locator(".search-fold")).to_have_count(0)            # every kind has hits
    issue_task = _task_hit(page, "Kitchen lights automation")
    expect(issue_task).to_have_count(0)
    expect(page.locator(".search-group[data-kind='tasks'] .search-group-count")).to_have_text(re.compile(r"^\d+ of \d+$"))
    # All brings it back into the task hits; the switch is the shared URL key
    page.locator("#searchScope .segmented-item[data-scope='all']").click()
    expect(issue_task).to_be_visible()
    expect(page.locator(".search-group[data-kind='tasks'] .search-group-count")).to_have_text(re.compile(r"^\d+$"))
    page.locator("#searchScope .segmented-item[data-scope='mine']").click()
    expect(issue_task).to_have_count(0)
    # task hits are the ONE shared row — done circle + title + the passive meta
    # line (no status word for "todo"; the folder is the row menu's, not a glyph —
    # #392) + the Move verb + the kebab
    kitchen_hit = _task_hit(page, "Kitchen")
    expect(kitchen_hit.locator(".trow-title")).to_contain_text("Kitchen")
    expect(kitchen_hit).to_have_attribute("data-status", "todo")
    expect(kitchen_hit.locator(".trow-done")).to_have_attribute("aria-pressed", "false")
    expect(kitchen_hit.locator(".trow-meta .trow-folder")).to_have_count(0)   # #392: the menu opens it
    expect(kitchen_hit.locator(".trow-kebab")).to_be_visible()
    # folder / email / issue hits are the same row shape (#48): a title line and
    # one muted meta line (inside .trow-main), no glyphs, no buttons — the title
    # IS the link, and no done circle or kebab (only task rows carry them)
    folder_hit = page.locator(".search-group[data-kind='folders'] .search-hit").first
    expect(folder_hit).to_have_class(re.compile(r"\btrow\b"))
    expect(folder_hit.locator(".trow-meta .search-hit-meta").first).to_contain_text("/house/kitchen")
    expect(folder_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^taskos://open\?ref="))
    expect(folder_hit.locator("[data-act='new'], [data-act='attach'], .search-hit-icon, .search-hit-actions, .trow-done, .trow-kebab")).to_have_count(0)
    email_hit = page.locator(".search-group[data-kind='emails'] .search-hit").first
    expect(email_hit.locator(".trow-title")).to_contain_text("Kitchen quotes from the installer")
    expect(email_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^taskos://open\?ref="))
    expect(email_hit.locator("[data-act='attach'], .search-hit-actions")).to_have_count(0)
    issue_hit = page.locator(".search-group[data-kind='issues'] .search-hit").first
    expect(issue_hit.locator(".trow-title")).to_contain_text("Kitchen lights automation")
    # this issue is already on the list: its title opens the linked task (the
    # issue chip inside the task is the forge link); the meta names repo#N + task
    expect(issue_hit.locator("a.search-hit-link[data-act='open']")).to_have_attribute("href", re.compile(r"^#task/\d+$"))
    expect(issue_hit.locator(".trow-meta")).to_contain_text("example/home-dashboard#7")
    expect(issue_hit.locator(".trow-meta")).to_contain_text("task #")
    expect(page.locator(".search-hit mark").first).to_be_visible()
    assert "q=kitchen" in page.url                                # ?q= keeps the query
    shot(page, shots / "story-10-search-1-desktop.png", full_page=True)
    return g, kitchen_hit


def _open_hits_from_the_results(page: Page, base: str, shots: Path, box, kitchen_hit):
    """Steps 2-3: a task hit opens the drawer; a folder hit goes to the opener."""
    # 2. open a task (the Kitchen task) from its row → the drawer beside the results
    kitchen_hit.locator(".trow-main").click()
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")
    shot(page, shots / "story-10-search-2-desktop.png")

    # 3. the folder hit's title link hands the ref to the opener (intercepted here)
    page.locator(".search-group[data-kind='folders'] .search-hit").first.locator("a.search-hit-link[data-act='open']").click()
    assert page.evaluate("window.__taskosClicks")[-1] == "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"
    pop = page.locator("#folderPop")                                # the one-time "install the opener" hint (Step 9)
    expect(pop).to_be_visible()
    page.keyboard.press("Escape")
    expect(pop).to_be_hidden()
    # keyboard: ↓ from the box focuses the first row (its title button), ↓
    # again the second task row, Enter opens that row's task
    box.click()
    box.press("ArrowDown")
    expect(page.locator(".search-hit").first.locator(".trow-main")).to_be_focused()
    page.keyboard.press("ArrowDown")
    second = page.locator(".search-group[data-kind='tasks'] .search-hit").nth(1)
    expect(second.locator(".trow-main")).to_be_focused()
    second_title = _get(base, f"/api/tasks/{second.get_attribute('data-id')}")["title"]
    page.keyboard.press("Enter")
    expect(drawer.locator("#drawerTitle")).to_have_value(second_title)
    return drawer


def _palette_and_commands(page: Page, ctx, browser: Browser, base: str, shots: Path, drawer, g):
    """Steps 4-7: Ctrl+K jumps to a task; > runs a command."""
    # 4. Ctrl+K → type → Enter opens the task
    page.keyboard.press("Escape")                                   # close the drawer
    expect(drawer).to_be_hidden()
    page.get_by_role("tab", name="Today").click()
    page.keyboard.press("Control+k")
    palette = page.locator("#palette")
    expect(palette).to_be_visible()
    pin = page.locator("#paletteInput")
    expect(pin).to_be_focused()
    pin.fill("passports")
    item = page.locator("#paletteList .palette-item[data-kind='task']").first
    expect(item).to_contain_text("Renew passports")
    shot(page, shots / "story-10-search-4-desktop.png")
    pin.press("Enter")
    expect(palette).to_be_hidden()
    expect(drawer).to_be_visible()
    expect(drawer.locator("#drawerTitle")).to_have_value("Renew passports")

    # 5. > commands → "Go to Board" (dark, for the record)
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    page.keyboard.press("Control+K")
    expect(palette).to_be_visible()
    pin.fill(">go to")
    cmds = page.locator("#paletteList .palette-item[data-kind='command']")
    expect(cmds.first).to_contain_text("Go to Today")   # nav order: Today leads (#319)
    # one per nav destination plus Archive and Settings — Time joined in #457
    expect(cmds).to_have_text([re.compile(rf"^Go to {name}") for name in ("Today", "Board", "Time", "Archive", "Search", "Settings")])
    shot(page, shots / "story-10-search-5-desktop.png")
    pin.fill(">go to board")
    expect(cmds.first).to_contain_text("Go to Board")
    pin.press("Enter")
    expect(palette).to_be_hidden()
    expect(page.locator("#paneBoard")).to_be_visible()
    expect(page.locator("nav.tabs")).to_have_attribute("data-active-tab", "board")
    # a "not configured" state renders as a visible row, never a blank: ask for a kind that is off
    # (the disposable instance has all four on — prove it through the API contract instead)
    off = _get(base, "/api/search?q=kitchen&kinds=tasks")
    assert next(g for g in off["groups"] if g["kind"] == "emails")["skipped"] is True
    ctx.close()

    # 6-7. phone: results as a one-column list, the palette as a full-width sheet
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    phone.add_init_script(INTERCEPT)
    p = phone.new_page()
    p.goto(base + "/?q=kitchen#search")
    expect(p.locator("#paneSearch")).to_be_visible()
    expect(p.locator("#searchInput")).to_have_value("kitchen")
    expect(p.locator(".search-group")).to_have_count(4)
    expect(p.locator(".search-group[data-kind='emails'] .search-group-count")).to_have_attribute("aria-label", re.compile(r"^\d+ hits?$"))
    _open_group(p, "emails")
    expect(p.locator(".search-group[data-kind='emails'] .search-hit").first).to_be_visible()
    shot(p, shots / "story-10-search-6-phone.png")
    p.keyboard.press("Control+K")
    expect(p.locator("#palette")).to_be_visible()
    p.locator("#paletteInput").fill("water")
    expect(p.locator("#paletteList .palette-item[data-kind='task']").first).to_contain_text("Pay water bill")
    shot(p, shots / "story-10-search-7-phone.png")
    p.keyboard.press("Escape")
    return p, phone


def _long_hits_and_everyone(base: str, inst, p, phone) -> None:
    """Steps 8-9: a long hit never widens the page; search covers everyone."""
    # 8. a long hit never widens the page (#417): invented over-long names (a
    # folder, a project holding the matching task) on a 390px screen. The grid
    # item's auto minimum used to take the nowrap meta row's full width, and
    # the whole Search pane scrolled sideways.
    longdir = inst.od / "house" / ("longprobe-" + "x" * 90)
    longdir.mkdir()
    inst.fe.folders.append(str(longdir))
    # folder-explorer still on its first email build: its own line on the Search tab, never "No matches"
    inst.fe.set_state("emails", "indexing", "the email index is being built")
    p.goto(base + "/?q=kitchen#search")
    p.reload()                                  # the page is already on this address: a reload re-runs the query
    expect(p.locator(".search-err", has_text="Emails unavailable (indexing)")).to_be_visible()
    expect(p.locator(".search-group[data-kind='emails']")).to_have_count(0)
    assert "Emails" not in " ".join(p.locator(".search-fold").all_inner_texts())      # not folded into "No matches"
    inst.fe.set_state("emails", "ok")
    project = _task_post(base, {"title": "Quarterly-programme-" + "y" * 80})
    _task_post(base, {"title": "Longprobe task", "parent_id": project["id"]})
    p.goto(base + "/?q=longprobe#search")
    expect(p.locator(".search-group[data-kind='tasks'] .search-hit.trow", has_text="Longprobe task")).to_be_visible()
    expect(p.locator(".search-group[data-kind='folders'] .search-hit", has_text="longprobe-")).to_be_visible()
    widths = p.evaluate("({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})")
    assert widths["scroll"] <= widths["client"], f"the page scrolls sideways: {widths}"

    # 9. search covers everyone, whichever way Mine · Everyone is set (#477): a
    # task of the install's second member is found from the owner's phone on
    # Mine and on Everyone, the Search tab carries no person row, and the
    # palette finds it too. Today on Mine does not list it.
    zebra = _task_post(base, {"title": "Zebra paperwork", "owner": "p2", "due": "2026-09-07"})
    assert zebra["owner"] == "p2"
    for whose in ("", "&whose=everyone"):
        p.goto(f"{base}/?q=zebra{whose}#search")
        expect(p.locator("#paneSearch")).to_be_visible()
        expect(_task_hit(p, "Zebra paperwork")).to_be_visible()
        expect(p.locator("#paneSearch .owner-switch")).to_have_count(0)
    p.goto(f"{base}/")
    p.click("nav.tabs .tab[data-tab='today']")
    expect(open_filter_sheet(p, "paneToday").locator(".owner-switch .segmented-item[aria-pressed='true']")).to_have_text("Mine")
    close_filter_sheet(p)
    expect(p.locator("#paneToday .trow[data-id]").first).to_be_visible()
    expect(p.locator("#paneToday .trow", has=p.locator(".trow-title", has_text="Zebra paperwork"))).to_have_count(0)
    p.keyboard.press("Control+K")
    p.locator("#paletteInput").fill("zebra")
    expect(p.locator("#paletteList .palette-item[data-kind='task']").first).to_contain_text("Zebra paperwork")
    p.keyboard.press("Escape")
    _weaker_matches_sit_under_a_label(base, p)
    _cleared_status_searches_every_task(base, p)
    phone.close()


def _weaker_matches_sit_under_a_label(base: str, p: Page) -> None:
    """Step 10: a typo and a half-remembered query still find the task, under a label.

    One word that is not spelled right, and a second word that is nowhere: each
    answer sits under its tier's sub-heading, after any exact hit, and an exact
    query carries none.
    """
    tasks = ".search-group[data-kind='tasks']"
    p.goto(f"{base}/?q=worktp#search")                             # a one-letter typo of "worktop"
    expect(p.locator(f"{tasks} .search-tier[data-tier='similar']")).to_have_text("Similar matches")
    expect(_task_hit(p, "Choose worktop material")).to_be_visible()
    expect(p.locator(f"{tasks} .search-tier[data-tier='partial']")).to_have_count(0)
    p.goto(f"{base}/?q=worktop%20zzqxj#search")                    # one word of two is in the task
    expect(p.locator(f"{tasks} .search-tier[data-tier='partial']")).to_have_text("Partial matches")
    expect(_task_hit(p, "Choose worktop material")).to_be_visible()
    p.goto(f"{base}/?q=worktop#search")                            # spelled right: no label
    expect(_task_hit(p, "Choose worktop material")).to_be_visible()
    expect(p.locator(f"{tasks} .search-tier")).to_have_count(0)


def _cleared_status_searches_every_task(base: str, p: Page) -> None:
    """Step 11: open by default; clear the status ticks and done and cancelled tasks are found too."""
    bikes = ".search-group[data-kind='tasks']"
    p.goto(f"{base}/?q=bikes#search")                              # "Sell the old bikes" is cancelled in the seed
    expect(p.locator("#searchMeta")).to_have_text("0 hits · open only")
    expect(p.locator(f"{bikes} .search-hit")).to_have_count(0)
    expect(p.locator(".search-fold")).to_contain_text("1 task hit hidden by the filters")
    sheet = open_filter_sheet(p, "paneSearch")
    status = sheet.locator(".filter-checks[data-name='status']")
    # the default is drawn as the open statuses ticked, so clearing them is a visible act
    ticked = status.locator("input:checked").evaluate_all("els => els.map(e => e.value)")
    assert ticked == ["inbox", "todo", "standby"], ticked
    for value in ticked:
        status.locator(f"input[value='{value}']").uncheck()
    close_filter_sheet(p)
    expect(p.locator("#searchMeta")).to_have_text("1 hit · every status")
    expect(_task_hit(p, "Sell the old bikes")).to_have_attribute("data-status", "cancelled")
    expect(p.locator("#paneSearch .filter-open .filter-count")).to_have_text("1")
    # done tasks too
    p.locator("#searchInput").fill("gift")
    expect(_task_hit(p, "Buy a birthday gift")).to_have_attribute("data-status", "done")
    # Today shares the state: its Todo pill is gone and the button counts the widening. Its list is
    # still the open tasks until its own search field has text; then every status, said in the header
    p.click("nav.tabs .tab[data-tab='today']")
    expect(p.locator("#todayFilterText .filter-pill")).to_have_count(0)
    expect(p.locator("#paneToday .filter-open .filter-count")).to_have_text("1")
    bikes_row = p.locator("#paneToday .trow", has_text="Sell the old bikes")
    expect(bikes_row).to_have_count(0)
    p.locator("#todayFilterText .filter-q").fill("bikes")
    expect(bikes_row).to_have_count(1)
    expect(p.locator("#homeHeadStatus")).to_contain_text("every status")
    p.locator("#todayFilterText .filter-q").fill("")
    expect(bikes_row).to_have_count(0)
    expect(p.locator("#homeHeadStatus")).not_to_contain_text("every status")
    # Clear puts the default back
    p.click("nav.tabs .tab[data-tab='search']")
    open_filter_sheet(p, "paneSearch").get_by_role("button", name="Clear").click()
    close_filter_sheet(p)
    expect(p.locator("#searchMeta")).to_have_text("0 hits · open only")


def _on_one_line(page: Page, pane: str) -> None:
    """The pane's strip is one line: field, filter button and + share a row, inside the screen (#789)."""
    boxes = [page.locator(f"#{pane} {sel}").bounding_box() for sel in (".filter-field", ".filter-open", ".quick-add-btn")]
    field, button, plus = boxes
    assert field and button and plus, boxes
    centres = [b["y"] + b["height"] / 2 for b in boxes]
    assert max(centres) - min(centres) < 6, f"the strip wrapped onto two lines: {boxes}"
    assert plus["x"] + plus["width"] <= PHONE["width"] and field["x"] >= 0, boxes
    assert field["x"] + field["width"] <= button["x"] + 1, f"the field runs under the filter button: {boxes}"
    widths = page.evaluate("({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})")
    assert widths["scroll"] <= widths["client"], f"the page scrolls sideways: {widths}"


def _status_pills_in_the_search_field(base: str, browser: Browser, shots: Path) -> None:
    """#789: Today and Board open with a Todo pill in the search field; × widens the search; the sheet and the pills are one state."""
    for title, status in (("Pillprobe todo", "todo"), ("Pillprobe inbox", "inbox"), ("Pillprobe done", "done")):
        _task_post(base, {"title": title, "status": status})
    light = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="light")
    dark = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="dark")
    try:
        _pill_walk(base, shots, light.new_page(), "light")
        _pill_walk(base, shots, dark.new_page(), "dark")
    finally:
        light.close()
        dark.close()


def _pill_walk(base: str, shots: Path, p: Page, scheme: str) -> None:
    """One theme's phone walk of the status pills (a fresh context, so the default state)."""
    p.goto(base + "/")
    assert p.evaluate("document.documentElement.dataset.theme") == scheme
    pill = p.locator("#todayFilterText .filter-pill")
    rows = p.locator("#paneToday .trow", has=p.locator(".trow-title", has_text="Pillprobe"))
    # default: one Todo pill; the strip stays one line; nothing is filtered yet (no count on the button)
    expect(pill).to_have_count(1)
    expect(pill).to_have_text("Todo")
    expect(p.locator("#paneToday .filter-open .filter-count")).to_be_hidden()
    _on_one_line(p, "paneToday")
    p.click("nav.tabs .tab[data-tab='board']")
    expect(p.locator("#boardFilterText .filter-pill")).to_have_text("Todo")
    _on_one_line(p, "paneBoard")
    p.click("nav.tabs .tab[data-tab='today']")
    # a search covers the to-do tasks only, and the header line says so
    p.locator("#todayFilterText .filter-q").fill("pillprobe")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Pillprobe todo")
    expect(p.locator("#homeHeadStatus")).to_contain_text("todo")
    if scheme == "light":
        shot(p, shots / "story-10-search-10-phone.png")
    # × on the last pill: every status
    pill.click()
    expect(pill).to_have_count(0)
    expect(rows).to_have_count(3)
    expect(p.locator("#homeHeadStatus")).to_contain_text("every status")
    expect(p.locator("#paneToday .filter-open .filter-count")).to_have_text("1")
    _on_one_line(p, "paneToday")
    if scheme == "dark":
        shot(p, shots / "story-10-search-11-phone.png")
    # the sheet draws the pills' state: nothing ticked; ticking Todo brings the resting pill back
    sheet = open_filter_sheet(p, "paneToday")
    status = sheet.locator(".filter-checks[data-name='status']")
    expect(status.locator("input:checked")).to_have_count(0)
    status.locator("input[value='todo']").check()
    status.locator("input[value='done']").check()
    close_filter_sheet(p)
    expect(pill).to_have_count(2)
    expect(rows).to_have_count(2)                              # Pillprobe todo + Pillprobe done
    # × on one of several drops only that status, and un-ticks it in the sheet
    p.locator("#todayFilterText .filter-pill[data-status='done']").click()
    expect(pill).to_have_count(1)
    expect(pill).to_have_text("Todo")
    expect(rows).to_have_count(1)
    status = open_filter_sheet(p, "paneToday").locator(".filter-checks[data-name='status']")
    expect(status.locator("input:checked")).to_have_count(1)
    expect(status.locator("input[value='todo']")).to_be_checked()
    expect(status.locator("input[value='done']")).not_to_be_checked()
    close_filter_sheet(p)


def test_find_anything(search_webapp: SearchInstance, browser: Browser, shots: Path) -> None:
    inst = search_webapp
    base = inst.base
    st = _get(base, "/api/search/status")["adapters"]
    assert all(a["configured"] for a in st), st                    # the four indexes are all wired

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(INTERCEPT)
    page: Page = ctx.new_page()
    page.goto(base + "/")
    page.get_by_role("tab", name="Search").click()
    box = page.locator("#searchInput")
    expect(box).to_be_focused()
    assert_control_boundaries(page.locator("#searchBox"))      # the card is the field's edge (#339)
    _empty_search_tab(page, box)
    g, kitchen_hit = _four_groups_for_a_word(page, shots, box)
    surface(page, "search.pane")
    drawer = _open_hits_from_the_results(page, base, shots, box, kitchen_hit)
    p, phone = _palette_and_commands(page, ctx, browser, base, shots, drawer, g)
    _long_hits_and_everyone(base, inst, p, phone)
    _status_pills_in_the_search_field(base, browser, shots)
