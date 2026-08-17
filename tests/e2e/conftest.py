"""Session fixtures for the Playwright e2e suite.

Isolation by construction: ``webapp`` boots a **disposable** uvicorn on a free
loopback port with ``TASKOS_DB_PATH`` → a temp database and
``TASKOS_CONFIG_PATH`` → a temp copy of the committed sample config with the
mirror / backup folders blanked (or pointed into the temp dir — see
``mirrored_webapp``), so a run never reads or writes the live ``:8448`` app,
its ``data/tasks.db``, ``config/config.json`` or the real mirror folder.

Auth (Step 7): the browser reaches the disposable instance over loopback,
which ``src.auth`` treats as the owner — no token, cookie or env switch is
needed; there is deliberately no ``TASKOS_AUTH_DISABLED`` flag. The
non-loopback gate is proven at unit level (``tests/test_auth.py``) with a
spoofed client address; story 07 walks the /login page against an instance
booted with a temp config that carries a token.

``TASKOS_E2E_LIVE=1`` is the one loudly-named opt-in: the suite then runs
*read-only* against the live ``http://127.0.0.1:8448`` instead of booting
(never a kill — reclaiming the port is ``tray.bat --restart``'s job). The
check → refuse → log policy is the vendored ``_e2e_live_guard.py``.

``seeded_webapp`` boots a second disposable instance over the synthetic
fixture (``tests/fixtures/seed.py``) for the stories that need data on
screen (Step 4 on); ``webapp`` stays empty for story 01. ``mirrored_webapp``
(story 06) is a seeded instance whose ``mirror.dir`` / ``backup_dir`` are
temp folders the test can edit and list.

Screenshots: ``shots`` yields ``docs/screenshots`` so a story test saves its
numbered proof there directly (the public repo carries them; the fixture DB
is synthetic/empty, never personal data).

``pytest_sessionfinish`` runs the vendored leaked-browser sweep (#203) once
every fixture — pytest-playwright's ``browser`` included — has torn down.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import pytest

from tests.conftest import write_test_config
from tests.e2e._browser_sweep import sweep_browser_helpers
from tests.e2e._e2e_live_guard import require_disposable_instance

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOTS_DIR = REPO_ROOT / "docs" / "screenshots"
LIVE_PORT = 8448
LIVE_ENV = "TASKOS_E2E_LIVE"
LOOP_FACTORY = "app.webapp.event_loop:selector_loop_factory"

# Bounded Playwright waits: 15 s fails fast with a TimeoutError naming the
# locator instead of stacking opaque 30 s waits (project-scaffolding#61).
_DEFAULT_TIMEOUT_MS = int(os.environ.get("E2E_DEFAULT_TIMEOUT_MS", "15000"))


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_healthz(base: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2) as res:
                if res.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


def _terminate(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:  # noqa: BLE001 — best effort
                pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception:  # noqa: BLE001 — best effort
        pass


def _boot(work: Path, db_path: Path, config_path: Path | None = None) -> tuple[subprocess.Popen, str, IO[str]]:
    """Start a disposable uvicorn on a free loopback port over ``db_path``.

    ``config_path`` defaults to a temp copy of the sample with the mirror and
    backup folders blanked, so the instance never touches a real synced folder
    (and no auth token → the instance is loopback-only, which is exactly what
    the browser is). Story 07 passes a temp config carrying a token to walk
    the /login page.
    """
    port = _free_tcp_port()
    print(f"[e2e] booting disposable instance on 127.0.0.1:{port} (db {db_path})")
    log: IO[str] = (work / "webapp.log").open("w", encoding="utf-8")
    if config_path is None:
        config_path = write_test_config(work / "config.json")
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "TASKOS_DB_PATH": str(db_path),
        "TASKOS_CONFIG_PATH": str(config_path),
    }
    cmd = [
        sys.executable, "-m", "uvicorn", "app.webapp.server:app",
        "--host", "127.0.0.1", "--port", str(port),
        "--log-level", "warning", "--loop", LOOP_FACTORY,
    ]
    kwargs: dict = dict(cwd=str(REPO_ROOT), stdout=log, stderr=subprocess.STDOUT, env=env)
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, **kwargs)
    base = f"http://127.0.0.1:{port}"
    if not _wait_healthz(base, timeout=20):
        _terminate(proc)
        log.close()
        tail = (work / "webapp.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        pytest.fail(f"disposable webapp did not answer {base}/healthz within 20s\n{tail}")
    return proc, base, log


@pytest.fixture(scope="session")
def webapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Base URL of the instance under test — disposable, **empty** DB by default."""
    if os.environ.get(LIVE_ENV) == "1":
        require_disposable_instance(LIVE_PORT, LIVE_ENV)
        base = f"http://127.0.0.1:{LIVE_PORT}"
        if not _wait_healthz(base, timeout=5):
            pytest.exit(f"{LIVE_ENV}=1 but nothing answers {base}/healthz", returncode=2)
        yield base
        return

    work = tmp_path_factory.mktemp("taskos-e2e")
    proc, base, log = _boot(work, work / "tasks.db")
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="session")
def seeded_webapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A second disposable instance over the **synthetic seed** (tests/fixtures/seed.py).

    Story tests from Step 4 on walk real data; story 01 keeps the empty
    instance. Never available against the live app (``TASKOS_E2E_LIVE=1``):
    the seed refuses a database that already has tasks, and the live DB is
    the user's — those tests skip loudly instead.
    """
    if os.environ.get(LIVE_ENV) == "1":
        pytest.skip(f"{LIVE_ENV}=1: the seeded fixture never runs against the live database")
    from tests.fixtures.seed import seed_db

    work = tmp_path_factory.mktemp("taskos-e2e-seeded")
    db = work / "tasks.db"
    seed_db(db)
    proc, base, log = _boot(work, db)
    try:
        yield base
    finally:
        _terminate(proc)
        log.close()


class MirroredInstance:
    """What story 06 needs: the base URL plus the folders the instance writes."""

    def __init__(self, base: str, mirror_dir: Path, backup_dir: Path, db: Path) -> None:
        self.base = base
        self.mirror_dir = mirror_dir
        self.backup_dir = backup_dir
        self.db = db


@pytest.fixture(scope="session")
def mirrored_webapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MirroredInstance]:
    """A seeded disposable instance with ``mirror.dir`` / ``backup_dir`` under a temp folder."""
    if os.environ.get(LIVE_ENV) == "1":
        pytest.skip(f"{LIVE_ENV}=1: the mirrored fixture never runs against the live database")
    from tests.fixtures.seed import seed_db

    work = tmp_path_factory.mktemp("taskos-e2e-mirror")
    db = work / "tasks.db"
    seed_db(db)
    mirror_dir = work / "mirror"
    backup_dir = work / "backup"
    mirror_dir.mkdir()
    config = write_test_config(work / "config.json", dir=str(mirror_dir), backup_dir=str(backup_dir))
    proc, base, log = _boot(work, db, config)
    try:
        yield MirroredInstance(base, mirror_dir, backup_dir, db)
    finally:
        _terminate(proc)
        log.close()


@pytest.fixture(scope="session")
def shots() -> Path:
    """Where story tests save their numbered proof screenshots."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    return SHOTS_DIR


@pytest.fixture(autouse=True)
def _bound_default_timeouts(context) -> None:
    context.set_default_timeout(_DEFAULT_TIMEOUT_MS)
    context.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Advisory sweep of browser helpers this run orphaned inside this checkout."""
    result = sweep_browser_helpers(REPO_ROOT)
    print(f"\n{result.summary()}")
    for entry in result.killed:
        print(f"  reclaimed leaked helper: {entry}")
    # Playwright's own scratch dir under the checkout — nothing of ours lives there.
    shutil.rmtree(REPO_ROOT / "test-results", ignore_errors=True)
