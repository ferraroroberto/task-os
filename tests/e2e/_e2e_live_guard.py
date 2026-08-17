"""E2e live-instance guard (issue #191/#194/#197).

The fleet-wide policy: an e2e/regression fixture must default to booting its
own disposable instance and *refuse* — never silently kill or adopt — a live
app already listening on its target port. Ad-hoc `pytest tests/e2e` runs must
never drive a live tray/dev-server by accident. #191 shipped this as
hand-rolled logic inline in a conftest.py; #194 extracted it here because the
policy itself (check occupied -> refuse-with-named-flag -> log) is genuinely
shape-independent across the fleet, even though how each project actually
boots its disposable instance is not.

The opt-in flag means "I am choosing to act on the already-listening
instance" — it does not mean "kill it". What "act" means is caller-owned and
repo-specific: read-only assertions against the live instance (the
app-launcher `LAUNCHER_E2E_LIVE` precedent — it has never meant kill), or,
only where a repo genuinely needs to reclaim the port, a restart performed
through that repo's own *canonical* restart recipe (e.g. `tray.bat
--restart`) — never a by-hand `taskkill`/port-kill. On several fleet repos the
guarded port is a daily-driver process with live state (voice-transcriber's
tray with live sessions + a whisper connection; app-launcher's Board), so a
blanket kill is actively dangerous, and a by-hand kill also misses orphaned
port holders — itself a cause of the ephemeral-port exhaustion this
convention exists to prevent (#197). This module must never teach that shape.

Vendor-verbatim: consuming apps copy this file byte-identical into their own
`tests/e2e/` (like `app/tray/single_instance.py`, `tests/e2e/_geometry.py`) —
the target port and the opt-in env var name are call-site arguments, so the
copy never forks. The module imports only the stdlib (plus a local `pytest`
import, deferred so the module stays importable outside a pytest run).
"""

from __future__ import annotations

import os
import socket


def port_is_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something accepts TCP connections on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def require_disposable_instance(
    port: int,
    live_flag_env: str,
    *,
    host: str = "127.0.0.1",
) -> bool:
    """Refuse to touch an occupied port unless the caller opted in.

    Returns ``True`` when ``live_flag_env`` is set to ``"1"`` — the caller has
    explicitly opted in to *act* on the already-occupied port — and ``False``
    when it should simply boot fresh (the common case: the port is free, or
    nothing calls for touching what's there). What "act" means is entirely
    caller-owned and repo-specific; this function only reports the opt-in, it
    never performs it. The two legitimate meanings are: read-only assertions
    against the already-running instance, or — only where a repo genuinely
    needs to reclaim the port — invoking that repo's own canonical restart
    recipe (e.g. ``tray.bat --restart``), never a by-hand kill. See the module
    docstring for why a blanket kill is unsafe.

    Never returns while an occupied port has no opt-in: calls
    ``pytest.exit(..., returncode=2)`` instead, naming the flag, so a bare
    e2e run stops rather than silently touching a process it didn't start.

    Booting/tearing down the actual disposable instance stays the caller's
    job — this function only owns the check -> refuse -> log decision.
    """
    import pytest  # local import: keep this module importable outside pytest

    live_opt_in = os.environ.get(live_flag_env) == "1"
    if port_is_in_use(port, host) and not live_opt_in:
        pytest.exit(
            f"Refusing to touch the process already listening on "
            f"{host}:{port} - a bare e2e run must not silently kill or "
            f"adopt it. Set {live_flag_env}=1 to explicitly opt in to "
            "acting on the live instance instead of refusing - what "
            "'acting' means is this repo's own choice (read-only "
            "assertions, or a reclaim via its own canonical restart "
            "recipe, never a by-hand kill) - check this repo's CLAUDE.md, "
            "or free the port yourself first.",
            returncode=2,
        )
    if live_opt_in:
        print(f"[e2e] {live_flag_env}=1 - acting on the live instance at {host}:{port}")
    else:
        print(f"[e2e] booting disposable instance on {host}:{port}")
    return live_opt_in
