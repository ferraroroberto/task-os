"""The e2e stories' UI checks and gestures, shared by every story.

Contrast and field-boundary measurements (the design review's COLOR-03 and
LAYOUT-03, read from the computed style), the synthetic row swipe, and the
openers for the filter sheet, the Settings sheets and the drawer's More fields
— each the way a user reaches it. The capture rules (`shot`, `settle`) and the
disposable instances stay in `conftest.py`.
"""

from __future__ import annotations

import urllib.parse
from datetime import date

from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import _get

# WCAG 1.4.11's floor for a field boundary, and how /design-review's COLOR-03
# finds one: the field's own border, else its inset 1px edge, else the bordered
# wrapper hugging it (two levels up, at most twice its height), else its fill.
# Read from the computed style, so an engine that drops a declaration (WebKit
# paints no box-shadow on a native <select>, #339) fails here as it renders.
_BOUNDARY_MIN = 3.0
# The colour maths both contrast checks share: a CSS colour as RGBA (through a
# canvas, so any syntax the engine paints), compositing, WCAG luminance and
# ratio, and the background an element sits on, composited up its ancestors.
_COLOR_JS = """
  const cv = document.createElement('canvas').getContext('2d');
  const rgba = (c) => { cv.clearRect(0,0,1,1); cv.fillStyle = '#000'; cv.fillStyle = c; cv.fillRect(0,0,1,1);
    const d = cv.getImageData(0,0,1,1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (f, b) => [0,1,2].map(i => f[i] * f[3] + b[i] * (1 - f[3])).concat([1]);
  const lum = (c) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bgOf = (el) => { const stack = []; for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = rgba(getComputedStyle(n).backgroundColor); if (c[3] > 0) { stack.push(c); if (c[3] >= 0.999) break; } }
    let base = [255, 255, 255, 1]; for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base); return base; };
"""
_CONTROL_BOUNDARIES_JS = """(root) => {""" + _COLOR_JS + """
  const border = (s) => (parseFloat(s.borderTopWidth) || 0) > 0 && rgba(s.borderTopColor)[3] > 0 ? rgba(s.borderTopColor) : null;
  const inset = (s) => { const m = /^(rgba?\\([^)]*\\)) 0px 0px 0px [1-9][\\d.]*px inset$/.exec(s.boxShadow); return m ? rgba(m[1]) : null; };
  const out = [];
  root.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea').forEach((el) => {
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
    let host = el, s = getComputedStyle(el);
    if (!border(s) && !inset(s) && rgba(s.backgroundColor)[3] === 0) {
      for (let a = el.parentElement, i = 0; a && i < 2; a = a.parentElement, i++) { const as = getComputedStyle(a);
        if (border(as) && a.getBoundingClientRect().height <= r.height * 2 + 2) { host = a; s = as; break; } } }
    const surface = bgOf(host.parentElement || host);
    const edge = border(s) || inset(s) || (rgba(s.backgroundColor)[3] > 0 ? rgba(s.backgroundColor) : null);
    out.push({field: el.id || el.className || el.tagName, ratio: edge ? Math.round(ratio(over(edge, surface), surface) * 100) / 100 : 1});
  });
  return out;
}"""


#: What counts as a row's control, as the design review's LAYOUT-03 counts it.
_ROW_CONTROLS = 'a[href], button, select, input:not([type="hidden"]), textarea, [role=button]'

#: The action-row budget besides the row itself: a leading toggle, one extra
#: action and a trailing accessory (design.md action-row).
ROW_CONTROLS_MAX = 3

_ROW_EXTRAS_JS = """(rows, sel) => rows.map(row => {
  const vis = c => { const r = c.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ctl = [...row.querySelectorAll(sel)].filter(vis);
  const rw = row.getBoundingClientRect().width;
  const main = ctl.reduce((a, c) => (!a || c.getBoundingClientRect().width > a.getBoundingClientRect().width) ? c : a, null);
  return (main && main.getBoundingClientRect().width >= rw * 0.5) ? ctl.length - 1 : ctl.length;
})"""


