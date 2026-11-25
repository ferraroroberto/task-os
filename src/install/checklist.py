"""The personal checks ``setup.bat``'s checklist asks this app for, one command each.

``python -m src.install check <name>`` runs one and prints its detail. Its exit
code is the answer the vendored installer reads: 0 ``ok``, 1 ``missing`` (with
the one step that fixes it), 2 ``unknown`` (the fact could not be established,
which is never folded into ok).
"""

from __future__ import annotations

import http.client
import json
import os
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.certs import cert_paths
from src.config import DEFAULT_PORT
from src.install.machine import SCHEME, opener_state

#: The app answers its health route in milliseconds; a slow answer is not one worth waiting on.
_PROBE_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class Check:
    item: str
    state: str  # ok · missing · unknown
    detail: str = ""


def _config(root: Path) -> tuple[dict[str, Any] | None, str]:
    path = root / "config" / "config.json"
    if not path.exists():
        return None, "config/config.json does not exist yet"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"config/config.json is not valid JSON ({exc}); fix it, then re-run setup.bat"
    if not isinstance(data, dict):
        return None, "config/config.json is not a JSON object; fix it, then re-run setup.bat"
    return data, ""


#: Keys whose sample value is the author's own (an account, a person, a synced folder): on another PC each needs a
#: decision before the first start, since Issue sync and the mirror act on them within seconds.
PERSONAL_KEYS = (
    ("issues", "owner"), ("placeholders", "onedrive"), ("placeholders", "user"), ("mirror", "dir"),
    ("mirror", "backup_dir"), ("team", "people"), ("time", "people"),
)


def _lookup(data: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def sample_values_kept(root: Path, data: dict[str, Any]) -> Check:
    """Which personal keys still hold the sample's value. Only the owner knows whether that is right here,
    so a match is ``unknown``, never ``ok``."""
    item = "config reviewed for this PC"
    try:
        sample = json.loads((root / "config" / "config.sample.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check(item, "unknown", f"the sample could not be read ({exc})")
    same = [".".join(p) for p in PERSONAL_KEYS if _lookup(sample, p) is not None and _lookup(data, p) == _lookup(sample, p)]
    if not same:
        return Check(item, "ok")
    return Check(item, "unknown", "still the sample's values, right for this PC? " + ", ".join(same)
                 + " (docs/setup-and-migration.md)")


def _tray_helper() -> Path:
    home = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(home) / ".claude" / "tray" / "tray_lifecycle.ps1"


def _healthz(port: int, https: bool, timeout: float) -> int:
    """The status ``GET /healthz`` answers on loopback; raises when nothing answers."""
    if https:
        # loopback is the owner, and the served leaf names the tailnet host, never 127.0.0.1
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn: http.client.HTTPConnection = http.client.HTTPSConnection("127.0.0.1", port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/healthz")
        return conn.getresponse().status
    finally:
        conn.close()


def probe_app(port: int, timeout: float = _PROBE_TIMEOUT_S) -> Check:
    """Answering (HTTPS, then plain HTTP, as the tray's restart probe tries), refused (not running), or not
    established."""
    item = f"app answering on port {port}"
    problems: list[str] = []
    for https in (True, False):
        try:
            status = _healthz(port, https, timeout)
        except ConnectionRefusedError:
            return Check(item, "missing", "not running: start tray.bat")
        except (OSError, http.client.HTTPException) as exc:
            problems.append(f"{'https' if https else 'http'}: {exc.__class__.__name__}")
            continue
        if status == 200:
            return Check(item, "ok")
        problems.append(f"{'https' if https else 'http'}: /healthz answered {status}")
    return Check(item, "unknown", "no answer established (" + "; ".join(problems) + ")")


EXIT_CODES = {"ok": 0, "missing": 1, "unknown": 2}


def check_config_reviewed(root: Path) -> Check:
    data, problem = _config(root)
    if data is None:
        return Check("config reviewed for this PC", "unknown", problem)
    return sample_values_kept(root, data)


def check_your_name(root: Path) -> Check:
    item = "your name (Settings -> Your name)"
    data, problem = _config(root)
    if data is None:
        return Check(item, "unknown", problem)
    if str(data.get("your_name", "") or "").strip():
        return Check(item, "ok")
    return Check(item, "missing", "set it in Settings -> Your name: comments and activity are signed with it")


def check_opener(root: Path) -> Check:
    item = f"folder opener ({SCHEME}://)"
    state = opener_state(SCHEME)
    if state is None:
        return Check(item, "unknown", "the registry could not be read")
    return Check(item, "ok" if state else "missing", "" if state else "register it with this checkout's .venv python: -m src.install apply")


def check_tray_helper(root: Path) -> Check:
    item = "tray.bat --restart (shared tray helper)"
    if _tray_helper().is_file():
        return Check(item, "ok")
    return Check(item, "missing", "a plain tray.bat start works; --restart needs fleet-config's helper")


def check_certificate(root: Path) -> Check:
    item = "HTTPS certificate (phone access)"
    if cert_paths(project_root=root):
        return Check(item, "ok")
    return Check(item, "missing", "optional, for the phone: scripts/gen_tailscale_cert.py (docs/access.md)")


def check_signin(root: Path) -> Check:
    item = "sign-in for other devices"
    data, problem = _config(root)
    if data is None:
        return Check(item, "unknown", problem)
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}
    signed = bool(str(auth.get("token", "") or "").strip()) or (root / "config" / "app_password.json").is_file()
    if signed:
        return Check(item, "ok")
    return Check(item, "missing", "optional, for the phone: scripts/gen_token.py or python -m src.password set")


def check_app_answering(root: Path) -> Check:
    data, _problem = _config(root)
    port = data.get("port", DEFAULT_PORT) if data is not None else DEFAULT_PORT
    try:
        return probe_app(int(port))
    except (TypeError, ValueError):
        return Check("app answering", "unknown", f"config port {port!r} is not a number")


#: Every check ``setup.bat`` asks for, by the name ``.fleet.toml [[install.check]]`` passes.
CHECKS: dict[str, Callable[[Path], Check]] = {
    "config-reviewed": check_config_reviewed,
    "your-name": check_your_name,
    "opener": check_opener,
    "tray-helper": check_tray_helper,
    "certificate": check_certificate,
    "signin": check_signin,
    "app-answering": check_app_answering,
}
