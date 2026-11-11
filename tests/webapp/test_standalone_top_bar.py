"""The installed phone app follows the vendored nav's translucent top bar.

The vendored nav paints the top glass and the pages carry the head that goes
with it: `black-translucent` with `viewport-fit=auto`, `theme-color` following
the page colour. Content starts at the safe area with no fixed offset of the
app's own. Desktop engines cannot show standalone iOS painting, so this pins
the structure and the device is the proof.
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static"

_STATUS_BAR = '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'


def test_app_adds_no_standalone_top_offset() -> None:
    css = (STATIC / "styles" / "base.css").read_text(encoding="utf-8")
    assert "--standalone-head-offset" not in css
    assert "display-mode: standalone" not in css


def test_pages_carry_the_top_bar_head() -> None:
    for page in ("index.html", "login.html"):
        head = (STATIC / page).read_text(encoding="utf-8").split("</head>", 1)[0]
        assert _STATUS_BAR in head, page
        viewports = [line for line in head.splitlines() if '<meta name="viewport"' in line]
        assert len(viewports) == 1 and "viewport-fit=auto" in viewports[0], (page, viewports)
        assert 'name="theme-color"' in head, page
