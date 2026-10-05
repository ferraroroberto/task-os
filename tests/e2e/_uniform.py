"""The app's two shared control styles, pinned by computed style (#357).

Every icon-only button draws one way: no fill, border or shadow at rest, one
glyph size, an invisible >=44px target and a visible focus ring. Every
reference pill (folder, AI conversation, issue, link) draws the AI pill's way.
The design review never opens a drawer, so these rendered facts are measured
here, on the views a story already walks.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Locator, Page

# Vendored controls keep the glyph size their own component ships (the header
# toggles and the modal close draw `--icon-title`); they still owe the rest.
_VENDORED_GLYPH = (".home-toggle", ".detail-close")

_ICON_BUTTONS_JS = """(root, vendored) => {
  const clear = c => !c || c === 'transparent' || /rgba\\([^)]*,\\s*0\\)$/.test(c);
  const shown = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const out = [];
  for (const b of root.querySelectorAll('button')) {
    if (!shown(b) || !b.querySelector(':scope svg.icon')) continue;
    // icon-only: no visible text anywhere inside it
    const text = [...b.querySelectorAll('*')].concat([b]).some(e =>
      [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && shown(e));
    if (text) continue;
    // at rest only: a pressed, current, expanded or recording button is a state
    if (b.matches('[aria-pressed="true"], [aria-current], [aria-expanded="true"], .is-recording, .is-on')) continue;
    const s = getComputedStyle(b), r = b.getBoundingClientRect();
    const sides = ['Top', 'Right', 'Bottom', 'Left'];
    const border = sides.some(k => parseFloat(s['border' + k + 'Width']) > 0
      && s['border' + k + 'Style'] !== 'none' && !clear(s['border' + k + 'Color']));
    const grow = { left: 0, right: 0, top: 0, bottom: 0 };
    for (const w of ['::before', '::after']) {
      const p = getComputedStyle(b, w);
      if (p.content === 'none' || p.position !== 'absolute') continue;
      for (const k of Object.keys(grow)) {
        const v = parseFloat(p[k]);
        if (Number.isFinite(v) && v < 0) grow[k] = Math.max(grow[k], -v);
      }
    }
    const g = b.querySelector(':scope svg.icon').getBoundingClientRect();
    out.push({
      name: b.getAttribute('aria-label') || b.title || b.className,
      cls: b.className,
      vendored: vendored.some(v => b.matches(v)),
      bg: s.backgroundColor, filled: !clear(s.backgroundColor), border,
      shadow: s.boxShadow !== 'none',
      hitW: r.width + grow.left + grow.right, hitH: r.height + grow.top + grow.bottom,
      glyph: Math.round(g.width),
    });
  }
  return out;
}"""

_PILL_JS = """el => { const s = getComputedStyle(el), r = el.getBoundingClientRect();
  return { height: Math.round(r.height), radius: s.borderTopLeftRadius,
    padding: s.paddingTop + ' ' + s.paddingLeft, font: s.fontSize, weight: s.fontWeight,
    bg: s.backgroundColor, border: s.borderTopWidth + ' ' + s.borderTopStyle + ' ' + s.borderTopColor,
    color: s.color }; }"""


def icon_buttons(page: Page, scope: str = "body") -> list[dict[str, Any]]:
    """Every visible icon-only button under `scope`, measured at rest."""
    page.mouse.move(0, 0)                         # no hover on anything measured
    return page.locator(scope).first.evaluate(_ICON_BUTTONS_JS, list(_VENDORED_GLYPH))


def assert_icon_buttons_uniform(page: Page, scope: str = "body", min_count: int = 1) -> list[dict[str, Any]]:
    """No fill, border or shadow at rest, a >=44px target, one glyph size."""
    found = icon_buttons(page, scope)
    assert len(found) >= min_count, (scope, found)
    painted = [b for b in found if b["filled"] or b["border"] or b["shadow"]]
    assert not painted, "icon buttons painted at rest: " + repr(painted)
    small = [b for b in found if min(b["hitW"], b["hitH"]) < 43.5]
    assert not small, "icon buttons under the 44px target: " + repr(small)
    glyphs = {b["glyph"] for b in found if not b["vendored"]}
    assert len(glyphs) <= 1, "icon buttons draw more than one glyph size: " + repr(found)
    return found


def assert_focus_ring(page: Page, button: Locator) -> None:
    """Keyboard focus on an icon button draws a visible outline."""
    page.keyboard.press("Shift")                  # keyboard modality → :focus-visible
    button.focus()
    style = button.evaluate("el => { const s = getComputedStyle(el);"
                            " return [el.matches(':focus-visible'), s.outlineStyle, parseFloat(s.outlineWidth)]; }")
    assert style[0] and style[1] != "none" and style[2] >= 2, style
    button.blur()


def pill_style(chip: Locator) -> dict[str, Any]:
    """The computed look of one reference pill."""
    return chip.evaluate(_PILL_JS)
