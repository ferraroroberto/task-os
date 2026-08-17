"""The HTTPS certificate pair the webapp serves — where it lives, whether it
exists, and the auto-renew hook every launcher runs before uvicorn binds.

``webapp/certificates/{cert,key}.pem`` (gitignored via ``/webapp/``) is
written by ``scripts/gen_tailscale_cert.py`` (vendored verbatim from
project-scaffolding): a real Let's Encrypt leaf for this machine's tailnet
MagicDNS name, trusted by every device on the tailnet with zero per-device
steps. The leaf is ~90 days, so ``ensure_cert_fresh()`` runs the generator's
``--check`` leg (renew only a ``.ts.net`` cert expiring within ~30 days, never
block startup on an error) from every spawn point — ``WebappManager`` under
the tray, ``launcher.py webapp`` and ``webapp.bat``.

Pair present → the launcher passes ``--ssl-keyfile/--ssl-certfile`` and the
app serves ``https://<host>.ts.net:8448``; absent → plain HTTP with a loud
log line (never silent) and ``/api/status`` reports ``https: false``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = PROJECT_ROOT / "webapp" / "certificates"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"
GEN_SCRIPT = PROJECT_ROOT / "scripts" / "gen_tailscale_cert.py"
CHECK_TIMEOUT_S = 90.0  # a renewal round-trips to Let's Encrypt via tailscale


def cert_paths(project_root: Path | None = None) -> tuple[Path, Path] | None:
    """``(cert.pem, key.pem)`` when both exist under ``webapp/certificates/``."""
    root = project_root or PROJECT_ROOT
    cert = root / "webapp" / "certificates" / "cert.pem"
    key = root / "webapp" / "certificates" / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    return None


def cert_hostname() -> str | None:
    """The ``.ts.net`` DNS SAN of the served leaf — the URL other devices use.

    ``None`` when there is no pair, no ``.ts.net`` name in it, or the
    ``cryptography`` package (the generator's dependency) is unavailable.
    """
    pair = cert_paths()
    if pair is None:
        return None
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(pair[0].read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for name in san.value.get_values_for_type(x509.DNSName):
            if name.endswith(".ts.net"):
                return name
    except Exception as exc:  # noqa: BLE001 — a display convenience, never load-bearing
        logger.debug("cert_hostname: %s", exc)
    return None


def ensure_cert_fresh(python: str | None = None) -> bool:
    """Run ``gen_tailscale_cert.py --check`` (auto-renew inside ~30 days).

    Returns ``True`` when the check ran cleanly (including the no-op cases),
    ``False`` when it could not run — logged, never raised: a cert problem must
    not keep the webapp from starting.
    """
    if not GEN_SCRIPT.exists():
        logger.warning("⚠️ https: %s missing — cert auto-renew skipped", GEN_SCRIPT)
        return False
    if cert_paths() is None:
        return True  # nothing to renew; the launcher logs the plain-HTTP fallback
    try:
        proc = subprocess.run(
            [python or sys.executable, str(GEN_SCRIPT), "--check"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECK_TIMEOUT_S,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("⚠️ https: cert --check did not run (%s) — continuing with the cert on disk", exc)
        return False
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            logger.info("🔏 cert --check: %s", line.strip())
    if proc.returncode != 0:
        logger.warning("⚠️ https: cert --check exited %d: %s", proc.returncode, (proc.stderr or "").strip()[-400:])
        return False
    return True


def uvicorn_ssl_args() -> list[str]:
    """CLI flags for the pair, ``[]`` when serving plain HTTP (logged loudly)."""
    pair = cert_paths()
    if pair is None:
        logger.warning(
            "⚠️ https: no %s — serving PLAIN HTTP; run scripts/gen_tailscale_cert.py for the tailnet cert",
            CERT_DIR,
        )
        return []
    cert, key = pair
    return ["--ssl-keyfile", str(key), "--ssl-certfile", str(cert)]
