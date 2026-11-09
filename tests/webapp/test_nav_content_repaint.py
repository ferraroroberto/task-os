"""Structural check for the header raster at an installed iOS app's cold start.

On an iPhone home-screen app the header card can stay soft after a cold
launch while the rows below it are sharp. The working explanation (not
reproducible in desktop Chromium or WebKit): WebKit keeps the page's root
tiles rastered from a frame taken while the launch viewport was still
growing, and only content that repaints later (rows filled in by data) is
re-rastered. The static header never repaints.

The fix rides the nav's settle watcher, which already fires once the
viewport stops resizing (visualViewport) and on every return to the
foreground (visibilitychange, pageshow): on the same one-frame rebuild it
sets a paint-only change on the page content, so WebKit repaints the content
tiles at their settled scale. These checks pin that wiring, and that the
header itself carries no layer-promoting property at rest. A desktop engine
cannot show the blur, so only the device proves the fix.
"""

from __future__ import annotations

import re
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "_vendored"
NAV_CSS = VENDORED / "nav" / "nav-tabs.css"
NAV_JS = VENDORED / "nav" / "nav-tabs.js"
HEADER_CSS = (VENDORED / "home-head" / "home-head.css", VENDORED / "card" / "card.css")

# A property that promotes an element to its own compositing layer, or makes
# WebKit composite it differently; the content repaint must never use one.
LAYER_PROPERTIES = ("transform", "will-change", "filter", "backdrop-filter", "opacity", "contain")


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _function_body(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    depth, i = 0, js.index("{", start)
    for j in range(i, len(js)):
        depth += {"{": 1, "}": -1}.get(js[j], 0)
        if depth == 0:
            return js[i : j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def test_settle_rebuild_also_repaints_the_page_content() -> None:
    js = NAV_JS.read_text(encoding="utf-8")
    body = _function_body(js, "recompositeGlass")
    assert "document.documentElement" in body
    assert "classList.add('content-repaint')" in body
    assert "classList.remove('content-repaint')" in body
    # The settle triggers: a quiet viewport and a return to the foreground.
    watch = _function_body(js, "watchGlassSettle")
    for trigger in ("visualViewport.addEventListener('resize'", "'visibilitychange'", "'pageshow'"):
        assert trigger in watch, trigger


def test_content_repaint_rule_is_paint_only() -> None:
    css = _strip_comments(NAV_CSS.read_text(encoding="utf-8"))
    rules = re.findall(r"html\.content-repaint\s+\.app\s*\{([^}]*)\}", css)
    assert rules, "nav-tabs.css has no html.content-repaint .app rule"
    props = [d.split(":", 1)[0].strip() for rule in rules for d in rule.split(";") if d.strip()]
    assert props and all(p.startswith("outline") for p in props), props


def test_header_card_has_no_layer_property_at_rest() -> None:
    for path in HEADER_CSS:
        css = _strip_comments(path.read_text(encoding="utf-8"))
        for prop in LAYER_PROPERTIES:
            assert not re.search(rf"(?<![-\w]){re.escape(prop)}\s*:", css), f"{path.name}: {prop}"