def assert_action_row_budget(rows: Locator) -> list[int]:
    """Every row in *rows* carries at most the action-row budget of controls (#350).

    Counted the way the design review's LAYOUT-03 counts them: every visible
    interactive element in the row, minus a main one that spans half of it.
    Returns the per-row counts.
    """
    counts = rows.evaluate_all(_ROW_EXTRAS_JS, _ROW_CONTROLS)
    assert counts and max(counts) <= ROW_CONTROLS_MAX, f"rows over the action-row budget: {counts}"
    return counts


_TEXT_CONTRAST_JS = """(el) => {""" + _COLOR_JS + """
  const bg = bgOf(el);
  return Math.round(ratio(over(rgba(getComputedStyle(el).color), bg), bg) * 100) / 100;
}"""


def text_contrast(text: Locator) -> float:
    """WCAG contrast of *text*'s colour against the background it sits on (#339)."""
    return text.evaluate(_TEXT_CONTRAST_JS)


# A sideways touch on a row, as synthetic Pointer Events (swipe.js, #311):
# `row.locator(".trow-main").evaluate(SWIPE_JS, [x0, x1])`. It proves the wiring
# — which action a side runs — not the feel of the gesture, which is the
# owner's iPhone walk.
SWIPE_JS = """(el, [x0, x1]) => {
  const r = el.getBoundingClientRect();
  const y = r.top + r.height / 2;
  const fire = (type, x) => el.dispatchEvent(new PointerEvent(type, {
    pointerId: 7, pointerType: 'touch', isPrimary: true, bubbles: true, clientX: x, clientY: y }));
  fire('pointerdown', x0);
  for (let i = 1; i <= 8; i++) fire('pointermove', x0 + (x1 - x0) * i / 8);
  fire('pointerup', x1);
}"""


def open_filter_sheet(page: Page, pane: str) -> Locator:
    """Open the one filter sheet from *pane*'s filter button, like a user would (#395).

    *pane* is the pane's id (``paneBoard``, ``paneToday``, ``paneJournal``,
    ``paneSearch``); the sheet is the shared ``#filterSheet`` dialog, drawn for
    the tab that opened it. Already open → returned as it is.
    """
    sheet = page.locator("#filterSheet")
    if not sheet.evaluate("el => el.open"):
        page.locator(f"#{pane} .filter-open").click()
    expect(sheet).to_be_visible()
    return sheet


def close_filter_sheet(page: Page) -> None:
    """Close the filter sheet with its Done button (it is modal: the page under
    it takes no clicks while it is up)."""
    sheet = page.locator("#filterSheet")
    if sheet.evaluate("el => el.open"):
        sheet.locator(".filter-done").click()
    expect(sheet).to_be_hidden()


def filter_button(page: Page, pane: str) -> Locator:
    """*pane*'s filter button: its count and its name say what is on (#395)."""
    return page.locator(f"#{pane} .filter-open")


def board_mode(page: Page, mode: str) -> None:
    """Press the Board's Week · Status segment (#396), like a user would.

    Week is the default; the pick is remembered on the device, so one press per
    browser context holds across reloads and tab presses. The Board tab must be
    showing.
    """
    seg = page.locator(f"#paneBoard .board-modes [data-mode='{mode}']")
    seg.click()
    expect(seg).to_have_attribute("aria-pressed", "true")
    expect(page.locator(f"#paneBoard .board-{mode}")).to_be_visible()


def open_settings_sheet(page: Page, key: str, *, tap: bool = False) -> Locator:
    """Settings → one row's sheet, like a user would (#397).

    Presses the header gear when Settings is not up, then the row whose sheet
    is *key* (``issues``, ``mirror``, ``archive``, … — the row's
    ``data-settings-sheet``). Returns the sheet's body, which carries the id of
    the Settings card it replaced (``#issuesCard`` …), so a story reads the same
    ids it always did. *tap* presses with touch, for the phone legs.
    """
    press = (lambda loc: loc.tap()) if tap else (lambda loc: loc.click())
    if not page.locator("#paneSettings").is_visible():
        # The shell's markup ships a lit tab and the gear before app.js has run,
        # so a press on a page that has only just navigated (a sign-in) lands on
        # a button with no handler yet. The build line is empty until boot has
        # bound the gear and fetched /api/version: the first sign of a live app.
        expect(page.locator("#buildReadout")).to_contain_text("Build:")
        press(page.locator("#settingsBtn"))
        expect(page.locator("#paneSettings")).to_be_visible()
    press(page.locator(f"#paneSettings [data-settings-sheet='{key}']"))
    body = page.locator(f"#settingsSheet .settings-sheet[data-sheet='{key}']")
    expect(body).to_be_visible()
    return body


