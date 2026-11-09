"""Structural pins for the header raster bisect at an installed iOS app's cold start.

On an iPhone home-screen app the header card renders soft, with faint smeared
ghost copies of its text, after a cold launch, while the rows below it are
sharp. Desktop Chromium and WebKit cannot show it, so only the device decides.

This build is a regression bisect: every vendored front-end component is held
at the content it had before the re-vendor wave that preceded the symptom, the
rest of the app at HEAD. These checks pin that state, so a stray re-vendor
cannot silently end the experiment before the device answers, and that the
header itself carries no layer-promoting property at rest.
"""

from __future__ import annotations

import re
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "_vendored"
NAV_CSS = VENDORED / "nav" / "nav-tabs.css"
NAV_JS = VENDORED / "nav" / "nav-tabs.js"
HEADER_CSS = (VENDORED / "home-head" / "home-head.css", VENDORED / "card" / "card.css")

# A property that promotes an element to its own compositing layer, or makes
# WebKit composite it differently.
LAYER_PROPERTIES = ("transform", "will-change", "filter", "backdrop-filter", "opacity", "contain")


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_bisect_nav_has_none_of_the_later_settle_machinery() -> None:
    js = NAV_JS.read_text(encoding="utf-8")
    css = _strip_comments(NAV_CSS.read_text(encoding="utf-8"))
    for marker in ("watchGlassSettle", "recompositeGlass", "ResizeObserver", "content-repaint"):
        assert marker not in js, marker
    for marker in ("glass-rebuild", "content-repaint", "translateZ(0); will-change: auto"):
        assert marker not in css, marker
    # The launch-time viewport expansion and the standalone lvh anchoring
    # predate the bisect window, so they stay.
    assert "function expandStandaloneViewport()" in js


def test_bisect_buttons_carry_no_hit_area_pseudo_element() -> None:
    css = _strip_comments((VENDORED / "button" / "button.css").read_text(encoding="utf-8"))
    assert ".button-ghost::before" not in css
    assert ".button-surface::before" not in css


def test_header_card_has_no_layer_property_at_rest() -> None:
    for path in HEADER_CSS:
        css = _strip_comments(path.read_text(encoding="utf-8"))
        for prop in LAYER_PROPERTIES:
            assert not re.search(rf"(?<![-\w]){re.escape(prop)}\s*:", css), f"{path.name}: {prop}"
