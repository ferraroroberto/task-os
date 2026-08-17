"""Shared constants for the routers: paths + the once-per-process build identity."""

from __future__ import annotations

from pathlib import Path

from src.static_versioning import BuildInfo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = PROJECT_ROOT / "app" / "webapp" / "static"

# Computed once at import: git SHA + fleet asset hash + build time. The tray
# restarts the webapp on every code change (restart recipe in CLAUDE.md), so
# there is no watcher and no per-request work.
BUILD_INFO = BuildInfo(STATIC_DIR, PROJECT_ROOT)
