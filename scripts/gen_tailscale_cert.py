"""Provision a Tailscale HTTPS certificate (a real Let's Encrypt leaf) for this app.

This is the *preferred* HTTPS path for a scaffold-derived PWA whose primary remote
surface is the tailnet: `tailscale cert <host>.ts.net` issues a real Let's Encrypt
certificate for the tailnet MagicDNS name, so every device already on the tailnet
trusts it with **zero** per-device steps -- no CA install, no .mobileconfig, no
Certificate-Trust toggle, no Chrome-restart gotcha. Use the self-signed CA generator
(see docs/app-onboarding.md "LAN-only fallback") only for an app with no Tailscale.

Prerequisites:
  1. Enable HTTPS in the Tailscale admin console, once per tailnet:
     https://login.tailscale.com/admin/dns  (scroll to "HTTPS Certificates")
  2. tailscale must be running and authenticated on this machine.

Usage:
    # Provision or force-renew (auto-detects this machine's MagicDNS name):
    & .venv/Scripts/python.exe scripts/gen_tailscale_cert.py
    & .venv/Scripts/python.exe scripts/gen_tailscale_cert.py <host>.ts.net

    # Check and auto-renew if expiring within 30 days (wire into the webapp
    # launcher's startup, before uvicorn binds, so a stale cert self-heals):
    & .venv/Scripts/python.exe scripts/gen_tailscale_cert.py --check

The Let's Encrypt leaf is ~90 days, far shorter than a self-signed root, so the
--check auto-renew is mandatory, not optional. It renews ONLY a .ts.net cert that
is expiring, no-ops a self-signed cert, and never blocks startup on an error.
"""
from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Run standalone (`python scripts/gen_tailscale_cert.py`), so sys.path[0] is
# scripts/, not the repo root -- put the root on the path before importing the
# shared CREATE_NO_WINDOW flag.
sys.path.insert(0, str(PROJECT_ROOT))

from src.no_window import NO_WINDOW  # noqa: E402 -- needs the sys.path line above

# The scaffold's webapp serves its leaf from webapp/certificates/ (see
# docs/app-onboarding.md). Keep this in sync with the --ssl-certfile path the
# launcher passes to uvicorn.
CERT_DIR = PROJECT_ROOT / "webapp" / "certificates"
RENEW_WITHIN_DAYS = 30


def _tailscale_hostname() -> str:
    """Detect this machine's tailnet MagicDNS name from `tailscale status`."""
    result = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        raise SystemExit("tailscale status failed. Is tailscale running?")
    data = json.loads(result.stdout)
    name = data.get("Self", {}).get("DNSName", "").rstrip(".")
    if not name:
        raise SystemExit("Could not detect Tailscale hostname from 'tailscale status'.")
    return name


def _tailscale_hostname_from_cert(cert_path: Path) -> str | None:
    """Return the .ts.net DNS SAN from the cert, or None if not a Tailscale cert."""
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for name in san.value.get_values_for_type(x509.DNSName):
            if ".ts.net" in name:
                return name
    except Exception:
        pass
    return None


def _expiring_within(cert_path: Path, days: int) -> bool:
    """Return True if the cert expires within `days` days."""
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        try:
            expiry = cert.not_valid_after_utc
        except AttributeError:  # cryptography < 42
            expiry = cert.not_valid_after.replace(tzinfo=datetime.UTC)
        threshold = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=days)
        return expiry < threshold
    except Exception:
        return False


def _provision(hostname: str) -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert_path = CERT_DIR / "cert.pem"
    key_path = CERT_DIR / "key.pem"

    result = subprocess.run(
        [
            "tailscale", "cert",
            "--cert-file", str(cert_path),
            "--key-file", str(key_path),
            hostname,
        ],
        capture_output=True,
        text=True,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        print(msg)
        raise SystemExit(
            "\ntailscale cert failed.\n"
            "Make sure HTTPS certificates are enabled in the Tailscale admin console:\n"
            "  https://login.tailscale.com/admin/dns"
        )

    print(f"[OK] cert.pem -> {cert_path}")
    print(f"[OK] key.pem  -> {key_path}")


def _check_and_renew() -> None:
    """Renew the cert if it is a Tailscale cert expiring within RENEW_WITHIN_DAYS days.
    Always exits cleanly -- startup must not be blocked by cert errors."""
    cert_path = CERT_DIR / "cert.pem"
    if not cert_path.exists():
        return

    hostname = _tailscale_hostname_from_cert(cert_path)
    if hostname is None:
        return  # self-signed (or unreadable) cert; leave it alone

    if not _expiring_within(cert_path, RENEW_WITHIN_DAYS):
        return

    print(f"[INFO] Tailscale cert for {hostname} expires within {RENEW_WITHIN_DAYS} days -- renewing.")
    if shutil.which("tailscale") is None:
        print("[WARN] tailscale not found on PATH; skipping cert renewal.")
        return
    try:
        _provision(hostname)
        print("[OK] Tailscale cert renewed.")
    except SystemExit as exc:
        print(f"[WARN] Cert renewal failed: {exc}")


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "--check":
        _check_and_renew()
        return

    if shutil.which("tailscale") is None:
        raise SystemExit("tailscale not found on PATH.")

    hostname = args[0] if args else _tailscale_hostname()
    print(f"Provisioning Tailscale cert for: {hostname}")
    _provision(hostname)
    print()
    print("Restart the webapp, then open it over Tailscale:")
    print(f"  https://{hostname}:<PORT>")
    print()
    print("Note: https://localhost:<PORT> will show a cert hostname-mismatch warning")
    print("because this cert is issued only for the Tailscale domain.")
    print("Use http://localhost:<PORT> for plain local desktop access.")


if __name__ == "__main__":
    main()
