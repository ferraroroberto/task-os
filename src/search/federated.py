"""Federated search — one query, every adapter at once, results grouped by kind.

:class:`FederatedSearch` holds the four adapters (:mod:`src.search.base`
order: tasks · folders · emails · issues) and answers :meth:`search` with::

    {"q": "...", "took_ms": 12,
     "groups": [{"kind": "tasks", "configured": true, "reason": null, "note": null,
                 "hits": [...], "count": 3, "took_ms": 4, "error": null}, ...]}

Rules the UI and the CLI rely on:

- every kind is **always** a group, in that order — an unconfigured adapter is
  ``configured: false`` + its ``reason`` (never silently absent), a failing
  one is ``configured: true`` + ``error`` (a broken index is not "no hits"),
  and ``kinds=`` narrows which adapters *run* but the skipped ones still
  appear with ``skipped: true`` so a client can tell "not asked" from "empty";
- the configured adapters run **concurrently** in a thread pool, each bounded
  by :data:`ADAPTER_TIMEOUT_S` — a slow index (a cold 18 k-row email FTS)
  cannot hold the others hostage; a timeout is that group's ``error``;
- ``limit`` is per group.

:func:`build_federated` wires the adapters from an :class:`~src.config.AppConfig`
plus the running services (the webapp lifespan passes ``app.state.folders`` /
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
from src.search.folders_adapter import FoldersAdapter
from src.search.issues_adapter import IssuesAdapter
from src.search.tasks_adapter import TasksAdapter

logger = logging.getLogger(__name__)

__all__ = ["ADAPTER_TIMEOUT_S", "DEFAULT_LIMIT", "FederatedSearch", "build_federated", "parse_kinds"]

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
        """Per kind: ``{kind, name, configured, reason, note}`` — the Settings card."""
        out = []
        for kind in KINDS:
            a = self.adapters.get(kind)
            if a is None:
                out.append({"kind": kind, "name": None, "configured": False, "reason": "no adapter", "note": None})
                continue
            ok, reason = a.is_configured()
            note = getattr(a, "note", None)
            out.append({
                "kind": kind, "name": a.name, "configured": ok, "reason": None if ok else reason,
                "note": note() if callable(note) and ok else None,
            })
        return out

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
                    "hits": [], "count": 0, "took_ms": 0, "error": None, "skipped": kind not in wanted,
                }
                groups[kind] = group
                if a is None:
                    group["reason"] = "no adapter"
                    continue
                ok, reason = a.is_configured()
                group["configured"] = bool(ok)
                group["reason"] = None if ok else reason
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
    folders: Any | None = None,
    issues: Any | None = None,
    conn_factory: Callable[[], Any] | None = None,
    timeout_s: float = ADAPTER_TIMEOUT_S,
) -> FederatedSearch:
    """The four adapters over ``config`` + the running services (may be ``None``)."""
    return FederatedSearch(
        [
            TasksAdapter(conn_factory),
            FoldersAdapter(folders),
            EmailsAdapter(config.search.email_db, config.placeholders),
            IssuesAdapter(issues, conn_factory),
        ],
        timeout_s=timeout_s,
    )
