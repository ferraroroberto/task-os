"""The one writer for runtime files whose location a caller names.

A log, a config, a backup or an export lands at a path that is a parameter, a
config value or an environment override, so the runtime-write ratchet cannot
resolve it from the source. Every such write goes through this module, which
refuses at run time any path under a code folder: runtime output belongs in
``data/``, ``config/``, ``webapp/`` (gitignored live state), the synced folders
or a temp dir, never beside the code that writes it.
"""

from __future__ import annotations

import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
#: The runtime-write ratchet's default ``code_folders`` (``.fleet.toml`` does not override it).
CODE_FOLDERS = ("src", "app", "scripts", "hooks", "skills")


class CodeFolderWrite(ValueError):
    """A write was aimed at a path inside one of the repo's code folders."""


def checked(path: Path | str) -> Path:
    """``path`` unchanged, or :class:`CodeFolderWrite` when it resolves under a code folder."""
    target = Path(path)
    resolved = target.resolve()
    for folder in CODE_FOLDERS:
        if resolved.is_relative_to(REPO_ROOT / folder):
            raise CodeFolderWrite(f"refusing to write {resolved}: it is inside the code folder {folder}/")
    return target


def make_dir(path: Path | str, *, parents: bool = True, exist_ok: bool = True) -> Path:
    """Create the folder ``path``."""
    target = checked(path)
    # runtime-write-exempt: checked() above refuses any path under a code folder
    target.mkdir(parents=parents, exist_ok=exist_ok)
    return target


def save_text(path: Path | str, text: str, *, newline: str | None = None) -> Path:
    """Write ``text`` to ``path`` as UTF-8."""
    target = checked(path)
    # runtime-write-exempt: checked() above refuses any path under a code folder
    target.write_text(text, encoding="utf-8", newline=newline)
    return target


def open_append(path: Path | str, *, binary: bool = False) -> IO[str] | IO[bytes]:
    """Open ``path`` for appending (UTF-8 text unless ``binary``); the caller closes it."""
    target = checked(path)
    # runtime-write-exempt: checked() above refuses any path under a code folder
    return target.open("ab") if binary else target.open("a", encoding="utf-8")


def rotating_file_handler(path: Path | str, *, max_bytes: int, backups: int) -> RotatingFileHandler:
    """A rotating UTF-8 log handler on ``path``."""
    target = checked(path)
    # runtime-write-exempt: checked() above refuses any path under a code folder
    return RotatingFileHandler(target, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")


def copy_file(source: Path | str, destination: Path | str) -> Path:
    """Copy ``source`` to ``destination``, keeping its timestamps."""
    target = checked(destination)
    # runtime-write-exempt: checked() above refuses any path under a code folder
    shutil.copy2(source, target)
    return target
