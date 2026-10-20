"""`src.clock`'s two pinned modes: frozen, and frozen-at-start-then-advancing (#459)."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from src import clock

PINNED = "2026-09-07T09:00:00+00:00"


def test_pinned_clock_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(clock.CLOCK_ENV, PINNED)
    monkeypatch.delenv(clock.TICK_ENV, raising=False)
    read = clock._initial_clock()
    first = read()
    time.sleep(0.05)
    assert read() == first == datetime.fromisoformat(PINNED)


def test_tick_starts_at_the_pinned_instant_and_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(clock.CLOCK_ENV, PINNED)
    monkeypatch.setenv(clock.TICK_ENV, "1")
    read = clock._initial_clock()
    first = read()
    assert 0 <= (first - datetime.fromisoformat(PINNED)).total_seconds() < 1
    time.sleep(0.05)
    assert read() > first


def test_tick_without_a_pinned_start_is_the_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(clock.CLOCK_ENV, "")
    monkeypatch.setenv(clock.TICK_ENV, "1")
    assert abs((clock._initial_clock()() - datetime.now().astimezone()).total_seconds()) < 5
