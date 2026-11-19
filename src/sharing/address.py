"""Which local IPv4 address reaches a share's server.

A machine can hold several private addresses (a LAN card, a VPN, a virtual
switch), so "the first private address" is a guess. The address a launcher on the
other side needs is the *source* address of the route to the server the shared
folder lives on, which the operating system picks. Nothing is sent: connecting a
UDP socket only makes the OS choose a route.

Everything that touches the network or the OS is a parameter of
:func:`discover`, so the tests never read a live address.
"""

from __future__ import annotations

import ctypes
import ipaddress
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PureWindowsPath

#: The discard port: the UDP connect below sends nothing, so any port does.
_PROBE_PORT = 9


@dataclass(frozen=True)
class Discovery:
    """The address, or ``None`` and the reason there is not one."""

    address: str | None
    reason: str = ""


def _unc_server(path: str) -> str | None:
    """The server of a ``\\\\server\\share\\...`` path, else ``None``."""
    drive = PureWindowsPath(path).drive
    parts = drive.strip("\\").split("\\")
    if drive.startswith("\\\\") and len(parts) >= 2 and parts[0]:
        return parts[0]
    return None


def _mapped_unc(path: str) -> str | None:
    """The UNC root a mapped drive letter points at (Windows), else ``None``."""
    drive = PureWindowsPath(path).drive
    if sys.platform != "win32" or len(drive) != 2 or drive[1] != ":":
        return None
    size = ctypes.c_ulong(1024)
    buf = ctypes.create_unicode_buffer(size.value)
    # 0 = NO_ERROR; any other code means the letter is a local disk or not mapped.
    if ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size)) != 0:  # type: ignore[attr-defined]
        return None
    return buf.value or None


def share_server(path: str, mapped: Callable[[str], str | None] = _mapped_unc) -> str | None:
    """The server name behind ``path`` — a UNC path, or a mapped drive resolved to one — else ``None``."""
    return _unc_server(path) or _unc_server(mapped(path) or "")


def _resolve(server: str) -> list[str]:
    infos = socket.getaddrinfo(server, None, socket.AF_INET, socket.SOCK_DGRAM)
    return sorted({str(info[4][0]) for info in infos})


def _source_for(remote: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((remote, _PROBE_PORT))
        return str(probe.getsockname()[0])


def discover(
    path: str,
    *,
    mapped: Callable[[str], str | None] = _mapped_unc,
    resolve: Callable[[str], list[str]] = _resolve,
    source_for: Callable[[str], str] = _source_for,
) -> Discovery:
    """The local IPv4 address used to reach the server ``path`` lives on."""
    server = share_server(path, mapped)
    if server is None:
        return Discovery(None, "the file is not on a network share, so there is no server to find a route to")
    try:
        remotes = resolve(server)
    except OSError as exc:
        return Discovery(None, f"the share's server could not be resolved ({type(exc).__name__})")
    if not remotes:
        return Discovery(None, "the share's server has no IPv4 address")
    try:
        sources = sorted({source_for(remote) for remote in remotes})
    except OSError as exc:
        return Discovery(None, f"no route to the share's server ({type(exc).__name__})")
    if len(sources) > 1:
        return Discovery(None, f"ambiguous: {len(sources)} local addresses reach the share's server")
    address = ipaddress.ip_address(sources[0])
    if address.is_loopback or address.is_unspecified or address.is_link_local:
        return Discovery(None, "the share's server is this computer, so the route has no address to publish")
    return Discovery(str(address))
