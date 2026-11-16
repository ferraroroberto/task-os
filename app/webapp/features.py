"""Available features at runtime — what a switch does to the running app.

``src/features.py`` owns the table of blocks and the config key; this module owns
the three things a switch changes while the process is up:

- :func:`apply_features` — start the background services of every block that is on
  and stop those of every block that is off (idempotent, so the lifespan and a
  toggle both call it);
- :func:`feature_rows` — each block's state for Settings: on / off, and
  *unavailable* with the reason when its dependency is missing on this machine
  (read from the services' own status, never decided here);
- :func:`off_section` — the stand-in a ``GET /api/status`` section becomes while
  its block is off, so every row reads "off" with the one reason.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from src.features import FEATURES, OFF_REASON

logger = logging.getLogger(__name__)

#: The services with a background thread, by block. Every other service is a
#: client with nothing to keep running: the routes and the UI are its only surface.
THREADED: dict[str, tuple[str, ...]] = {
    "issues": ("issues",),
    "email": ("capture",),
    "mirror": ("mirror", "backup"),
}


def apply_features(app: FastAPI) -> None:
    """Start the threaded services of the blocks that are on, stop those of the blocks that are off."""
    off = app.state.config.features_off
    for key, names in THREADED.items():
        for name in names:
            service = getattr(app.state, name, None)
            if service is None:
                continue
            if key in off:
                service.stop()
            else:
                service.start()
    if off:
        logger.info("ℹ️ features: off on this machine — %s", ", ".join(sorted(off)))


def off_section(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """A status section for a switched-off block."""
    return {"enabled": False, "configured": False, "reason": OFF_REASON, "feature_off": True, **(extra or {})}


def _problem(*sections: dict[str, Any] | None) -> str | None:
    """The first reason among ``sections`` when none of them is on, else ``None``.

    A section is on when it says ``enabled`` or ``configured``; one that says neither,
    or is missing, is the block's dependency being absent.
    """
    reasons: list[str] = []
    for section in sections:
        if section and (section.get("enabled") or section.get("configured")):
            return None
        reasons.append(str((section or {}).get("reason") or "not started"))
    return reasons[0] if reasons else None


def unavailable_reason(app: FastAPI, key: str) -> str | None:
    """Why block ``key`` cannot work on this machine whatever its switch says, else ``None``.

    Only blocks with a dependency can be unavailable: the time tracker is the app's
    own data. Reads what each service already knows from its config and attributes —
    no fetch, no probe — so a switched-off block is never touched (the caller skips it).
    """
    state = app.state
    if key == "calendar":
        return None if app.state.config.calendar.ics_url.strip() else "calendar.ics_url is blank — no calendar connected"
    if key == "issues":
        return None if state.issues.enabled else state.issues.reason
    if key == "email":
        return _problem(state.folder_explorer.summary())
    if key == "ai":
        return _problem(state.ai.status(), state.voice.status())
    if key == "mirror":
        return _problem(
            {"enabled": state.mirror.enabled, "reason": state.mirror.reason},
            {"enabled": state.backup.enabled, "reason": state.backup.reason},
        )
    return None


def feature_rows(app: FastAPI) -> list[dict[str, Any]]:
    """Every block, in order: ``{key, label, summary, enabled, available, reason}``."""
    off = app.state.config.features_off
    rows: list[dict[str, Any]] = []
    for f in FEATURES:
        # A block that is off is not asked: the answer would touch its service.
        reason = None if f.key in off else unavailable_reason(app, f.key)
        rows.append({
            "key": f.key, "label": f.label, "summary": f.summary,
            "enabled": f.key not in off, "available": reason is None, "reason": reason,
        })
    return rows
