"""Story 09 — open a folder (Step 9/13, issue #10).

    A task carries {onedrive}/house/kitchen → the folder chip on the Table is a
    taskos://open?ref=… link whose tooltip is the path this server resolves →
    click it: the browser hands the URL to the per-PC opener (Explorer opens
    on that PC — proven by hand, see the validation record) and, once, a hint
    appears under the chip: "Nothing opened? Install the opener" → the hint
    leads to Settings → Folder opener, the one-line install command with this
    address filled in → in the drawer the Folder field takes an absolute path
    and stores it as {onedrive}/… → "Pick from folder index…" attaches a
    folder from the index → on the phone the chip shows the resolved path to
    copy instead of navigating.

Walks the story against a **disposable seeded instance whose {onedrive} points
at a temp tree** (so the seed's refs resolve to folders that exist and the
folder index has something to index — never a real synced folder), 1440×900
Chromium then a 390-wide touch context, saving the proof shots the validation
record links to:

    docs/screenshots/story-09-folders-1-desktop.png   Table: folder chips (taskos:// links)
    docs/screenshots/story-09-folders-2-desktop.png   the one-time hint under the chip
    docs/screenshots/story-09-folders-3-desktop.png   Settings: Folder opener card + install command
    docs/screenshots/story-09-folders-4-desktop.png   drawer: absolute path → {onedrive}/… ref
    docs/screenshots/story-09-folders-5-desktop.png   drawer: folder-index picker with hits
    docs/screenshots/story-09-folders-6-desktop.png   drawer after the pick (dark)
    docs/screenshots/story-09-folders-7-phone.png     phone: copy popover with the resolved path

The taskos:// navigation itself is intercepted here (a custom scheme cannot
be routed by Playwright); the real hand-off to Explorer is the headed walk.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.conftest import write_test_config
from tests.e2e._geometry import assert_no_horizontal_overflow
from tests.e2e.conftest import INTERCEPT, _boot, _get, _post, _terminate

DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


class FolderInstance:
    def __init__(self, base: str, od: Path) -> None:
        self.base = base
        self.od = od
        self.od_fwd = str(od).replace("\\", "/")


@pytest.fixture(scope="module")
def folder_webapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[FolderInstance]:
    """Seeded instance; {onedrive} = a temp tree with the seed's folders + a few more."""
    from tests.fixtures.seed import seed_db

    work = tmp_path_factory.mktemp("taskos-e2e-folders")
    od = work / "od"
    for rel in ("house/kitchen/plans", "house/garden", "house/bathroom", "admin/car", "admin/school", "task-os"):
        (od / rel).mkdir(parents=True)
    seed_db(work / "tasks.db")
    cfg = write_test_config(
        work / "config.json",
        folder_roots=["{onedrive}"],
        placeholders={"onedrive": str(od).replace("\\", "/"), "user": "sam"},
    )
    proc, base, log = _boot(work, work / "tasks.db", cfg)
    try:
        _post(base, "/api/folders/reindex")            # deterministic: don't race the startup thread
        yield FolderInstance(base, od)
    finally:
        _terminate(proc)
        log.close()


def _centers_align(*locators, tol: float = 2.0) -> None:
    """Every element sits on ONE line: same vertical centre within `tol` px."""
    boxes = [loc.bounding_box() for loc in locators]
    assert all(boxes), boxes
    centres = [b["y"] + b["height"] / 2 for b in boxes]
    assert max(centres) - min(centres) <= tol, boxes


def _kitchen(base: str) -> dict:
    items = _get(base, "/api/tasks?q=Kitchen&include_closed=true")["items"]
    return next(t for t in items if t["title"] == "Kitchen")


