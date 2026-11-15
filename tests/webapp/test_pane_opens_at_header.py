"""A pane opens at a heading, not at a collapsed section far down the list.

The Today list begins with an unheaded group, so the first heading the served
markup would otherwise hold is a disclosure card's title below the fold; the
design review reads that as a pane that does not open at its top. The pane
carries its own visually hidden heading ahead of everything else.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static"


def _pane_markup(pane_id: str) -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    start = html.index(f'<section id="{pane_id}"')
    return html[start:html.index("</section>", start)]


def test_today_pane_leads_with_its_own_heading() -> None:
    pane = _pane_markup("paneToday")
    body = re.sub(r"<!--.*?-->", "", pane, flags=re.S)
    first_tag = re.search(r'<div class="pane-body">\s*<(\w+)([^>]*)>', body)
    assert first_tag is not None
    assert first_tag.group(1) == "h2" and "visually-hidden" in first_tag.group(2)


def test_visually_hidden_is_not_display_none() -> None:
    css = (STATIC / "styles" / "components.css").read_text(encoding="utf-8")
    rule = css[css.index(".visually-hidden {"):].split("}", 1)[0]
    assert "display" not in rule and "position: absolute" in rule
