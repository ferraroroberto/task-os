"""Federated search — one query, every adapter at once, results grouped by kind.

:class:`FederatedSearch` holds the four adapters (:mod:`src.search.base`
order: tasks · folders · emails · issues) and answers :meth:`search` with::

    {"q": "...", "took_ms": 12,
     "groups": [{"kind": "tasks", "configured": true, "reason": null, "note": null,
                 "hits": [...], "count": 3, "took_ms": 4, "error": null,
                 "unavailable": null}, ...]}

Rules the UI and the CLI rely on:

- every kind is **always** a group, in that order — an unconfigured adapter is
  ``configured: false`` + its ``reason`` (never silently absent), a failing
  one is ``configured: true`` + ``error`` (a broken index is not "no hits"),
  and a folder-explorer-backed one that cannot answer (down, still on its first
  index, nothing set up there, unreadable) is ``configured: true`` +
  ``unavailable: {state, reason}`` — never an empty ``hits`` that reads as "no match",
  and ``kinds=`` narrows which adapters *run* but the skipped ones still
  appear with ``skipped: true`` so a client can tell "not asked" from "empty";
- the configured adapters run **concurrently** in a thread pool, each bounded
  by :data:`ADAPTER_TIMEOUT_S` — a slow index (a cold 18 k-row email FTS)
  cannot hold the others hostage; a timeout is that group's ``error``;
- ``limit`` is per group.

:func:`build_federated` wires the adapters from an :class:`~src.config.AppConfig`
plus the running services (the webapp lifespan passes ``app.state.folder_explorer`` /
``app.state.issues``; the CLI's local backend builds its own).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from src.config import AppConfig
from src.search.base import KINDS, SearchAdapter
from src.search.emails_adapter import EmailsAdapter
from src.search.folder_explorer import OK, FolderExplorerClient, Unavailable
from src.search.folders_adapter import FoldersAdapter
from src.search.issues_adapter import IssuesAdapter
from src.search.tasks_adapter import TasksAdapter

logger = logging.getLogger(__name__)

__all__ = ["ADAPTER_TIMEOUT_S", "DEFAULT_LIMIT", "FederatedSearch", "build_federated", "parse_kinds"]

NOT_CONFIGURED = "not-configured"
ADAPTER_TIMEOUT_S = 2.0
DEFAULT_LIMIT = 20


def parse_kinds(raw: str | Iterable[str] | None) -> list[str]:
    """``"tasks,emails"`` / ``["tasks"]`` → the known kinds in canonical order; blank = all."""
    if raw is None:
        return list(KINDS)
    wanted = {k.strip().lower() for k in (raw.split(",") if isinstance(raw, str) else raw) if k and k.strip()}
    if not wanted:
        return list(KINDS)
    return [k for k in KINDS if k in wanted]


class FederatedSearch:
    def __init__(self, adapters: Iterable[SearchAdapter], *, timeout_s: float = ADAPTER_TIMEOUT_S) -> None:
        self.adapters: dict[str, SearchAdapter] = {}
        for a in adapters:
            self.adapters[a.kind] = a
        self.timeout_s = float(timeout_s)

    # ------------------------------------------------------------- status
    def status(self) -> list[dict[str, Any]]:
        """Per kind: ``{kind, name, configured, state, reason, note}`` — the Settings card.

        ``state`` is ``ok`` for a local index that is configured, ``not-configured``
        for one that is not, and for a folder-explorer-backed kind the state
        folder-explorer reports (or ``unreachable``) — asked in parallel, because
        each is a network call.
        """
        with ThreadPoolExecutor(max_workers=len(KINDS), thread_name_prefix="task-os-search-status") as pool:
            return list(pool.map(self._status_row, KINDS))

    def _status_row(self, kind: str) -> dict[str, Any]:
        a = self.adapters.get(kind)
        if a is None:
            return {"kind": kind, "name": None, "configured": False, "state": NOT_CONFIGURED,
                    "reason": "no adapter", "note": None}
        ok, reason = a.is_configured()
        if not ok:
            return {"kind": kind, "name": a.name, "configured": False, "state": NOT_CONFIGURED,
                    "reason": reason, "note": None}
        availability = getattr(a, "availability", None)
        if callable(availability):
            state, why, note = availability()
            return {"kind": kind, "name": a.name, "configured": True, "state": state, "reason": why, "note": note}
        note = getattr(a, "note", None)
        return {"kind": kind, "name": a.name, "configured": True, "state": OK, "reason": None,
                "note": note() if callable(note) else None}

    # ------------------------------------------------------------- search
    def search(self, q: str, *, kinds: Iterable[str] | None = None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        q = (q or "").strip()
        wanted = set(parse_kinds(list(kinds) if kinds is not None else None))
        started = time.perf_counter()
        groups: dict[str, dict[str, Any]] = {}
        jobs: dict[str, tuple[SearchAdapter, Any]] = {}
        pool = ThreadPoolExecutor(max_workers=max(1, len(self.adapters)), thread_name_prefix="task-os-search")
        try:
            for kind in KINDS:
                a = self.adapters.get(kind)
                group: dict[str, Any] = {
                    "kind": kind, "configured": False, "reason": None, "note": None,
                    "hits": [], "count": 0, "took_ms": 0, "error": None, "unavailable": None,
                    "skipped": kind not in wanted, "deep_link": None,
                }
                groups[kind] = group
                if a is None:
                    group["reason"] = "no adapter"
                    continue
                ok, reason = a.is_configured()
                group["configured"] = bool(ok)
                group["reason"] = None if ok else reason
                deep_link = getattr(a, "deep_link", None)
                if ok and q and callable(deep_link):
                    group["deep_link"] = deep_link(q)
                if not ok or kind not in wanted or not q:
                    continue
                jobs[kind] = (a, pool.submit(self._run, a, q, limit))
            deadline = time.perf_counter() + self.timeout_s
            for kind, (a, fut) in jobs.items():
                group = groups[kind]
                remaining = max(0.0, deadline - time.perf_counter())
                try:
                    hits, took = fut.result(timeout=remaining)
                    group["hits"] = [h.to_dict() for h in hits]
                    group["count"] = len(group["hits"])
                    group["took_ms"] = took
                except FutureTimeout:
                    group["error"] = f"timed out after {self.timeout_s:.0f} s"
                    group["took_ms"] = int(self.timeout_s * 1000)
                    logger.warning("⚠️ search: %s adapter timed out after %.0fs for %r", a.name, self.timeout_s, q)
                except Unavailable as exc:
                    group["unavailable"] = {"state": exc.state, "reason": exc.reason}
                    logger.info("ℹ️ search: %s unavailable (%s): %s", a.name, exc.state, exc.reason)
                except Exception as exc:  # noqa: BLE001 — one broken index is a visible state, not a 500
                    group["error"] = f"{type(exc).__name__}: {exc}"
                    logger.exception("❌ search: %s adapter failed for %r", a.name, q)
                note = getattr(a, "note", None)
                if callable(note):
                    try:
                        group["note"] = note()
                    except Exception:  # noqa: BLE001
                        group["note"] = None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return {
            "q": q,
            "groups": [groups[k] for k in KINDS],
            "took_ms": int((time.perf_counter() - started) * 1000),
        }

    @staticmethod
    def _run(adapter: SearchAdapter, q: str, limit: int) -> tuple[list[Any], int]:
        t = time.perf_counter()
        hits = adapter.search(q, limit)
        return hits, int((time.perf_counter() - t) * 1000)


def build_federated(
    config: AppConfig,
    *,
    folder_explorer: FolderExplorerClient | None = None,
    issues: Any | None = None,
    conn_factory: Callable[[], Any] | None = None,
    timeout_s: float = ADAPTER_TIMEOUT_S,
) -> FederatedSearch:
    """The four adapters over ``config`` + the running services (may be ``None``)."""
    return FederatedSearch(
        [
            TasksAdapter(conn_factory),
            FoldersAdapter(folder_explorer, config.placeholders),
            EmailsAdapter(folder_explorer, config.placeholders, config.search.email_deep_url),
            IssuesAdapter(issues, conn_factory),
        ],
        timeout_s=timeout_s,
    )
