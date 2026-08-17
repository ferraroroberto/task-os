"""Tasks adapter — ``tasks_fts`` + ``comments_fts`` through :func:`src.tasks_repo.search`.

Always configured (the database is the app). Each call opens its own
connection (``conn_factory``, default :func:`src.db.connect`) because the
adapters run concurrently in a thread pool.

Hit: title = the task title · subtitle = ``breadcrumb › … · status`` ·
snippet = the FTS snippet with ``[match]`` marks · ref = the id · url =
``#task/<id>`` · extra = ``task_id, code, status, priority, due, matched_in,
breadcrumb, folder_ref, issue_ref`` (what the row's chips need).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from src import tasks_repo as repo
from src.db import connect
from src.search.base import Hit

__all__ = ["TasksAdapter"]


class TasksAdapter:
    name = "tasks"
    kind = "tasks"

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection] | None = None) -> None:
        self._connect = conn_factory or connect

    def is_configured(self) -> tuple[bool, str | None]:
        return True, None

    def search(self, q: str, limit: int) -> list[Hit]:
        conn = self._connect()
        try:
            items = repo.search(conn, q, limit=limit)
        finally:
            conn.close()
        return [self._hit(t) for t in items]

    @staticmethod
    def _hit(t: dict[str, Any]) -> Hit:
        crumbs = " › ".join(c["title"] for c in (t.get("breadcrumb") or []))
        sub_bits = [b for b in (crumbs, t.get("status") or "", t.get("code") or "") if b]
        return Hit(
            kind="tasks",
            title=t.get("title") or f"#{t['id']}",
            subtitle=" · ".join(sub_bits),
            snippet=t.get("snippet") or "",
            ref=str(t["id"]),
            url=f"#task/{t['id']}",
            score=-float(t.get("rank") or 0.0),
            extra={
                "task_id": int(t["id"]),
                "code": t.get("code"),
                "status": t.get("status"),
                "priority": t.get("priority"),
                "due": t.get("due"),
                "type": t.get("type"),
                "matched_in": t.get("matched_in"),
                "breadcrumb": t.get("breadcrumb") or [],
                "folder_ref": t.get("folder_ref"),
                "issue_ref": t.get("issue_ref"),
            },
        )
