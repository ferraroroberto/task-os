"""Webapp process manager — race-safe adopt-or-spawn for the uvicorn child.

Same shape as the sister trays (photo-ocr / voice-transcriber / app-launcher):

- ``status()`` — a real ``GET /healthz`` round-trip plus a TCP probe.
- ``start()``  — adopts an already-listening webapp (no second spawn) or
  spawns ``python -m uvicorn app.webapp.server:app`` from this venv, under the
  vendored ``cross_process_lock`` so two trays starting at once can't both
  spawn (project-scaffolding#39).
- ``stop()``   — terminates only a process *this* manager spawned; an
  externally started uvicorn is left alone (``tray.bat --restart`` reclaims
  those by port, scoped to this repo's ``.venv``).

Health probes use ``http.client`` directly — one short-lived loopback request
per watchdog tick (60 s), no session needed at that cadence.
"""

from __future__ import annotations

import http.client
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.tray.single_instance import cross_process_lock
from app.webapp.event_loop import LOOP_FACTORY
from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

OWNERSHIP_NONE = "none"
OWNERSHIP_OURS = "ours"
OWNERSHIP_EXTERNAL = "external"


@dataclass(frozen=True)
class WebappManagerConfig:
    host: str = "0.0.0.0"
    port: int = 8448
    startup_timeout_seconds: float = 20.0
    request_timeout_seconds: float = 1.5
    poll_interval_seconds: float = 0.4


@dataclass
class WebappStatus:
    running: bool
    ownership: str
    pid: Optional[int]
    port: int
    base_url: str
    detail: str


def cert_paths(project_root: Optional[Path] = None) -> Optional[tuple[Path, Path]]:
    """``(cert.pem, key.pem)`` under ``webapp/certificates/`` when both exist.

    HTTPS is Step 7 (Tailscale cert); until then the pair is absent and the
    webapp serves plain HTTP on the loopback/LAN.
    """
    root = project_root or PROJECT_ROOT
    cert = root / "webapp" / "certificates" / "cert.pem"
    key = root / "webapp" / "certificates" / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    return None


def _loopback_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "") else host


def stop_process(proc: subprocess.Popen, name: str) -> None:
    """CTRL_BREAK (Windows) → terminate → kill after 5 s. Best-effort."""
    try:
        logger.info("🛑 Stopping %s (pid=%s)", name, proc.pid)
        if sys.platform == "win32":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:  # noqa: BLE001
                pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s stop failed: %s", name, exc)


class WebappManager:
    """Start / stop / health-check the webapp uvicorn process."""

    def __init__(self, config: Optional[WebappManagerConfig] = None) -> None:
        self.config = config or WebappManagerConfig()
        self._proc: Optional[subprocess.Popen] = None

    @property
    def base_url(self) -> str:
        scheme = "https" if cert_paths() else "http"
        return f"{scheme}://{_loopback_host(self.config.host)}:{self.config.port}"

    def is_reachable(self) -> bool:
        """A real ``/healthz`` round-trip — a port check cannot see a wedge."""
        host = _loopback_host(self.config.host)
        timeout = self.config.request_timeout_seconds
        for use_tls in (bool(cert_paths()), False):
            try:
                if use_tls:
                    import ssl

                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                        host, self.config.port, timeout=timeout, context=ctx
                    )
                else:
                    conn = http.client.HTTPConnection(host, self.config.port, timeout=timeout)
                try:
                    conn.request("GET", "/healthz")
                    if conn.getresponse().status == 200:
                        return True
                finally:
                    conn.close()
            except (OSError, http.client.HTTPException):
                continue
        return False

    def is_port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex((_loopback_host(self.config.host), self.config.port)) == 0

    def status(self) -> WebappStatus:
        running_here = self._proc is not None and self._proc.poll() is None
        reachable = self.is_reachable() or self.is_port_in_use()
        if running_here and reachable:
            return WebappStatus(True, OWNERSHIP_OURS, self._proc.pid, self.config.port,
                                self.base_url, "running (started by this tray)")
        if reachable:
            return WebappStatus(True, OWNERSHIP_EXTERNAL, None, self.config.port,
                                self.base_url, "running (external — adopted)")
        return WebappStatus(False, OWNERSHIP_NONE, None, self.config.port,
                            self.base_url, "not running")

    def start(self, wait: bool = True) -> WebappStatus:
        # Serialize status()-then-Popen across processes: the loser of a
        # simultaneous start blocks, re-checks, and adopts the now-listening
        # webapp instead of spawning a duplicate. Fails open on a mutex glitch.
        with cross_process_lock(rf"Global\task-os-webapp-start-{self.config.port}"):
            current = self.status()
            if current.running and current.ownership == OWNERSHIP_OURS:
                logger.info("ℹ️ Webapp already %s", current.detail)
                return current
            if current.running:
                logger.info("🔗 Adopting external webapp at %s", current.base_url)
                return current

            cmd = self._build_command()
            logger.info("🚀 Starting webapp: %s", " ".join(cmd))
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            popen_kwargs: Dict[str, Any] = dict(
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW
            try:
                self._proc = subprocess.Popen(cmd, **popen_kwargs)
            except FileNotFoundError as exc:
                raise RuntimeError(f"python launcher not found: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"failed to launch webapp: {exc}") from exc

            if wait:
                self._wait_until_ready()
            return self.status()

    def restart(self, wait: bool = True) -> WebappStatus:
        status = self.status()
        if status.running and status.ownership == OWNERSHIP_EXTERNAL:
            raise RuntimeError(
                "Webapp is running but was started externally — use tray.bat --restart"
            )
        if status.running:
            self.stop()
        return self.start(wait=wait)

    def stop(self) -> WebappStatus:
        status = self.status()
        if status.ownership == OWNERSHIP_EXTERNAL:
            logger.info("✋ Leaving external webapp running (not ours)")
            return status
        if not status.running or self._proc is None:
            return status
        try:
            stop_process(self._proc, "webapp")
        finally:
            self._proc = None
        return WebappStatus(False, OWNERSHIP_NONE, None, self.config.port, self.base_url, "stopped")

    def _build_command(self) -> List[str]:
        cmd: List[str] = [
            sys.executable, "-m", "uvicorn", "app.webapp.server:app",
            "--host", self.config.host,
            "--port", str(self.config.port),
            "--log-level", "warning",
            "--loop", LOOP_FACTORY,
        ]
        certs = cert_paths()
        if certs is not None:
            cert, key = certs
            cmd.extend(["--ssl-keyfile", str(key), "--ssl-certfile", str(cert)])
        return cmd

    def _wait_until_ready(self) -> None:
        deadline = time.time() + self.config.startup_timeout_seconds
        while time.time() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                raise RuntimeError("webapp uvicorn exited before becoming ready")
            if self.is_reachable():
                logger.info("✅ Webapp ready at %s", self.base_url)
                return
            time.sleep(self.config.poll_interval_seconds)
        raise RuntimeError(
            f"webapp did not become ready within {self.config.startup_timeout_seconds}s"
        )
