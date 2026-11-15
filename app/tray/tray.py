"""System-tray launcher — owns the task-os webapp lifecycle behind a tray icon.

Launched by ``tray.bat`` (idempotent start; ``--restart`` is the orphan-proof
reclaim-then-start owned by the shared ``tray_lifecycle.ps1``). Menu:

    Open task-os      — open the app (the tailnet HTTPS URL when the served
                        cert names it, else the loopback URL)
    Copy URL          — clipboard that same URL (paste it on the phone)
    Restart webapp    — stop + start so a fresh build is picked up
    Status            — toast with the webapp state
    --
    Quit              — stop the webapp and exit

Self-heal (vendored ``app/tray/watchdog.py``):
the initial spawn retries with backoff on a background thread, a health
watchdog splits *starting* (the child this tray spawned is alive inside its
startup window → back off), *dead* (not listening → respawn) and *wedged*
(listening, ``/healthz`` silent → alert only), and every attempt leaves a
breadcrumb in ``webapp/watchdog.log`` — the only durable trail under
``pythonw``, which has no ``sys.stderr``. Every spawn goes through one
``RespawnGuard`` so a slow boot never stacks a second copy on the port.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from app.tray.single_instance import SingleInstance
from app.tray.watchdog import (
    DEFAULT_STARTUP_RETRY_DELAYS_S,
    DEFAULT_STARTUP_WINDOW_S,
    BreadcrumbLog,
    HealthWatchdog,
    RespawnGuard,
    RespawnOutcome,
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
# `clip` copies a short URL and answers in well under a second, so a child still
# alive after 10 s is wedged and must not stall the tray menu thread.
CLIP_TIMEOUT_S = 10
# How often the boot thread asks a freshly spawned webapp whether it answers yet,
# to toast "ready" without holding the spawn path (which must not block).
READY_POLL_S = 2.0


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
            timeout=CLIP_TIMEOUT_S,
        )
        return p.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("clip did not finish within %ss; clipboard not set", CLIP_TIMEOUT_S)
        return False
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
        self.manager = WebappManager(WebappManagerConfig(port=config.port, server=config.server))
        self.wd_log = BreadcrumbLog(WATCHDOG_LOG)
        self.guard = RespawnGuard(self.wd_log)  # owns the one webapp child this tray spawned
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

    def _spawn(self) -> int:
        """Spawn the webapp and return its pid without waiting for readiness.

        A readiness wait that times out raises with the child still alive, and
        the pid would be lost to the guard: that is how copies stacked up.
        """
        self.manager.start(wait=False)
        pid = self.manager.child_pid
        if pid is None:
            raise RuntimeError(f"webapp child exited at once — see {self.manager.log_path}")
        return pid

    def _announce_ready(self) -> None:
        """Toast once the spawned webapp answers, giving up after its startup window."""
        deadline = time.monotonic() + DEFAULT_STARTUP_WINDOW_S
        while not self.watchdog_stop.wait(READY_POLL_S):
            if self.manager.is_reachable():
                self.wd_log(f"webapp started at {self.manager.base_url}")
                _notify("task-os ready", self.manager.public_url)
                return
            if time.monotonic() >= deadline:
                self.wd_log("webapp not answering after its startup window")
                return

    def _start(self) -> None:
        try:
            if self.manager.is_port_in_use():
                self.wd_log(f"webapp already listening on :{self.config.port} -- adopted")
                _notify("task-os ready", self.manager.public_url)
                return
            retry_with_backoff(
                lambda: self.guard.respawn(self._spawn),
                DEFAULT_STARTUP_RETRY_DELAYS_S,
                self._on_start_attempt_failed,
            )
            self._announce_ready()
        except Exception as exc:  # noqa: BLE001 — exhausted: loud, never silent
            self.starter_exc = exc
            self.wd_log(f"webapp start FAILED permanently: {exc}")
            logger.error("❌ webapp start failed after retries: %s", exc)
            _notify("task-os start failed", str(exc))

    def _on_wedge(self, count: int) -> None:
        if self.guard.is_starting():
            # Our own child is alive inside its startup window: a slow boot, not
            # a failure. Spawning again would leave two copies on the port.
            self.wd_log(f"webapp pid {self.guard.pid} still starting ({count} failed probes)")
            self.watchdog.rearm()
            return
        if self.manager.is_port_in_use():
            # Wedged: listening but not answering. Alert only — auto-killing a
            # stuck process can mask what is actually wrong.
            msg = f"webapp on :{self.config.port} listening but not answering /healthz ({count} probes)"
            self.wd_log(f"WEDGE {msg} -- use tray.bat --restart")
            logger.error("❌ %s", msg)
            _notify("task-os webapp wedged", "Listening but not answering — use tray.bat --restart")
            return
        # Dead: not listening at all — safe to respawn.
        self.wd_log(f"webapp not listening ({count} consecutive failures) -- respawning")
        try:
            if self.guard.respawn(self._spawn) is RespawnOutcome.SPAWNED:
                self.wd_log("webapp respawned")
                _notify("task-os webapp respawned", self.manager.base_url)
        except Exception as exc:  # noqa: BLE001
            self.wd_log(f"webapp respawn failed: {exc}")
            logger.error("❌ webapp respawn failed: %s", exc)
            _notify("task-os respawn failed", str(exc))
        # Re-evaluate next tick either way: a respawned child must be probed
        # again, a failed one retried, and neither waits on a recovery edge.
        self.watchdog.rearm()

    def _on_recover(self) -> None:
        self.guard.mark_healthy()
        self.wd_log("webapp health recovered")
        logger.info("✅ webapp answering /healthz again")
        _notify("task-os webapp recovered", self.manager.base_url)

    # -- menu actions ---------------------------------------------------------

    def open_local(self, icon, item) -> None:  # noqa: ARG002
        webbrowser.open(self.manager.public_url)

    def copy_local(self, icon, item) -> None:  # noqa: ARG002
        url = self.manager.public_url
        _notify("Copied URL" if _clipboard_copy(url) else "URL", url)

    def restart_webapp(self, icon, item) -> None:  # noqa: ARG002
        def _do_restart() -> None:
            try:
                _notify("task-os", "Restarting webapp…")
                try:
                    self.manager.restart(wait=True)
                finally:
                    # A readiness timeout leaves the new child alive: the guard
                    # must know it or the next respawn stacks a copy beside it.
                    pid = self.manager.child_pid
                    if pid is not None:
                        self.guard.track(pid)
                self.wd_log("webapp restarted from tray menu")
                _notify("task-os webapp restarted", self.manager.public_url)
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
            MenuItem("Copy URL", self.copy_local),
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

    # In-process single-instance guard: tray.bat's
    # CIM pre-check can let two near-simultaneous launches through; the
    # guarantee lives in this named mutex, held for the tray's lifetime.
    instance = SingleInstance(MUTEX_NAME)
    if not instance.acquired:
        logger.info("ℹ️ Another task-os tray is already running; exiting.")
        return 0
    return TrayApp(config, instance).run()
