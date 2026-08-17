"""One definition of the Windows ``CREATE_NO_WINDOW`` subprocess flag.

Every ``subprocess`` spawn that launches an external console executable
(``git``, ``netstat``, ``taskkill``, ``powershell.exe``, ``tailscale``, a
helper script, ...) must pass ``creationflags=NO_WINDOW`` on Windows. A parent
with no console of its own -- a ``pythonw`` tray, a scheduled task, a daemon,
an agent's captured shell -- otherwise makes Windows allocate a fresh console
per child, flashing a window on screen; on a poll loop that reads as malware
or a stuck app. See ``CLAUDE.md`` -> "Windows console-subprocess suppression
(``CREATE_NO_WINDOW``)" (project-scaffolding#13, fleet-config#399).

Import the flag from here instead of re-deriving the
``sys.platform == "win32"`` ternary at each call site::

    from src.no_window import NO_WINDOW

    subprocess.run([...], creationflags=NO_WINDOW)

**Vendor-verbatim modules are the one exception and keep a local definition.**
A file copied byte-identical into adopter repos cannot import a module of this
repo's -- the copy would not resolve, and the hash-verified bytes must stay
self-contained. Two such files therefore derive the flag themselves on
purpose, and that is not drift: ``tests/e2e/_browser_sweep.py`` and
``scripts/classify_e2e.py`` (both listed in
``scripts/verify-before-ship.ps1``'s ``$VendoredModules``).

Stdlib-only and side-effect-free, so a standalone script launched outside the
project venv can import it after putting the repo root on ``sys.path``.
"""

from __future__ import annotations

import subprocess
import sys

#: ``subprocess.CREATE_NO_WINDOW`` on Windows, ``0`` (a no-op) elsewhere, so
#: the same call site is portable without a per-platform branch.
NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

__all__ = ["NO_WINDOW"]
