"""The archive lifecycle, declared once: a run's state and a mail's state.

Both are *derived*, never stored. The tables hold facts (a run row's ``status``
and ``finished_at``, an item row's ``status``, ``files`` and ``decided_at``;
the service holds whether a worker is alive), and every reader asks the two
functions here what those facts mean. A reader that compares ``status`` to a
word, or combines it with ``files`` / ``decided_at``, is re-deriving a mode and
will one day disagree with the others (``docs/archive-state.md``).

The JavaScript mirror of the tables is ``app/webapp/static/js/archive/state.js``;
``tests/archive/test_archive_state.py`` keeps the two in step.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    """What the ``archive_runs.status`` column may hold (its ``CHECK``)."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ItemStatus(StrEnum):
    """What the ``archive_items.status`` column may hold (its ``CHECK``)."""

    ARCHIVED = "archived"
    MOVED = "moved"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    REVERTED = "reverted"


class RunState(StrEnum):
    """Where a run is, as every reader sees it."""

    RUNNING = "running"          # row open and this process holds a live worker for it
    INTERRUPTED = "interrupted"  # row open and no live worker: the process died mid-run
    DONE = "done"                # closed cleanly (its ``error`` may still carry notes)
    FAILED = "failed"            # closed with its reason in ``error``


class ItemState(StrEnum):
    """What can be done with one mail, as every reader sees it."""

    ARCHIVED = "archived"            # filed by a run, files on disk
    MOVED = "moved"                  # filed into a folder a human picked, files on disk
    NEEDS_REVIEW = "needs_review"    # still in the Inbox, waiting for a human
    REVIEWED = "reviewed"            # still in the Inbox, a human has said "seen"
    FAILED_ON_DISK = "failed_on_disk"  # a step failed after files were written: retryable, revertible
    FAILED_CLEAN = "failed_clean"    # failed with nothing on disk: the next run decides it again
    REVERTED = "reverted"            # undone, back in the Inbox and free for a later run


#: Why a run left open by a dead process was closed; also the reason an
#: ``interrupted`` run reports before the sweep reaches it.
INTERRUPTED_ERROR = "interrupted: the app stopped during this run"

#: States whose mail has files in the archive tree right now, so an undo has something to undo.
ON_DISK_STATES = frozenset({ItemState.ARCHIVED, ItemState.MOVED, ItemState.FAILED_ON_DISK})
#: States in which a human may still say "seen" (accept answers 409 on anything else).
REVIEWABLE_STATES = frozenset({
    ItemState.NEEDS_REVIEW, ItemState.REVIEWED, ItemState.FAILED_ON_DISK, ItemState.FAILED_CLEAN,
})
#: States that wait in the Inbox for a human to name a folder.
INBOX_WAITING_STATES = frozenset({ItemState.NEEDS_REVIEW, ItemState.REVIEWED})
#: The stored statuses in which a mail is actually filed (the unique index covers exactly these).
FILED_STATUSES = (ItemStatus.ARCHIVED, ItemStatus.MOVED)


def derive_run_state(run: Mapping[str, Any], worker_alive: bool) -> RunState:
    """One run row + whether a worker is driving it right now -> its state.

    An open row with no worker is ``interrupted`` and never ``running``: nothing
    is going to close it. A closed row is what it says whatever the worker is
    doing (the service closes the row a moment before it lets go of its lock).
    """
    status = RunStatus(run["status"])
    if status is RunStatus.RUNNING:
        return RunState.RUNNING if worker_alive else RunState.INTERRUPTED
    return RunState.FAILED if status is RunStatus.FAILED else RunState.DONE


def derive_item_state(item: Mapping[str, Any]) -> ItemState:
    """One item row (``files`` parsed to a list) -> its state.

    A stored ``failed`` is two modes: with files on disk it is half-done (retry,
    revert), with none it is a mail the next run decides again. A
    ``needs_review`` that carries ``decided_at`` is ``reviewed``.
    """
    status = ItemStatus(item["status"])
    if status is ItemStatus.NEEDS_REVIEW:
        return ItemState.REVIEWED if item.get("decided_at") else ItemState.NEEDS_REVIEW
    if status is ItemStatus.FAILED:
        return ItemState.FAILED_ON_DISK if item.get("files") else ItemState.FAILED_CLEAN
    return ItemState(status.value)


def annotate_run(run: Mapping[str, Any], worker_alive: bool) -> dict[str, Any]:
    """The run as the API renders it: every stored field plus ``state`` and ``state_reason``."""
    state = derive_run_state(run, worker_alive)
    reason: str | None = None
    if state is RunState.INTERRUPTED:
        reason = INTERRUPTED_ERROR
    elif state is RunState.FAILED:
        reason = run.get("error")
    return {**run, "state": state.value, "state_reason": reason}


__all__ = [
    "FILED_STATUSES",
    "INBOX_WAITING_STATES",
    "INTERRUPTED_ERROR",
    "ON_DISK_STATES",
    "REVIEWABLE_STATES",
    "ItemState",
    "ItemStatus",
    "RunState",
    "RunStatus",
    "annotate_run",
    "derive_item_state",
    "derive_run_state",
]
