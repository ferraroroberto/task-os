"""The installed phone app starts its content 20px below the safe area.

iOS renders the header card soft when the page content starts right at the
safe-area edge of the standalone app; 20px lower was picked as sharp on the
device. Desktop engines cannot show the softness, so this pins the structure:
the offset has one home, it is plain padding on top of the safe area, it is
scoped to standalone on a phone, and the rule adds no layer.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static"


def test_app_applies_the_offset_in_the_installed_phone_app_only() -> None:
    css = (STATIC / "styles" / "base.css").read_text(encoding="utf-8")
    assert css.count("--standalone-head-offset: 20px;") == 1
    block = re.search(
        r"@media \(display-mode: standalone\) and \(pointer: coarse\) and \(max-width: 520px\) \{(.*?)\n\}",
        css,
        flags=re.S,
    )
    assert block, "the offset rule must be scoped to the installed phone app"
    body = block.group(1)
    assert "padding-top: calc(env(safe-area-inset-top, 0px) + var(--standalone-head-offset));" in body
    for prop in ("transform", "will-change", "filter"):
        assert prop not in body, prop
