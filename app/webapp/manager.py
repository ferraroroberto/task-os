"""Webapp process manager — race-safe adopt-or-spawn for the uvicorn child.

Same shape as the sister trays (photo-ocr / voice-transcriber / app-launcher):

- ``status()`` — a real ``GET /healthz`` round-trip plus a TCP probe.
- ``start()``  — adopts an already-listening webapp (no second spawn) or
  spawns ``python -m uvicorn app.webapp.server:app`` from this venv, under the
  vendored ``cross_process_lock`` so two trays starting at once can't both
  spawn (project-scaffolding#39). Before the spawn it runs the cert
  auto-renew (``src.certs.ensure_cert_fresh``) and passes ``--ssl-*`` when
  ``webapp/certificates/{cert,key}.pem`` exist — HTTPS on the tailnet name,
  plain HTTP (logged loudly) otherwise.
- ``stop()``   — terminates only a process *this* manager spawned; an
  externally started uvicorn is left alone (``tray.bat --restart`` reclaims
  those by port, scoped to this repo's ``.venv``).

The spawned child's stdout and stderr go to ``webapp/webapp.log`` (append,
rolled to ``webapp.log.1`` past 1 MB): file logging only starts inside
``create_app()``, so a webapp that dies at boot — an import error after a
pull, a port bind failure, a migration exception — would otherwise leave its
traceback nowhere. The "exited before becoming ready" error names that file.

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
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from app.tray.single_instance import cross_process_lock
from app.webapp.event_loop import LOOP_FACTORY
from src.certs import cert_hostname, cert_paths, ensure_cert_fresh, uvicorn_ssl_args
from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
#: The spawned webapp's stdout + stderr — beside the tray's ``watchdog.log``.
WEBAPP_LOG = PROJECT_ROOT / "webapp" / "webapp.log"
WEBAPP_LOG_MAX_BYTES = 1_000_000

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
    pid: int | None
    port: int
    base_url: str
    detail: str


def _loopback_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "") else host


def _open_child_log(path: Path, max_bytes: int = WEBAPP_LOG_MAX_BYTES) -> IO[bytes] | None:
    """The append-mode log the webapp child writes to; ``None`` when it cannot be opened.

    A log already past ``max_bytes`` is rolled to ``<name>.1`` first (one
    generation), so the file stays bounded without a rotating handler in a
    process that only ever hands its descriptor to the child. An unwritable
    checkout must not stop the app from starting — the caller falls back to
    discarding the output, as before.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > max_bytes:
            os.replace(path, path.with_name(path.name + ".1"))
        handle = path.open("ab")
        handle.write(f"\n--- webapp start {datetime.now().isoformat(timespec='seconds')} ---\n".encode())
        handle.flush()
        return handle
    except OSError as exc:
        logger.warning("⚠️ webapp output log unavailable (%s) — child output is discarded", exc)
        return None


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

    def __init__(
        self, config: WebappManagerConfig | None = None, *, log_path: Path | None = None,
    ) -> None:
        self.config = config or WebappManagerConfig()
        self.log_path = log_path or WEBAPP_LOG
        self._proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        """Loopback URL — the health probe and the owner bypass."""
        scheme = "https" if cert_paths() else "http"
        return f"{scheme}://{_loopback_host(self.config.host)}:{self.config.port}"

    @property
    def public_url(self) -> str:
        """The URL to open / share: ``https://<host>.ts.net:<port>`` when the
        served cert names the tailnet host (no browser warning, works from the
        phone too), else the loopback URL."""
        host = cert_hostname()
        if host:
            return f"https://{host}:{self.config.port}"
        return self.base_url

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

            # Auto-renew a Tailscale leaf expiring within ~30 days BEFORE
            # uvicorn binds (scaffold app-onboarding §2a) — never blocks.
            ensure_cert_fresh(sys.executable)
            cmd = self._build_command()
            logger.info("🚀 Starting webapp: %s", " ".join(cmd))
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            child_log = _open_child_log(self.log_path)
            popen_kwargs: dict[str, Any] = dict(
                cwd=str(PROJECT_ROOT),
                stdout=child_log if child_log else subprocess.DEVNULL,
                stderr=subprocess.STDOUT if child_log else subprocess.DEVNULL,
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
            finally:
                if child_log:
                    child_log.close()   # the child holds its own inherited copy

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

    def _build_command(self) -> list[str]:
        cmd: list[str] = [
            sys.executable, "-m", "uvicorn", "app.webapp.server:app",
            "--host", self.config.host,
            "--port", str(self.config.port),
            "--log-level", "warning",
            "--loop", LOOP_FACTORY,
        ]
        cmd.extend(uvicorn_ssl_args())  # [] + a loud log line when no cert pair
        return cmd

    def _wait_until_ready(self) -> None:
        deadline = time.time() + self.config.startup_timeout_seconds
        while time.time() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                raise RuntimeError(
                    f"webapp uvicorn exited before becoming ready — see {self.log_path}"
                )
            if self.is_reachable():
                logger.info("✅ Webapp ready at %s", self.base_url)
                return
            time.sleep(self.config.poll_interval_seconds)
        raise RuntimeError(
            f"webapp did not become ready within {self.config.startup_timeout_seconds}s"
        )
