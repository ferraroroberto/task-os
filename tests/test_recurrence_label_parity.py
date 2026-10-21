"""``recurrence.js`` ⇔ ``src/dates.py`` — the web UI's hand-kept copy of the recurrence words.

``recurrenceLabel`` mirrors ``describe_recurrence`` and ``anchorOptions`` offers
the anchors ``normalise_anchor`` stores; neither is generated, so this loads the
module under node and holds both to the Python side for every cadence ± anchor
± interval (#229). ``recurrence.js`` imports nothing precisely so it loads bare.
"""

from __future__ import annotations

from pathlib import Path

from src.dates import (
    RECURRENCES,
    WEEKDAY_ABBR,
    WEEKDAYS_ANCHOR,
    describe_recurrence,
    normalise_anchor,
)
from tests.fixtures.node_js import CALL_RUNNER, call_js, requires_node

MODULE = Path(__file__).resolve().parents[1] / "app" / "webapp" / "static" / "recurrence.js"

pytestmark = requires_node


def _call_js(calls: list[tuple[str, list]]) -> list:
    return call_js(MODULE, CALL_RUNNER, calls)


def _anchors(cadence: str | None) -> list[str | None]:
    if cadence == "weekly":
        return [None, *WEEKDAY_ABBR, WEEKDAYS_ANCHOR, "mon,thu", "mon,wed,fri", "sat,sun"]
    if cadence == "monthly":
        nths = [f"{n}-{d}" for n in ("1", "2", "3", "4", "last") for d in WEEKDAY_ABBR]
        return [None, *(f"day-{d}" for d in range(1, 32)), *nths]
    return [None]


def test_recurrence_label_matches_describe_recurrence_everywhere() -> None:
    cases = [
        (cadence, anchor, interval)
        for cadence in (None, *RECURRENCES)
        for anchor in _anchors(cadence)
        for interval in (None, 1, 2, 7, 12)
    ]
    js = _call_js([("recurrenceLabel", list(case)) for case in cases])
    mismatches = [
        (case, py, got)
        for case, got in zip(cases, js, strict=True)
        if (py := describe_recurrence(*case)) != got
    ]
    assert len(cases) > 400
    assert mismatches == []


def test_anchor_options_offer_only_canonical_anchors() -> None:
    """Every value the On picker can send is one the server stores unchanged."""
    groups = _call_js([("anchorOptions", [cadence]) for cadence in RECURRENCES])
    for cadence, options in zip(RECURRENCES, groups, strict=True):
        values = [pair[0] for group in options for pair in group["options"] if pair[0]]
        assert bool(values) == (cadence in ("weekly", "monthly"))
        for value in values:
            assert normalise_anchor(cadence, value) == value
