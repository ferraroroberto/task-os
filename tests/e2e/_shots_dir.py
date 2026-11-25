"""Where the ``shots`` fixture saves screenshots.

``docs/screenshots/`` is the committed gallery. A run whose rendering is not the
gallery's (the gate's WebKit request-budget stage) names a scratch folder in
``TASKOS_SHOTS_DIR`` so it never writes into a tracked folder.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

SHOTS_DIR_ENV = "TASKOS_SHOTS_DIR"


def resolve_shots_dir(environ: Mapping[str, str], default: Path) -> Path:
    """The override folder when the environment names one, else the gallery."""
    override = environ.get(SHOTS_DIR_ENV, "").strip()
    return Path(override) if override else default
