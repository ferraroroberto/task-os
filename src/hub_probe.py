"""The reachability probe every local-hub client shares.

One TCP connect, cached by the caller for :data:`PROBE_TTL_S`: the AI client
(:mod:`src.ai.client`), the voice client (:mod:`src.voice`) and the enrich
client (:mod:`src.enrich`) all ask "is anything accepting connections there?"
the same way.
"""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

#: How long a reachability verdict is trusted before the port is touched again.
#: Long enough that opening the quick-add dialog repeatedly costs one connect,
#: short enough that starting whisper shows up on the next open.
PROBE_TTL_S = 15.0
#: Generous for a loopback connect on purpose. The verdict is cached and the
#: mic is disabled until it lands, so a slow probe costs a moment of "checking"
#: — while a probe that gives up too early costs a *wrong* "not reachable" on
#: an endpoint that is simply on another machine.
PROBE_TIMEOUT_S = 1.5


def endpoint_of(url: str) -> tuple[str, int] | None:
    """``(host, port)`` to connect to — ``None`` when *url* is not addressable."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:      # a non-numeric port in the URL
        return None
    return parts.hostname, port


def connect_failure(url: str) -> str | None:
    """``None`` when *url*'s host/port accepts a connection, else why not.

    Shared by the AI, voice and enrich clients: the same connect, the same
    three distinct answers.
    """
    target = endpoint_of(url)
    if target is None:
        return f"not an http(s) URL: {url}"
    host, port = target
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_S):
            pass
    except TimeoutError:
        # A timeout does NOT establish which failure it is, so it must not
        # claim to. Windows takes ~2 s to report a refusal on a dead loopback
        # port (measured here), which is longer than a probe the UI waits on
        # should take — so "nothing there" and "held but silent" (:8090 is
        # mutex-shared with automation/audio/transcribe_voice) both land here,
        # and the reason names both rather than picking one.
        return (f"{host}:{port} did not answer within {PROBE_TIMEOUT_S:g}s — it may be down, "
                f"or the port may be busy")
    except OSError as exc:
        # A refusal *is* established: there is nothing listening.
        return f"nothing is listening on {host}:{port} ({exc.__class__.__name__}: {exc})"
    return None


__all__ = ["PROBE_TIMEOUT_S", "PROBE_TTL_S", "connect_failure", "endpoint_of"]
