"""A throwaway task-os instance over the synthetic seed, for /design-review.

``[design.review.synthetic]`` in ``.fleet.toml`` runs this script with the
repo's venv python from the repo root. It boots the webapp on a free loopback
port over a temp database filled by ``tests/fixtures/seed.py`` (the one dataset
allowed on screen) and a temp copy of the sample config, prints ``URL=<base>``
once ``/healthz`` answers, then blocks until its stdin closes and tears the
instance and its temp directory down.

The instance is built from its own temp paths and never reads ``TASKOS_DB_PATH``
or ``TASKOS_CONFIG_PATH`` from the caller: whatever those hold in the parent
environment, the child gets the temp ones, so the live database, the live
config and the live port (8448) are unreachable by construction.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.conftest import write_test_config  # noqa: E402
from tests.fixtures.seed import seed_db  # noqa: E402

HEALTHZ_TIMEOUT_S = 30.0
# Importing tests.conftest makes an empty directory for the password file at
# import time; it is this launcher's to remove, like its own work directory.
_IMPORT_SCRATCH = Path(os.environ["APP_PASSWORD_FILE"]).parent
# Windows releases a stopped child's file handles a moment after it exits.
_REMOVE_ATTEMPTS = 20


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _healthy(base: str, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2) as res:
                if res.status == 200:
                    return True
        except OSError:
            time.sleep(0.1)
    return False


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def _remove_tree(path: Path) -> None:
    for _ in range(_REMOVE_ATTEMPTS):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.25)
    print(f"could not remove {path}", file=sys.stderr)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="taskos-design-review-"))
    proc: subprocess.Popen | None = None
    try:
        db = work / "tasks.db"
        counts = seed_db(db)["counts"]
        if not counts:
            print("the synthetic seed produced no rows; refusing to serve it", file=sys.stderr)
            return 2
        config = write_test_config(work / "config.json")
        port = _free_loopback_port()
        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "TASKOS_DB_PATH": str(db),
            "TASKOS_CONFIG_PATH": str(config),
            "TASKOS_ISSUE_PROVIDER": "none",
            # The two pollers' first automatic passes land an hour out, so no
            # background write moves a surface while it is being measured.
            "TASKOS_CAPTURE_DELAY_S": "3600",
            "TASKOS_ISSUE_SYNC_DELAY_S": "3600",
        }
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if sys.platform == "win32" else 0
        with (work / "webapp.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "app.webapp.serve", "--host", "127.0.0.1", "--port", str(port),
                 "--log-level", "warning"],
                cwd=str(REPO_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
            )
            base = f"http://127.0.0.1:{port}"
            if not _healthy(base, HEALTHZ_TIMEOUT_S, proc):
                print(f"the synthetic instance did not answer {base}/healthz", file=sys.stderr)
                return 1
            print(f"URL={base}", flush=True)
            sys.stdin.read()   # the caller closing stdin is the stop signal
            return 0
    finally:
        if proc is not None:
            _stop(proc)
        _remove_tree(work)
        _remove_tree(_IMPORT_SCRATCH)


if __name__ == "__main__":
    sys.exit(main())
