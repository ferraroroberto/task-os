"""One logger setup for every entrypoint (webapp, tray, scripts, CLI).

``configure_logging()`` is idempotent: the first caller installs a stream
handler (when a console exists) plus a rotating file under ``data/logs/``;
later callers are no-ops. Under ``pythonw`` (the tray) ``sys.stderr`` is
``None`` — the file handler is then the *only* durable trail, which is why it
is always installed. Emoji markers are the fleet convention: ℹ️ ⚠️ ❌ ✅.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_FILE = LOG_DIR / "task-os.log"

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_CONFIGURED_FLAG = "_taskos_logging_configured"


def configure_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    """Install the console + rotating-file handlers once per process."""
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        return
    setattr(root, _CONFIGURED_FLAG, True)
    root.setLevel(level)
    formatter = logging.Formatter(_FMT, _DATEFMT)

    if sys.stderr is not None:
        try:
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    target = log_file or LOG_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # a read-only checkout must not kill startup
        root.warning("⚠️ logging: file handler unavailable (%s)", exc)


def get_logger(name: str) -> logging.Logger:
    """``logging.getLogger`` after making sure the process is configured."""
    configure_logging()
    return logging.getLogger(name)
