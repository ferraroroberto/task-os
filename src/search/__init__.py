"""Federated search (Step 10) — one query over four indexes, grouped by kind.

    base.py             the SearchAdapter protocol + Hit shape, FTS/mark helpers
    tasks_adapter.py    tasks_fts + comments_fts (src.tasks_repo.search)
    folders_adapter.py  the folder index (src.folder_index)
    emails_adapter.py   the email archiver's emails.db, read-only (FTS5 bm25, LIKE fallback)
    issues_adapter.py   issue_refs + the sync's cached open list (no forge call per keystroke)
    federated.py        run them concurrently (2 s each), always four groups, unconfigured = visible

Entry points: :func:`build_federated` (the webapp lifespan → ``app.state.search``,
the CLI's local backend) and :class:`FederatedSearch.search`.
"""

from src.search.base import KINDS, Hit, SearchAdapter
from src.search.federated import (
    ADAPTER_TIMEOUT_S,
    DEFAULT_LIMIT,
    FederatedSearch,
    build_federated,
    parse_kinds,
)

__all__ = [
    "ADAPTER_TIMEOUT_S", "DEFAULT_LIMIT", "KINDS", "FederatedSearch", "Hit", "SearchAdapter",
    "build_federated", "parse_kinds",
]
