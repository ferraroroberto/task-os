"""What the domain-rule tests share: the pinned anchor and the activity reader."""

from __future__ import annotations

from datetime import datetime

from src import tasks_repo as repo
from tests.fixtures.seed import PINNED_ANCHOR

ANCHOR = PINNED_ANCHOR  # 2026-08-17


def _fields(activity: list[dict]) -> list[tuple]:
    return [(a["field"], a["old_value"], a["new_value"]) for a in activity]


def _at(y: int, mo: int, d: int, h: int = 9, mi: int = 0):
    return repo.use_clock(lambda: datetime(y, mo, d, h, mi, 0).astimezone())
