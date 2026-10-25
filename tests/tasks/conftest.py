"""The domain-rule tests' fixtures: a fresh database, the seed over it and a pinned clock."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src import db as dbmod
from src import tasks_repo as repo
from tests.fixtures.seed import seed
from tests.tasks._support import (
    ANCHOR,
)


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "tasks.db"
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(path))
    dbmod.init_db()
    c = dbmod.connect()
    yield c
    c.close()


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> dict:
    result = seed(conn, ANCHOR)
    return result["ids"]


@pytest.fixture
def frozen():
    """Pin the repo clock to the anchor date so 'today' is deterministic."""
    with repo.use_clock(lambda: datetime(2026, 8, 17, 9, 0, 0).astimezone()):
        yield
