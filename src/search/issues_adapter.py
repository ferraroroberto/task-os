"""Issues adapter — the issue refs on coding tasks + the sync's cached open list.

No forge call on a keystroke: the adapter reads (a) ``issue_refs`` joined to
their tasks (:func:`src.tasks_repo.list_issue_refs`) and (b) the
:class:`~src.issue_sync.IssueSyncService` cache — the last-seen
:class:`~src.issues.IssueInfo` per issue (title, labels, state, url) the
periodic sync keeps warm — which also surfaces open issues that have no task
yet. Every query word must appear (case-insensitive) in ``owner/repo#N``,
the title, or a label; title hits rank above label / repo hits.

Configured ⇔ the issue provider is (the service's own ``reason`` otherwise —
"issues.provider is blank", "gh not on PATH", …).

Hit: title = the issue title (the task title when the cache is cold) ·
subtitle = ``owner/repo#N · state · labels`` · snippet = the title with
``[match]`` marks · ref = ``owner/repo#N`` · url = the issue URL · extra =
``provider, repo, number, state, labels, task_id`` (``task_id`` = the linked
task, ``None`` for a cached issue with no task yet).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from src import tasks_repo as repo
from src.db import connect
from src.search.base import Hit, mark_terms, terms

__all__ = ["IssuesAdapter"]


def _issue_url(provider: str, repo_name: str, number: int) -> str:
    host = "https://gitlab.com/" if provider == "gitlab" else "https://github.com/"
    sep = "/-/issues/" if provider == "gitlab" else "/issues/"
    return f"{host}{repo_name}{sep}{number}"


class IssuesAdapter:
    name = "issues"
    kind = "issues"

    def __init__(self, service: Any | None, conn_factory: Callable[[], sqlite3.Connection] | None = None) -> None:
        self.service = service
        self._connect = conn_factory or connect

    def is_configured(self) -> tuple[bool, str | None]:
        if self.service is None:
            return False, "issue service not started"
        if not getattr(self.service, "enabled", False):
            return False, getattr(self.service, "reason", None) or "issue provider not configured"
        return True, None

    def _candidates(self) -> list[dict[str, Any]]:
        """Local refs first (with the cached info merged in), then cached-only issues."""
        conn = self._connect()
        try:
            refs = repo.list_issue_refs(conn)
        finally:
            conn.close()
        cache = dict(getattr(self.service, "cache", {}) or {})
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        for r in refs:
            key = (r["provider"], r["repo"], int(r["number"]))
            seen.add(key)
            info = cache.get(key)
            out.append({
                "provider": r["provider"], "repo": r["repo"], "number": int(r["number"]),
                "title": (info.title if info else None) or r["task_title"] or f"{r['repo']}#{r['number']}",
                "state": (info.state if info else None) or r["state"] or "unknown",
                "url": r["url"] or (info.url if info else None) or _issue_url(r["provider"], r["repo"], int(r["number"])),
                "labels": list(info.labels) if info else [],
                "task_id": int(r["task_id"]),
                "task_status": r["task_status"],
            })
        for key, info in cache.items():
            if key in seen:
                continue
            out.append({
                "provider": info.provider, "repo": info.repo, "number": int(info.number),
                "title": info.title or info.ref, "state": info.state or "unknown",
                "url": info.url or _issue_url(info.provider, info.repo, int(info.number)),
                "labels": list(info.labels), "task_id": None, "task_status": None,
            })
        return out

    def search(self, q: str, limit: int) -> list[Hit]:
        words = [t.lower() for t in terms(q)]
        if not words:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for c in self._candidates():
            ref = f"{c['repo']}#{c['number']}".lower()
            title = (c["title"] or "").lower()
            labels = " ".join(c["labels"]).lower()
            score = 0.0
            ok = True
            for w in words:
                if w in title:
                    score += 3.0
                elif w in ref:
                    score += 2.0
                elif w in labels:
                    score += 1.0
                else:
                    ok = False
                    break
            if not ok:
                continue
            if c["state"] == "open":
                score += 0.5
            scored.append((score, c))
        scored.sort(key=lambda sc: (-sc[0], sc[1]["repo"], sc[1]["number"]))
        out: list[Hit] = []
        for score, c in scored[: max(0, int(limit))]:
            ref = f"{c['repo']}#{c['number']}"
            sub_bits = [ref, c["state"]] + list(c["labels"])
            out.append(Hit(
                kind="issues",
                title=c["title"],
                subtitle=" · ".join(sub_bits),
                snippet=mark_terms(c["title"], q),
                ref=ref,
                url=c["url"],
                score=score,
                extra={
                    "provider": c["provider"], "repo": c["repo"], "number": c["number"],
                    "state": c["state"], "labels": c["labels"], "task_id": c["task_id"],
                    "task_status": c["task_status"],
                },
            ))
        return out
