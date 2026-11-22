"""scripts/design_review_synthetic.py: the contract /design-review boots it by.

It prints ``URL=<base>`` once the instance answers, serves the synthetic seed on
a free loopback port, and exits (removing its temp directory) when its stdin
closes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "design_review_synthetic.py"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as res:
        return json.loads(res.read())


def _launch(tmp_path: Path, env_extra: dict[str, str] | None = None) -> subprocess.Popen:
    # The launcher makes its temp dir under tempfile's root; pointing that at
    # tmp_path lets the test see it appear and disappear.
    env = {**os.environ, "TMP": str(tmp_path), "TEMP": str(tmp_path), "TMPDIR": str(tmp_path),
           "PYTHONUTF8": "1", **(env_extra or {})}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        [sys.executable, str(SCRIPT)], cwd=str(REPO_ROOT), env=env, creationflags=flags,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_prints_url_serves_the_seed_and_cleans_up_on_stdin_eof(tmp_path: Path) -> None:
    proc = _launch(tmp_path)
    try:
        line = proc.stdout.readline().strip()
        match = re.fullmatch(r"URL=(http://127\.0\.0\.1:(\d+))", line)
        assert match, f"first stdout line was {line!r}"
        base, port = match.group(1), int(match.group(2))
        assert port != 8448, "the live port is never the synthetic instance's"

        assert _get(f"{base}/healthz") is not None
        assert _get(f"{base}/api/version")["schema_version"] >= 1
        # The seed's tasks are on screen: an empty install would answer 0.
        assert _get(f"{base}/api/tasks?limit=1"), "the instance serves no tasks"
        assert list(tmp_path.glob("taskos-design-review-*")), "the temp working directory is missing while serving"

        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    assert not list(tmp_path.glob("taskos-design-review-*")), "the temp working directory outlived the launcher"


def test_ignores_a_live_database_path_in_the_environment(tmp_path: Path) -> None:
    live = Path(tempfile.gettempdir()) / "not-a-real-live.db"   # never created: it must stay unopened
    proc = _launch(tmp_path, {"TASKOS_DB_PATH": str(live), "TASKOS_CONFIG_PATH": str(live)})
    try:
        assert proc.stdout.readline().startswith("URL=")
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    assert not live.exists()
