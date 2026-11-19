"""The drawer's keys (the row keys and its own act on the open task), walked
inside story 04's one test.

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
    """With a task open the keys act on it: `e` opens its folder (typed in a
    field it is a letter), `2` `3` set its status, `t` its due date, `p` its
    priority, `c` puts the cursor in the comment field, `l` unfolds the
    folder and link editors and `x` closes it as done, with Undo."""
    kitchen_id = next(int(t["id"]) for t in _get(base, "/api/tasks?q=Kitchen")["items"] if t["title"] == "Kitchen")
    page.goto(f"{base}/#task/{kitchen_id}")
    drawer = page.locator("#taskDrawer")
    expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")
    expect(drawer.locator(".prop-links a.drawer-folder-chip")).to_be_visible()
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

    # the row keys act on the open task, each with the row's Undo
    before = _get(base, f"/api/tasks/{kitchen_id}")
    status = drawer.locator(".drawer-status")
    page.keyboard.press("3")
    expect(status.locator("[data-status='standby']")).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("2")
    expect(status.locator("[data-status='todo']")).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("t")
    expect(page.locator("#toast")).to_contain_text("Due tomorrow")
    page.keyboard.press("z")
    expect(page.locator("#toast")).to_contain_text("Undone")
    assert _get(base, f"/api/tasks/{kitchen_id}")["due"] == before["due"]
    page.keyboard.press("p")
    expect(drawer.locator(".prop-row[data-field='priority']")).not_to_have_attribute("data-value", before["priority"] or "none")
    page.request.patch(f"{base}/api/tasks/{kitchen_id}", data={"priority": before["priority"], "status": before["status"]})
    page.reload()
    expect(drawer.locator("#drawerTitle")).to_have_value("Kitchen")

    # the drawer's own keys: c the comment field, l the editors
    drawer.locator(".drawer-close").focus()
    page.keyboard.press("c")
    expect(comment).to_be_focused()
    drawer.locator(".drawer-close").focus()
    page.keyboard.press("l")
    expect(drawer.locator(".drawer-links-editor")).to_be_visible()
    expect(drawer.locator(".prop-links-edit")).to_have_attribute("aria-expanded", "true")

    # the keys are discoverable: the palette's command carries `e`, the sheet
    # and the line under the property list list the rest
    expect(drawer.locator(".drawer-key-legend")).to_contain_text("Keys act on this task")
    drawer.locator(".drawer-close").focus()
    page.keyboard.press("Control+k")
    palette = page.locator("#palette")
    palette.locator("input").fill("open folder")
    expect(palette.locator("li", has_text="Open folder of current task").locator("kbd")).to_have_text("E")
    page.keyboard.press("Escape")

    # x closes it as done, with Undo, which puts it back open
    drawer.locator(".drawer-close").focus()
    page.keyboard.press("x")
    expect(drawer).to_be_hidden()
    expect(page.locator("#toast")).to_contain_text("Completed")
    assert _get(base, f"/api/tasks/{kitchen_id}")["status"] == "done"
    page.locator("#toast").get_by_role("button", name="Undo (Z)").click()
    expect(page.locator("#toast")).to_contain_text("Undone")
    assert _get(base, f"/api/tasks/{kitchen_id}")["status"] == before["status"]

    page.locator("body").press("?")
    expect(page.locator("#keysHelp")).to_contain_text("With a task open")
    expect(page.locator("#keysHelp")).to_contain_text("Open the folder")
    page.keyboard.press("Escape")
    expect(page.locator("#keysHelp")).to_be_hidden()
