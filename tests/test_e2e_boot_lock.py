"""The e2e suite's boot lock and per-run work root, proven without a browser.

``tests/e2e/_boot_lock.py`` keeps two processes from picking the same free port
at once. The lock is taken in a temp directory, never the real ``taskos-e2e``
root, so these tests cannot collide with an e2e run in progress on this
machine. The holders are real child processes, because the promise is about
*other* processes. The work-root half checks that each run names a root of its
own, hands it to its workers, and removes only that one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.e2e._boot_lock import boot_lock

REPO_ROOT = Path(__file__).resolve().parents[1]

_BOOT_HOLDER = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "from tests.e2e._boot_lock import boot_lock\n"
    "with boot_lock(Path(sys.argv[1])):\n"
    "    print('booting', flush=True)\n"
    "    time.sleep(1.5)\n"
)


def _spawn_boot_holder(root: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", _BOOT_HOLDER, str(root)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def test_a_second_process_waits_for_the_boot_slot(tmp_path: Path) -> None:
    """Two processes never pick-and-bind a port at once: the second waits its turn."""
    import time

    proc = _spawn_boot_holder(tmp_path)
    try:
        assert proc.stdout and proc.stdout.readline().strip() == "booting"
        started = time.monotonic()
        with boot_lock(tmp_path, timeout=30):
            waited = time.monotonic() - started
        assert waited >= 0.5, f"the second boot did not wait for the first ({waited:.2f}s)"
        # …and once the holder is gone the slot is free at once
        proc.wait(timeout=10)
        started = time.monotonic()
        with boot_lock(tmp_path, timeout=5):
            pass
        assert time.monotonic() - started < 1.0
    finally:
        if proc.poll() is None:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()


def test_a_boot_slot_that_never_frees_times_out_loudly(tmp_path: Path) -> None:
    proc = _spawn_boot_holder(tmp_path)
    try:
        assert proc.stdout and proc.stdout.readline().strip() == "booting"
        with pytest.raises(TimeoutError, match="no instance boot slot"):
            with boot_lock(tmp_path, timeout=0.3):
                pass
    finally:
        proc.kill()
        if proc.stdout:
            proc.stdout.close()


# ------------------------------------------------ the per-run work root (#820)


def test_each_run_names_a_work_root_of_its_own() -> None:
    """Two fresh interpreters importing the suite's conftest get different roots."""
    code = "from tests.e2e.conftest import E2E_WORK_ROOT; print(E2E_WORK_ROOT)"
    env_free = {k: v for k, v in os.environ.items() if k != "TASKOS_E2E_RUN_ROOT"}
    roots = [
        subprocess.run(
            [sys.executable, "-c", code], cwd=str(REPO_ROOT), env=env_free,
            capture_output=True, text=True, timeout=120, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        ).stdout.strip()
        for _ in range(2)
    ]
    assert roots[0] != roots[1]
    for root in roots:
        assert re.fullmatch(r"run-[0-9a-f]{8}", Path(root).name), root
        assert Path(root).parent.name == "taskos-e2e"


def test_a_worker_inherits_its_controllers_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tests.e2e import conftest

    monkeypatch.setenv(conftest.RUN_ROOT_ENV, str(tmp_path / "run-feedbeef"))
    assert conftest._resolve_work_root() == tmp_path / "run-feedbeef"


def test_only_the_session_controller_owns_the_work_root() -> None:
    """The controller removes the root; an xdist worker (``workerinput``) and a
    collect-only run (nothing boots) never do."""
    from tests.e2e.conftest import owns_work_root

    plain = SimpleNamespace(option=SimpleNamespace(collectonly=False))
    assert owns_work_root(plain) is True
    worker = SimpleNamespace(option=SimpleNamespace(collectonly=False), workerinput={"workerid": "gw0"})
    assert owns_work_root(worker) is False
    collecting = SimpleNamespace(option=SimpleNamespace(collectonly=True))
    assert owns_work_root(collecting) is False


def test_a_green_run_removes_its_own_root_and_nothing_else(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tests.e2e import conftest

    mine, other = tmp_path / "run-aaaaaaaa", tmp_path / "run-bbbbbbbb"
    for root in (mine, other):
        (root / "search").mkdir(parents=True)
        (root / "search" / "webapp.log").write_text("x", encoding="utf-8")
    monkeypatch.setattr(conftest, "E2E_WORK_ROOT", mine)
    config = SimpleNamespace(option=SimpleNamespace(collectonly=False))

    monkeypatch.setattr(conftest, "_SESSION_EXIT", [1])          # a red run keeps its logs
    conftest.pytest_unconfigure(config)
    assert mine.exists()

    monkeypatch.setattr(conftest, "_SESSION_EXIT", [0])
    conftest.pytest_unconfigure(config)
    assert not mine.exists()
    assert (other / "search" / "webapp.log").exists()


def test_the_gallery_keeps_the_shared_root_not_the_run_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tests.e2e import conftest

    monkeypatch.setattr(conftest, "E2E_SHARED_ROOT", tmp_path / "taskos-e2e")
    monkeypatch.setattr(conftest, "E2E_WORK_ROOT", tmp_path / "taskos-e2e" / "run-deadbeef")
    run = tmp_path / "taskos-e2e" / "run-deadbeef"
    for painted, expected in (
        (run.as_posix() + "/folders/od", (tmp_path / "taskos-e2e").as_posix() + "/folders/od"),
        (str(run / "folders" / "od"), str(tmp_path / "taskos-e2e" / "folders" / "od")),
    ):
        for src, to in conftest._path_mask_rules():
            painted = re.sub(src, lambda _m, to=to: to, painted, flags=re.I)
        assert painted == expected
