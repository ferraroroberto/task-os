"""Thin launcher — the one entrypoint ``tray.bat`` / ``webapp.bat`` invoke.

Usage:
    python launcher.py            # same as `tray`
    python launcher.py tray       # tray icon owning the webapp on :8448
    python launcher.py webapp     # foreground uvicorn (dev / headless box)

Puts its own folder on ``sys.path`` so the top-level packages (``app``,
``src``, ``scripts``) resolve without an outer namespace — the folder is the
root of its own repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def main(argv: list[str]) -> int:
    from src.config import load_config
    from src.logger import configure_logging

    configure_logging()
    command = argv[1] if len(argv) > 1 else "tray"
    config = load_config()

    if command == "tray":
        from app.tray.tray import run_tray

        return run_tray(config)

    if command == "webapp":
        import uvicorn

        from app.webapp.event_loop import LOOP_FACTORY

        uvicorn.run(
            "app.webapp.server:app",
            host="0.0.0.0",
            port=config.port,
            log_level="info",
            loop=LOOP_FACTORY,
        )
        return 0

    print(f"unknown command {command!r} — use: tray | webapp", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
