"""Windows event-loop shim for uvicorn.

Copied from app-launcher, where it fixed app-launcher#386/#388. The code is
verbatim; the references below are re-pointed at this repo.

On Windows, asyncio's default proactor event loop closes its listening
socket the moment ``accept()`` raises any ``OSError`` (see CPython's
``proactor_events.py:_start_serving``'s accept loop) -- and a client
aborting a connection mid-handshake (a browser dropping the socket, a
phone roaming off Wi-Fi) surfaces as exactly such an ``OSError`` (WinError
64, "The specified network name is no longer available"). One aborted
client and the listener is gone; the process stays alive but every
subsequent connection fails -- the webapp is unresponsive until a tray
restart.

The selector event loop's accept path has no such failure mode -- verified
empirically where the shim originated: 800 concurrent aborted connections
against a bare ``SelectorEventLoop`` server left it accepting fine, while
the same abuse killed a ``ProactorEventLoop`` server after ~20. Nothing in
this repo starts a child through ``asyncio.create_subprocess_*`` (every
spawn is plain ``subprocess``), so the selector loop's lack of subprocess
support is a non-issue here.

Wired into every place that spawns ``app.webapp.server:app`` under
uvicorn -- ``--loop app.webapp.event_loop:selector_loop_factory`` for the
CLI invocations (the tray's ``WebappManager._build_command`` in
``app/webapp/manager.py``, the e2e autoboot spawn in
``tests/e2e/conftest.py``) and
``loop="app.webapp.event_loop:selector_loop_factory"`` for the
programmatic ``uvicorn.run()`` call in ``launcher.py webapp`` (which
``webapp.bat`` hands over to). Keep all of them pointed at the same dotted
path below.

For a *custom* ``--loop``/``loop=`` value (anything outside uvicorn's
built-in ``none``/``auto``/``asyncio``/``uvloop`` names), uvicorn imports
the target and uses it directly as the final zero-arg
``Callable[[], asyncio.AbstractEventLoop]`` passed to ``asyncio.run`` --
unlike the built-in names, it is *not* called with a ``use_subprocess=``
kwarg first (that indirection only applies to the built-in factories in
``uvicorn.config.LOOP_FACTORIES``). So ``selector_loop_factory`` below
must itself return an *instantiated* loop, not a loop class.
"""

from __future__ import annotations

import asyncio
import sys


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


LOOP_FACTORY = "app.webapp.event_loop:selector_loop_factory"
