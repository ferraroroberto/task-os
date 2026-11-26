"""Story 05's late-refresh walk: a held list read must not undo a newer edit.

``_walk_edit_refresh`` is the driver the story file calls; the steps under it
are the slices of one walk and leave the page where the next one starts.
"""

from __future__ import annotations

from datetime import timedelta

from playwright.sync_api import Page, expect

from tests.e2e._board_steps import _today_row
from tests.e2e.conftest import E2E_ANCHOR, _get, settle

# Wraps the page's own fetch so a list read is answered by the server at once
# and handed to the app late — the order the network does not promise (#321).
# "Late" is when the walk calls `release()`, never a timer: the held answers have
# to land after the newer ones however slow the box is. In the page, not a
# Playwright route: a route handler that sleeps is a callback in flight, and one
# still sleeping when the context closes fails the teardown.
_HOLD_LIST_READS = r"""() => {
  const real = window.fetch.bind(window);
  const hold = window.__hold = {on: false, held: 0, delivered: 0};
  const released = new Promise(function (resolve) { hold.release = resolve; });
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init && init.method) || 'GET';
    const lists = /\/api\/(tasks\?|tasks\/tree|today)/.test(url);
    if (!hold.on || method !== 'GET' || !lists) return real(input, init);
    hold.held += 1;
    return real(input, init).then(function (res) {
      return released.then(function () { hold.delivered += 1; return res; });
    });
  };
}"""


def _edit_refresh_hold_the_reads(page: Page, base: str, made):
    """Step 1: a task, and the first edit's refresh reads held back."""
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
    return counts, drawer, tid


def _edit_refresh_second_edit(page: Page, base: str, drawer, tid) -> None:
    """Step 2: the due date, edited while those reads are still held."""
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


def _edit_refresh_rows_after_release(page: Page, counts, drawer, tid) -> None:
    """Step 3: every held answer lands; the rows keep the newer edit."""
    # 3. The newer edit's answer is on the row first, so what is released now
    #    really is stale. Let every held answer land, then settle — the stale
    #    overwrite, if there is one, has happened by now.
    expect(page.locator(f"#boardHost .trow[data-id='{tid}']")).to_contain_text("in 4w")
    assert counts()["delivered"] == 0, "a held read landed before the walk released it"
    page.evaluate("window.__hold.release()")
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
    counts, drawer, tid = _edit_refresh_hold_the_reads(page, base, made)
    _edit_refresh_second_edit(page, base, drawer, tid)
    _edit_refresh_rows_after_release(page, counts, drawer, tid)
