"""The e2e harness keeps off the loopback port pool and names it when the pool runs dry.

Every closed loopback connection parks an (ephemeral port, server port) pair in
TIME_WAIT, and Windows answers a ``connect()`` that lands on one with
``net::ERR_ADDRESS_IN_USE``. Two halves are pinned here without a browser: the
harness's own HTTP calls reuse one keep-alive connection per server, and a
failure carrying that marker is reported as its own condition, with and without
pytest-xdist.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW
from tests.e2e import _port_pool

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _answer(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — http.server's hook name
        if self.path == "/missing":
            self._answer(404, b'{"error": "nope"}')
        else:
            self._answer(200, b'{"ok": true}')

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self._answer(201 if self.path == "/made" else 422, b'{"made": true}')

    def log_message(self, *args: object) -> None:
        pass


class _CountingServer(ThreadingHTTPServer):
    accepted = 0

    def get_request(self):  # noqa: ANN201 — socketserver's signature
        self.accepted += 1
        return super().get_request()


@pytest.fixture()
def server() -> Iterator[_CountingServer]:
    srv = _CountingServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _base(srv: _CountingServer) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}"


def test_twenty_harness_calls_share_one_connection(server: _CountingServer) -> None:
    base = _base(server)
    for _ in range(10):
        assert _port_pool.get_json(base, "/anything") == {"ok": True}
        assert _port_pool.post_json(base, "/made", {"title": "x"}) == {"made": True}
    assert server.accepted == 1


def test_a_rejected_answer_raises_for_the_json_helpers_and_is_a_status_for_the_probe(
    server: _CountingServer,
) -> None:
    base = _base(server)
    with pytest.raises(_port_pool.HarnessHttpError) as caught:
        _port_pool.get_json(base, "/missing")
    assert caught.value.status == 404
    assert _port_pool.post_status(base, "/nope", {"title": ""}) == 422
    assert _port_pool.post_status(base, "/made", {"title": "x"}) == 201


def _run_child(tmp_path: Path, *extra: str) -> str:
    """Run a throwaway suite whose three tests fail — one on the port-pool marker — and return its output."""
    (tmp_path / "conftest.py").write_text(
        "from tests.e2e._port_pool import pytest_runtest_makereport, pytest_terminal_summary  # noqa: F401\n",
        encoding="utf-8",
    )
    (tmp_path / "test_child.py").write_text(
        textwrap.dedent(
            """
            def test_pool_dry():
                raise AssertionError("Page.goto: net::ERR_ADDRESS_IN_USE at http://127.0.0.1:50000/")


            def test_pool_dry_in_node():
                raise AssertionError("APIRequestContext.post: connect ENOBUFS 127.0.0.1:54418 - Local")


            def test_plain_failure():
                raise AssertionError("the badge is the wrong colour")
            """
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONUTF8": "1"}
    done = subprocess.run(  # subprocess-timeout-exempt: bounded by timeout= below
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--no-header", *extra],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", creationflags=NO_WINDOW, timeout=120,
    )
    return done.stdout + done.stderr


def _assert_names_the_pool_only_for_the_pool_failure(output: str) -> None:
    body, heading, section = output.partition("= PORT POOL EXHAUSTED =")
    assert heading, output
    section = section.split("short test summary info")[0]
    assert body.count("PORT POOL EXHAUSTED —") == 2, output   # only the two pool failures lead with it
    assert "the badge is the wrong colour" in body            # the other failure is reported as itself
    listed = [line.strip() for line in section.splitlines() if line.strip().startswith("test_child.py::")]
    assert sorted(listed) == ["test_child.py::test_pool_dry", "test_child.py::test_pool_dry_in_node"]


def test_a_port_pool_failure_leads_with_its_own_name(tmp_path: Path) -> None:
    output = _run_child(tmp_path)
    assert "3 failed" in output
    _assert_names_the_pool_only_for_the_pool_failure(output)


def test_the_port_pool_section_survives_parallel_workers(tmp_path: Path) -> None:
    output = _run_child(tmp_path, "-n", "2")
    assert "3 failed" in output
    _assert_names_the_pool_only_for_the_pool_failure(output)
