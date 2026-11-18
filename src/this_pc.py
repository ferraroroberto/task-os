"""Is a request from this very machine? — the test behind every action that reads this PC's own desktop.

A browser on the PC reaches the app by loopback or, through the tray's tailnet
link, by one of the PC's own interface addresses; a phone or another PC arrives
from an address that is not this machine's. The access gate (``src/auth.py``)
stays loopback-only; this wider test only decides whether an action about the
PC's own windows is offered.
"""

from __future__ import annotations

import ipaddress
import socket

from src.auth import is_loopback

__all__ = ["is_this_pc"]


def is_this_pc(host: str | None) -> bool:
    """True for loopback, or an IP address assigned to an interface of this machine."""
    if is_loopback(host):
        return True
    try:
        ip = ipaddress.ip_address((host or "").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Binding the wildcard or a multicast group succeeds without naming an interface.
    if ip.is_unspecified or ip.is_multicast:
        return False
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.bind((str(ip), 0))
    except OSError:
        return False
    return True
