"""Generate the PWA / tray / Stream-Deck icon set from the fleet brand generator.

Thin caller onto ``project-scaffolding``'s ``brand_gen.render_set()`` — the
master art is the vendored Lucide ``list-checks`` glyph in ``brand/``
(lucide-static v1.23.0, ISC), rendered on the fleet's dark tile. The scaffold
checkout is resolved as this repo's sibling; ``PROJECT_SCAFFOLDING_DIR``
overrides it.

Writes ``app/webapp/static/icons/{favicon.ico,icon-180.png,icon-192.png,
icon-512.png,icon-512-maskable.png}``, ``assets/tray/task-os.ico`` and
``assets/stream-deck/task-os-144.png``. All committed — the runtime never
imports ``resvg-py``.

Usage:
    .venv/Scripts/python.exe scripts/gen_icons.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_ICONS_DIR = PROJECT_ROOT / "app" / "webapp" / "static" / "icons"
MASTER_SVG = PROJECT_ROOT / "brand" / "list-checks.svg"


def _scaffolding_dir() -> Path:
    override = os.environ.get("PROJECT_SCAFFOLDING_DIR", "").strip()
    return Path(override) if override else PROJECT_ROOT.parent / "project-scaffolding"


def main() -> int:
    scaffolding = _scaffolding_dir()
    scripts_dir = scaffolding / "scripts"
    if not (scripts_dir / "brand_gen.py").is_file():
        print(
            f"project-scaffolding not found at {scaffolding} — clone it beside this "
            "repo, or point PROJECT_SCAFFOLDING_DIR at it.",
            file=sys.stderr,
        )
        return 1
    sys.path.insert(0, str(scripts_dir))
    from brand_gen import render_set  # noqa: PLC0415 — resolved above

    render_set(
        master=MASTER_SVG,
        out_dir=STATIC_ICONS_DIR,
        tray_out_dir=PROJECT_ROOT / "assets" / "tray",
        stream_deck_out_dir=PROJECT_ROOT / "assets" / "stream-deck",
        project_slug="task-os",
    )
    print(f"icons written under {STATIC_ICONS_DIR} and {PROJECT_ROOT / 'assets'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
