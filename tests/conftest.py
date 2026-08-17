"""Suite-wide isolation: every test process reads a **temp** config.

The committed sample config points ``mirror.dir`` / ``mirror.backup_dir`` at
``{onedrive}/task-os/…`` — a real folder on the developer's machine. A test
that boots the app (``TestClient(create_app())``) would otherwise start the
mirror watcher against it. This autouse session fixture writes a copy of the
sample with both folders blanked (→ the services report "not configured")
and points ``TASKOS_CONFIG_PATH`` at it, unless the caller already set one.
Tests that need a live mirror build their own config on top (see
``tests/test_mirror.py`` / the e2e conftest).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CONFIG = REPO_ROOT / "config" / "config.sample.json"


def write_test_config(
    target: Path,
    *,
    dir: str = "",
    backup_dir: str = "",
    folder_roots: list[str] | None = None,
    placeholders: dict[str, str] | None = None,
) -> Path:
    """The sample config with the machine-bound bits replaced: ``mirror.dir`` /
    ``backup_dir`` (blank = disabled), ``search.folder_roots`` (empty = the
    folder index stays off — the sample points at a real synced folder) and,
    optionally, the ``placeholders`` map (Step 9 tests point ``{onedrive}`` at a
    temp tree)."""
    raw = json.loads(SAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw["mirror"] = {"dir": dir, "backup_dir": backup_dir}
    raw.setdefault("search", {})["folder_roots"] = list(folder_roots or [])
    if placeholders is not None:
        raw["placeholders"] = dict(placeholders)
    target.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return target


@pytest.fixture(scope="session", autouse=True)
def _isolated_config(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    if os.environ.get("TASKOS_CONFIG_PATH"):
        yield
        return
    path = write_test_config(tmp_path_factory.mktemp("taskos-config") / "config.json")
    os.environ["TASKOS_CONFIG_PATH"] = str(path)
    try:
        yield
    finally:
        os.environ.pop("TASKOS_CONFIG_PATH", None)
