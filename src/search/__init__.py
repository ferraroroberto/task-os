"""Federated search (Step 10) — one query over four indexes, grouped by kind.

    base.py             the SearchAdapter protocol + Hit shape, FTS/mark helpers
    tasks_adapter.py    tasks_fts + comments_fts (src.tasks_repo.search)
    folder_explorer.py  the client for folder-explorer's v1 search API (five states, one exception)
    folders_adapter.py  folder search through that client
    emails_adapter.py   email search through that client
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
