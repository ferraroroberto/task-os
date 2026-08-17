"""System-tray launcher — owns the task-os webapp lifecycle behind a tray icon.

Launched by ``tray.bat`` (idempotent start; ``--restart`` is the orphan-proof
reclaim-then-start owned by the shared ``tray_lifecycle.ps1``). Menu:

    Open task-os      — open the local URL in the default browser
    Copy local URL    — clipboard the local URL
    Restart webapp    — stop + start so a fresh build is picked up
    Status            — toast with the webapp state
    --
    Quit              — stop the webapp and exit

Self-heal per project-scaffolding#201 (vendored ``app/tray/watchdog.py``):
the initial spawn retries with backoff on a background thread, a health
watchdog splits *dead* (not listening → respawn, then ``rearm()`` if that
failed) from *wedged* (listening, ``/healthz`` silent → alert only), and every
attempt leaves a breadcrumb in ``webapp/watchdog.log`` — the only durable
trail under ``pythonw``, which has no ``sys.stderr``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from app.tray.single_instance import SingleInstance
from app.tray.watchdog import (
    DEFAULT_STARTUP_RETRY_DELAYS_S,
    BreadcrumbLog,
    HealthWatchdog,
    retry_with_backoff,
)
from app.webapp.manager import WebappManager, WebappManagerConfig
from src.config import AppConfig
from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TRAY_ICON = PROJECT_ROOT / "assets" / "tray" / "task-os.ico"
FALLBACK_ICON = PROJECT_ROOT / "app" / "webapp" / "static" / "icons" / "icon-512.png"
# Gitignored (*.log). Best-effort writes, rotates past ~1 MB.
WATCHDOG_LOG = PROJECT_ROOT / "webapp" / "watchdog.log"
MUTEX_NAME = r"Global\task-os-tray"


def _build_icon():
    """Lazy-import Pillow so plain CLI use never drags it in."""
    from PIL import Image

    if TRAY_ICON.exists():
        return Image.open(TRAY_ICON)
    if FALLBACK_ICON.exists():
        return Image.open(FALLBACK_ICON)
    return Image.new("RGB", (32, 32), (10, 10, 10))


def _clipboard_copy(text: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        p = subprocess.run(
            ["clip"], input=text, text=True, check=False,
            encoding="utf-8", creationflags=NO_WINDOW,
        )
        return p.returncode == 0
    except OSError as exc:
        logger.debug("clip failed: %s", exc)
        return False


def _notify(title: str, message: str) -> None:
    """Windows toast when ``winotify`` is present; always logged."""
    logger.info("🔔 %s: %s", title, message)
    if sys.platform != "win32":
        return
    try:
        from winotify import Notification  # type: ignore

        Notification(app_id="task-os", title=title, msg=message).show()
    except Exception as exc:  # noqa: BLE001 — optional dependency
        logger.debug("winotify unavailable: %s", exc)


class TrayApp:
    """Owns the webapp behind the tray icon; one instance per process."""

    def __init__(self, config: AppConfig, instance: SingleInstance) -> None:
        self.config = config
        self.instance = instance  # held for the tray's lifetime (named mutex)
        self.manager = WebappManager(WebappManagerConfig(port=config.port))
        self.wd_log = BreadcrumbLog(WATCHDOG_LOG)
        self.watchdog_stop = threading.Event()
        self.watchdog = HealthWatchdog(
            probe=self.manager.is_reachable,
            on_wedge=self._on_wedge,
            on_recover=self._on_recover,
        )
        self.starter_exc: BaseException | None = None

    # -- webapp lifecycle ---------------------------------------------------

    def _on_start_attempt_failed(self, attempt: int, exc: BaseException) -> None:
        self.wd_log(f"webapp start attempt {attempt} failed: {exc}")
        logger.warning("⚠️ webapp start attempt %d failed: %s", attempt, exc)

    def _start(self) -> None:
        try:
            retry_with_backoff(
                lambda: self.manager.start(wait=True),
                DEFAULT_STARTUP_RETRY_DELAYS_S,
                self._on_start_attempt_failed,
            )
            self.wd_log(f"webapp started at {self.manager.base_url}")
            _notify("task-os ready", self.manager.base_url)
        except Exception as exc:  # noqa: BLE001 — exhausted: loud, never silent
            self.starter_exc = exc
            self.wd_log(f"webapp start FAILED permanently: {exc}")
            logger.error("❌ webapp start failed after retries: %s", exc)
            _notify("task-os start failed", str(exc))

    def _on_wedge(self, count: int) -> None:
        if self.manager.is_port_in_use():
            # Wedged: listening but not answering. Alert only — auto-killing a
            # stuck process can mask what is actually wrong (app-launcher#386).
            msg = f"webapp on :{self.config.port} listening but not answering /healthz ({count} probes)"
            self.wd_log(f"WEDGE {msg} -- use tray.bat --restart")
            logger.error("❌ %s", msg)
            _notify("task-os webapp wedged", "Listening but not answering — use tray.bat --restart")
            return
        # Dead: not listening at all — safe to respawn.
        self.wd_log(f"webapp not listening ({count} consecutive failures) -- respawning")
        try:
            self.manager.start(wait=True)
            self.wd_log("webapp respawned successfully")
            _notify("task-os webapp respawned", self.manager.base_url)
        except Exception as exc:  # noqa: BLE001
            self.wd_log(f"webapp respawn failed: {exc}")
            logger.error("❌ webapp respawn failed: %s", exc)
            _notify("task-os respawn failed", str(exc))
            self.watchdog.rearm()  # try again next tick, don't go silent

    def _on_recover(self) -> None:
        self.wd_log("webapp health recovered")
        logger.info("✅ webapp answering /healthz again")
        _notify("task-os webapp recovered", self.manager.base_url)

    # -- menu actions ---------------------------------------------------------

    def open_local(self, icon, item) -> None:  # noqa: ARG002
        webbrowser.open(self.manager.base_url)

    def copy_local(self, icon, item) -> None:  # noqa: ARG002
        url = self.manager.base_url
        _notify("Copied local URL" if _clipboard_copy(url) else "Local URL", url)

    def restart_webapp(self, icon, item) -> None:  # noqa: ARG002
        def _do_restart() -> None:
            try:
                _notify("task-os", "Restarting webapp…")
                self.manager.restart(wait=True)
                self.wd_log("webapp restarted from tray menu")
                _notify("task-os webapp restarted", self.manager.base_url)
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ webapp restart failed: %s", exc)
                _notify("Restart failed", str(exc))

        threading.Thread(target=_do_restart, daemon=True).start()

    def show_status(self, icon, item) -> None:  # noqa: ARG002
        s = self.manager.status()
        _notify("task-os status", f"{s.detail} · {s.base_url}")

    def quit_app(self, icon, item) -> None:  # noqa: ARG002
        logger.info("👋 Tray quit requested")
        self.watchdog_stop.set()
        try:
            self.manager.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️ stop failed: %s", exc)
        self.instance.release()
        icon.stop()

    # -- run ------------------------------------------------------------------

    def run(self) -> int:
        import pystray  # type: ignore
        from pystray import Menu, MenuItem

        # Background so the icon appears while uvicorn boots (retry schedule
        # could otherwise hold the tray for up to ~50 s).
        threading.Thread(target=self._start, daemon=True).start()
        threading.Thread(
            target=self.watchdog.run, args=(self.watchdog_stop,), daemon=True
        ).start()

        menu = Menu(
            MenuItem("Open task-os", self.open_local, default=True),
            MenuItem("Copy local URL", self.copy_local),
            Menu.SEPARATOR,
            MenuItem("Restart webapp", self.restart_webapp),
            MenuItem("Status", self.show_status),
            Menu.SEPARATOR,
            MenuItem("Quit", self.quit_app),
        )
        icon = pystray.Icon("task-os", icon=_build_icon(), title="task-os", menu=menu)
        icon.run()
        return 1 if self.starter_exc is not None else 0


def run_tray(config: AppConfig) -> int:
    """Run the tray icon; returns when the user picks Quit."""
    try:
        import pystray  # noqa: F401 — import-check only; TrayApp.run() re-imports
    except ImportError as exc:
        logger.error("❌ pystray not installed (%s); pip install -r requirements.txt", exc)
        return 1

    # In-process single-instance guard (project-scaffolding#39): tray.bat's
    # CIM pre-check can let two near-simultaneous launches through; the
    # guarantee lives in this named mutex, held for the tray's lifetime.
    instance = SingleInstance(MUTEX_NAME)
    if not instance.acquired:
        logger.info("ℹ️ Another task-os tray is already running; exiting.")
        return 0
    return TrayApp(config, instance).run()
