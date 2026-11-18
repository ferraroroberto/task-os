"""The drawer's `e` key (opens the task's folder), walked inside story 04's one test.

Kept beside it rather than in it: the story file is at its size cap.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.conftest import _get

# A click on the folder chip is observed and cancelled before the browser follows
# its `taskos://` link, so no File Explorer window opens during the test.
_RECORD_FOLDER_OPENS = """
window.__folderOpens = [];
document.addEventListener('click', function (ev) {
  const a = ev.target.closest && ev.target.closest('a.chip-folder');
  if (!a) return;
  window.__folderOpens.push(a.getAttribute('href'));
  ev.preventDefault();
}, true);
"""


def walk_drawer_e_opens_folder(page: Page, base: str) -> None:
    """`e` with a task open in the drawer opens its folder; typed in a field it is a letter."""
    kitchen_id = next(int(t["id"]) for t in _get(base, "/api/tasks?q=Kitchen")["items"] if t["title"] == "Kitchen")
    page.goto(f"{base}/#task/{kitchen_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")
    expect(drawer.locator(".drawer-folder a.chip-folder")).to_be_visible()
    page.evaluate(_RECORD_FOLDER_OPENS)

    # typing in a field types the letter and opens nothing
    comment = drawer.locator(".comment-input")
    comment.click()
    page.keyboard.press("e")
    expect(comment).to_have_value("e")
    assert page.evaluate("window.__folderOpens") == []
    comment.fill("")

    # focus on the drawer itself (not a field): `e` follows the folder chip's opener link
    drawer.locator(".drawer-close").focus()
    page.keyboard.press("e")
    page.wait_for_function("window.__folderOpens.length === 1")
    assert page.evaluate("window.__folderOpens")[0].startswith("taskos://open?ref=")

    # the key is discoverable: the palette's command carries it, and the sheet lists it
    page.keyboard.press("Control+k")
    palette = page.locator("#palette")
    palette.locator("input").fill("open folder")
    expect(palette.locator("li", has_text="Open folder of current task").locator("kbd")).to_have_text("E")
    page.keyboard.press("Escape")
    drawer.locator(".drawer-close").click()
    page.locator("body").press("?")
    expect(page.locator("#keysHelp")).to_contain_text("Open the folder of the open task")
    page.keyboard.press("Escape")
    expect(page.locator("#keysHelp")).to_be_hidden()
