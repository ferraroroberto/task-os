"""Keep the e2e harness off the host's loopback ephemeral-port pool.

Every closed loopback connection leaves an (ephemeral port, server port) pair in
TIME_WAIT for minutes, and Windows answers a ``connect()`` that lands on one with
``net::ERR_ADDRESS_IN_USE`` instead of trying another port. So the more
connections a run opens, the likelier the next page load fails on a page that is
fine, and a second gate on the same host adds its own.

Two halves, both reached from ``conftest.py``:

* ``get_json`` / ``post_json`` / ``post_status`` — the harness's own calls to the
  instance under test over one pooled keep-alive session (``src.pooled_http``),
  where a bare ``urllib.request.urlopen`` opened and closed a socket per call.
  The browser's own sockets are not these: a context opens its own, so the
  stories keep a context per case where the case needs the isolation.
* ``pytest_runtest_makereport`` + ``pytest_terminal_summary`` — a failure whose
  text carries ``ERR_ADDRESS_IN_USE`` (or Playwright's ``connect ENOBUFS``) leads with ``PORT POOL EXHAUSTED`` and the
  run ends with a section of that name, so the gate output names a host-capacity
  problem rather than a page defect. The section is read from the reports the
  controller already holds, so it holds under pytest-xdist.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
import requests

from src.pooled_http import pooled_request

#: The two faces the exhaustion takes: the browser's page load, and Playwright's Node-side
#: ``APIRequestContext`` (``connect ENOBUFS 127.0.0.1:<port>``, seen on a full run).
PORT_POOL_MARKERS = ("ERR_ADDRESS_IN_USE", "connect ENOBUFS")
PORT_POOL_HEADLINE = (
    "PORT POOL EXHAUSTED — the host ran out of loopback ephemeral ports or socket buffers "
    "(ERR_ADDRESS_IN_USE / connect ENOBUFS); this is not a page failure. Another gate or a recent run holds "
    "ports in TIME_WAIT: wait a few minutes and re-run instead of debugging the page."
)


class HarnessHttpError(AssertionError):
    """The instance answered a harness call with a status the story did not expect."""

    def __init__(self, method: str, url: str, status: int) -> None:
        super().__init__(f"{method} {url} answered {status}")
        self.status = status


def _call(method: str, base: str, path: str, *, body: dict | None, headers: dict[str, str] | None,
          timeout: float) -> requests.Response:
    kwargs: dict[str, Any] = {"headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    return pooled_request(method, f"{base}{path}", timeout=timeout, **kwargs)


def _expect_ok(res: requests.Response, method: str, url: str) -> dict:
    if res.status_code >= 400:
        raise HarnessHttpError(method, url, res.status_code)
    return res.json()


def get_json(base: str, path: str, *, timeout: float = 5) -> dict:
    """GET a JSON endpoint on the instance under test; a 4xx/5xx raises ``HarnessHttpError``."""
    return _expect_ok(_call("GET", base, path, body=None, headers=None, timeout=timeout), "GET", f"{base}{path}")


def send_json(method: str, base: str, path: str, body: dict | None = None, *,
              headers: dict[str, str] | None = None, timeout: float = 5) -> dict:
    """Send ``method`` with ``body`` as JSON (no body when ``None``) and return the JSON answer; a 4xx/5xx raises."""
    res = _call(method, base, path, body=body, headers=headers, timeout=timeout)
    return _expect_ok(res, method, f"{base}{path}")


def post_json(base: str, path: str, body: dict | None = None, *, timeout: float = 5) -> dict:
    """POST ``body`` as JSON (an empty object when ``None``) and return the JSON answer; a 4xx/5xx raises."""
    return send_json("POST", base, path, {} if body is None else body, timeout=timeout)


def post_status(base: str, path: str, body: dict, *, timeout: float = 15) -> int:
    """POST ``body`` and hand back the status code, a 4xx included: the rejection is what the story asserts."""
    return _call("POST", base, path, body=body, headers=None, timeout=timeout).status_code


def is_port_pool_failure(text: str) -> bool:
    return any(marker in text for marker in PORT_POOL_MARKERS)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Relabel a report that failed on a port-pool marker so its first line names the host."""
    report = yield
    if report.failed and is_port_pool_failure(report.longreprtext) and PORT_POOL_HEADLINE not in report.longreprtext:
        report.longrepr = f"{PORT_POOL_HEADLINE}\n\n{report.longreprtext}"
    return report


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """List the tests that failed on the port pool in a section of their own."""
    hit = [r.nodeid for r in terminalreporter.stats.get("failed", []) if PORT_POOL_HEADLINE in r.longreprtext]
    hit += [r.nodeid for r in terminalreporter.stats.get("error", []) if PORT_POOL_HEADLINE in r.longreprtext]
    if not hit:
        return
    terminalreporter.write_sep("=", "PORT POOL EXHAUSTED", red=True, bold=True)
    terminalreporter.write_line(PORT_POOL_HEADLINE)
    for nodeid in dict.fromkeys(hit):
        terminalreporter.write_line(f"  {nodeid}")