def test_open_a_folder(folder_webapp: FolderInstance, browser: Browser, shots: Path) -> None:
    inst = folder_webapp
    base = inst.base
    kitchen = _kitchen(base)
    assert kitchen["folder_ref"] == "{onedrive}/house/kitchen"
    assert kitchen["folder_resolved"] == inst.od_fwd + "/house/kitchen"     # the server resolves, never the page

    ctx = browser.new_context(viewport=DESKTOP, color_scheme="light")
    ctx.add_init_script(INTERCEPT)
    page: Page = ctx.new_page()
    page.goto(base + "/?status=doing,todo,standby&project=" + str(kitchen["parent_id"]))
    page.get_by_role("tab", name="Table").click()

    # 1. the chip: taskos:// href + resolved-path tooltip
    row = page.locator(f".task-row[data-id='{kitchen['id']}']")
    chip = row.locator("a.chip-folder")
    expect(chip).to_be_visible()
    assert chip.get_attribute("href") == "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"
    assert chip.get_attribute("title") == inst.od_fwd + "/house/kitchen"
    assert chip.get_attribute("target") is None                             # same tab → the OS handler
    page.screenshot(path=str(shots / "story-09-folders-1-desktop.png"))

    # 2. first click: the navigation is handed to the opener (intercepted here) + the one-time hint
    chip.click()
    assert page.evaluate("window.__taskosClicks") == ["taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"]
    pop = page.locator("#folderPop")
    expect(pop).to_be_visible()
    expect(pop).to_have_attribute("data-mode", "hint")
    expect(pop).to_contain_text("Nothing opened? Install the opener")
    expect(pop.locator(".folder-pop-path")).to_have_text(inst.od_fwd + "/house/kitchen")
    expect(page.locator("#taskDrawer")).to_be_hidden()                       # the chip never opens the row
    page.screenshot(path=str(shots / "story-09-folders-2-desktop.png"))
    page.keyboard.press("Escape")
    expect(pop).to_be_hidden()
    chip.click()                                                            # second click: no hint (one-time)
    page.wait_for_timeout(600)
    expect(pop).to_be_hidden()
    assert len(page.evaluate("window.__taskosClicks")) == 2

    # 3. the hint's link → Settings → Folder opener card with the command for this address
    page.evaluate("localStorage.removeItem('task-os.opener-hint')")
    chip.click()
    expect(pop).to_be_visible()
    pop.locator("a.folder-pop-install").click()
    expect(page.locator("#paneSettings")).to_be_visible()
    card = page.locator("#folderCard")
    expect(card).to_be_visible()
    cmd = card.locator("#openerInstall")
    expect(cmd).to_contain_text("$d=")
    expect(cmd).to_contain_text(base + "/opener/opener.cmd")
    expect(cmd).to_contain_text("HKCU:\\Software\\Classes\\taskos")
    expect(card.locator("#statusIndex")).to_contain_text("folder(s)")
    card.locator("details.opener-more summary").click()
    expect(card.locator("#openerEnv")).to_contain_text("onedrive=")
    page.screenshot(path=str(shots / "story-09-folders-3-desktop.png"), full_page=True)

    # 4. drawer: the Folder editor folds an absolute path onto the placeholder
    page.goto(base + "/#task/" + str(kitchen["id"]))
    drawer = page.locator("#taskDrawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator(".drawer-folder a.chip-folder")).to_have_attribute("href", "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen")
    # #74: the section is exactly TWO lines - [chip + delete] then
    # [ref + Change + Pick]. The resolved path is the chip's own tooltip, not a
    # third line, and the drawer's "Copy path" is gone (the phone still reaches
    # the path through the chip's popover, asserted in step 7).
    fchip = drawer.locator(".drawer-folder a.chip-folder")
    assert (fchip.get_attribute("title") or "").startswith(inst.od_fwd + "/house/kitchen")
    expect(drawer.locator(".folder-resolved")).to_have_count(0)
    expect(drawer.locator(".folder-copy")).to_have_count(0)
    expect(drawer.locator("div.drawer-folder > *:not([hidden])")).to_have_count(2)
    trash = drawer.locator(".folder-current .icon-btn")
    expect(trash).to_be_visible()
    _centers_align(fchip, trash)                      # delete is ON the chip's line, centred on it
    _centers_align(
        drawer.locator("#drawerFolder"),
        drawer.locator(".folder-form .button-surface"),
        drawer.locator("button.folder-pick"),
    )
    assert_no_horizontal_overflow(page)
    field = drawer.locator("#drawerFolder")
    field.fill(str(inst.od / "admin" / "car"))                              # backslashes, absolute
    field.press("Enter")
    expect(drawer.locator(".drawer-folder a.chip-folder")).to_have_attribute("href", "taskos://open?ref=%7Bonedrive%7D%2Fadmin%2Fcar")
    expect(page.locator(".toast")).to_contain_text("Stored as {onedrive}/admin/car")
    assert _get(base, f"/api/tasks/{kitchen['id']}")["folder_ref"] == "{onedrive}/admin/car"
    page.screenshot(path=str(shots / "story-09-folders-4-desktop.png"))

    # #74 removed the resolved-path line, so a placeholder this server does not
    # know has to warn ON the chip instead - deficit tint (which has to beat
    # `a.chip`'s accent) plus the reason in the tooltip. Never a silent chip.
    good_color = drawer.locator(".drawer-folder a.chip-folder").evaluate("el => getComputedStyle(el).color")
    field.fill("{nowhere}/lost")
    field.press("Enter")
    bad = drawer.locator(".drawer-folder a.chip-folder")
    expect(bad).to_have_attribute("data-ref", "{nowhere}/lost")      # the re-render landed
    assert "chip-missing" in (bad.get_attribute("class") or "")
    assert "placeholder not configured" in (bad.get_attribute("title") or "")
    assert bad.evaluate("el => getComputedStyle(el).color") != good_color
    field.fill(str(inst.od / "admin" / "car"))
    field.press("Enter")
    back = drawer.locator(".drawer-folder a.chip-folder")
    expect(back).to_have_attribute("data-ref", "{onedrive}/admin/car")
    assert "chip-missing" not in (back.get_attribute("class") or "")

    # 5. the folder-index picker: search-as-you-type, Enter attaches the first hit
    drawer.locator("button.folder-pick").click()
    q = drawer.locator(".folder-picker-q")
    expect(q).to_be_visible()
    q.fill("kitchen plans")
    hit = drawer.locator(".folder-picker-item")
    expect(hit).to_have_count(1)
    expect(hit.first.locator(".folder-picker-ref")).to_have_text("{onedrive}/house/kitchen/plans")
    page.screenshot(path=str(shots / "story-09-folders-5-desktop.png"))
    q.press("Enter")
    expect(drawer.locator(".drawer-folder a.chip-folder")).to_have_attribute("href", "taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen%2Fplans")
    assert _get(base, f"/api/tasks/{kitchen['id']}")["folder_ref"] == "{onedrive}/house/kitchen/plans"
    activity = _get(base, f"/api/tasks/{kitchen['id']}")["activity"]
    assert activity[0]["field"] == "folder_ref" and activity[0]["new_value"] == "{onedrive}/house/kitchen/plans"

    # 6. dark, for the record
    page.emulate_media(color_scheme="dark")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    page.wait_for_timeout(200)
    page.screenshot(path=str(shots / "story-09-folders-6-desktop.png"))
    ctx.close()

    # 7. phone (coarse pointer): the chip shows the path to copy instead of navigating
    phone = browser.new_context(viewport=PHONE, device_scale_factor=3, is_mobile=True, has_touch=True)
    phone.add_init_script(INTERCEPT)
    p = phone.new_page()
    p.goto(base + "/#task/" + str(kitchen["id"]))
    d = p.locator("#taskDrawer")
    expect(d).to_be_visible()
    d.locator(".drawer-folder a.chip-folder").click()
    pop = p.locator("#folderPop")
    expect(pop).to_be_visible()
    expect(pop).to_have_attribute("data-mode", "copy")
    expect(pop.locator(".folder-pop-path")).to_have_text(inst.od_fwd + "/house/kitchen/plans")
    expect(pop.locator("button.folder-pop-copy")).to_be_visible()
    # #74: still exactly two lines at 390 - the picker button drops to its
    # glyph so [ref + Change + Pick] stays on one line without side-scroll.
    expect(d.locator("div.drawer-folder > *:not([hidden])")).to_have_count(2)
    expect(d.locator(".folder-pick-label")).to_be_hidden()
    assert_no_horizontal_overflow(p)
    assert p.evaluate("document.querySelector('#taskDrawer a.chip-folder').getAttribute('href')").startswith("taskos://open?ref=")
    p.screenshot(path=str(shots / "story-09-folders-7-phone.png"))
    phone.close()