def close_settings_sheet(page: Page) -> None:
    """Close the open Settings sheet with its Done button (#397)."""
    sheet = page.locator("#settingsSheet")
    if sheet.is_visible():
        sheet.locator(".settings-sheet-done").click()
    expect(sheet).to_be_hidden()


def assert_control_boundaries(scope: Locator) -> list[float]:
    """Every visible field under *scope* draws a boundary of at least 3:1 against its surface.

    Returns the measured ratios (so a story can name them); fails on the first
    field under the floor, or when *scope* holds no visible field at all.
    """
    found = scope.evaluate(_CONTROL_BOUNDARIES_JS)
    assert found, "no visible input, select or textarea to measure"
    low = [f for f in found if f["ratio"] < _BOUNDARY_MIN]
    assert not low, f"field boundary under {_BOUNDARY_MIN}:1 (WCAG 1.4.11): {low}"
    return [f["ratio"] for f in found]


#: The date sheet's re-date phrases, push-outs first (#391) — snooze.js DUE_OPTIONS.
DUE_SHEET = [("tomorrow", "Tomorrow"), ("this weekend", "This weekend"), ("next week", "Next week"), ("today", "Today")]


def assert_date_sheet(menu: Locator, base: str) -> None:
    """The re-date sheet lists its phrases push-outs first, each beside the
    date the server resolves it to today (#391) — the date a pick writes."""
    phrases = ",".join(p for p, _ in DUE_SHEET)
    resolved = _get(base, "/api/dates?phrases=" + urllib.parse.quote(phrases))["dates"]
    days = [date.fromisoformat(resolved[p]) for p, _ in DUE_SHEET]
    opts = menu.locator(".snooze-opt[data-phrase]")
    expect(opts.locator(".snooze-opt-label")).to_have_text([label for _, label in DUE_SHEET])
    expect(opts.locator(".snooze-opt-date")).to_have_text([f"{d:%a} {d.day} {d:%b}" for d in days])


def assert_on_crumb_line(drawer: Locator, *, may_wrap: bool = False) -> None:
    """The drawer head's parent tools sit on the breadcrumb's line (#486), inside
    the drawer, clear of the crumbs. `may_wrap`: a phone, where a long trail
    pushes the tools under it — still clear of the crumbs and still inside."""
    crumbs = drawer.locator(".drawer-crumbs").bounding_box()
    box = drawer.bounding_box()
    tools = drawer.locator(".drawer-parent-tools button")
    assert crumbs and box and tools.count(), (crumbs, box)
    first = tools.first.bounding_box()
    for i in range(tools.count()):
        b = tools.nth(i).bounding_box()
        assert b["x"] >= box["x"] - 0.5 and b["x"] + b["width"] <= box["x"] + box["width"] + 0.5, (i, b, box)
    same_line = abs((first["y"] + first["height"] / 2) - (crumbs["y"] + crumbs["height"] / 2)) <= 4
    beside = first["x"] >= crumbs["x"] + crumbs["width"] - 0.5
    below = first["y"] >= crumbs["y"] + crumbs["height"] - 0.5
    assert (same_line and beside) or (may_wrap and below), ("crumbs", crumbs, "tools", first)


def open_more_fields(drawer: Locator) -> Locator:
    """Open the drawer's **More fields** (#394) and return the disclosure.

    The rare fields and the editors (starts, repeat, person, code,
    folder, link editor, blockers, children, issue panel) live there, closed
    by default. It stays open for the page's life once opened, so on a page
    that already opened it this only checks; a fresh load closes it again.
    """
    more = drawer.locator("details.drawer-more")
    expect(more).to_be_attached()
    if more.get_attribute("open") is None:
        more.locator("summary").first.click()
    expect(more).to_have_attribute("open", "")
    return more
