"""The phone drawer's pinned comment bar stays clear of the screen's rounded corners.

The installed iOS app reports a zero safe-area inset (`viewport-fit=auto`), so
the bar cannot lean on `env()` alone: it keeps the nav pill's edge clearance on
the left, right and bottom, and lets a larger reported inset win. A real device
is the proof; this pins the rule so a later edit cannot shrink it back.
"""

from __future__ import annotations

import re
from pathlib import Path

DRAWER_CSS = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "styles" / "drawer.css"

_CLEARANCE = "var(--bottom-tabs-margin, 21px)"


def _pinned_composer_rule() -> str:
    css = DRAWER_CSS.read_text(encoding="utf-8")
    match = re.search(r"^\.comment-composer-pinned\s*\{(.*?)\n\}", css, re.S | re.M)
    assert match, "the pinned composer rule is gone"
    return match.group(1)


def test_pinned_composer_keeps_edge_clearance_on_three_sides() -> None:
    rule = _pinned_composer_rule()
    padding = re.search(r"padding:(.*?);", rule, re.S)
    assert padding, rule
    for side in ("right", "left"):
        assert f"max({_CLEARANCE}, env(safe-area-inset-{side}, 0px))" in padding.group(1), side
    assert f"max({_CLEARANCE}, calc(var(--space-sm) + env(safe-area-inset-bottom, 0px)))" in padding.group(1)
