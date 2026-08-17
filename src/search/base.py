"""The search-adapter contract — one shape for every index the search box reads.

An adapter wraps one index (``tasks_fts``, the folder index, the email
archiver's ``emails_fts``, the issue cache) and answers two questions:

- :meth:`SearchAdapter.is_configured` → ``(True, None)`` when the index can be
  queried on this install, else ``(False, reason)`` — the federated layer turns
  that into a group with ``configured: false`` and the reason, so a missing
  index is a **visible state**, never an empty result;
- :meth:`SearchAdapter.search` → a list of :class:`Hit`, best first.

Every hit carries the same keys whatever the kind (:meth:`Hit.to_dict`), so
the Search tab renders one row template and the CLI one line format:

    kind      tasks | folders | emails | issues
    title     the one line a human scans (task title, folder name, subject, issue title)
    subtitle  where / who (breadcrumb · status, the portable ref, sender · date · folder, repo#N · state)
    snippet   the matched text with ``[`` ``]`` around the matched terms (the UI renders <mark>)
    ref       what "attach" stores: the task id, the folder ref, the .msg ref, the issue ``owner/repo#N``
    url       what "open" follows: ``#task/<id>``, a ``taskos://open?ref=…`` link, the issue URL
    score     higher = better (bm25 negated, or a term-count)
    extra     kind-specific fields the row actions need (task status / code, folder path,
              email sender / date / folder, issue repo / number / provider / state / labels / task_id)

Adapters run in a thread pool (:mod:`src.search.federated`), so each opens
its own database connection per call — never a shared one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = ["KINDS", "Hit", "SearchAdapter", "fts_query", "mark_terms", "terms"]

KINDS: tuple[str, ...] = ("tasks", "folders", "emails", "issues")
MARK_OPEN = "["
MARK_CLOSE = "]"


@dataclass
class Hit:
    kind: str
    title: str
    subtitle: str = ""
    snippet: str = ""
    ref: str = ""
    url: str = ""
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "snippet": self.snippet,
            "ref": self.ref,
            "url": self.url,
            "score": round(float(self.score), 4),
            **self.extra,
        }


@runtime_checkable
class SearchAdapter(Protocol):
    """What :class:`src.search.federated.FederatedSearch` needs from one index."""

    name: str
    kind: str

    def is_configured(self) -> tuple[bool, str | None]:
        """``(True, None)`` when :meth:`search` can run here; else ``(False, why)``."""

    def search(self, q: str, limit: int) -> list[Hit]:
        """Best-first hits for ``q``; empty when nothing matches (never on error — raise)."""


def terms(q: str) -> list[str]:
    """The non-empty whitespace-separated words of a query, order kept."""
    return [t for t in (q or "").split() if t.strip()]


def fts_query(q: str) -> str:
    """Free text → a safe FTS5 MATCH string: every word a quoted prefix term, ANDed.

    Same recipe as ``src.tasks_repo._fts_query`` — quotes defuse ``#``, ``-``,
    ``:`` and friends; the trailing ``*`` makes ``pass`` hit ``passport``.
    """
    return " ".join('"' + t.replace('"', '""') + '"*' for t in terms(q))


def mark_terms(text: str, q: str) -> str:
    """Wrap every case-insensitive occurrence of each query word in ``[`` ``]``.

    For indexes with no snippet function (the folder index's substring search,
    the LIKE fallback) so their hits highlight the same way FTS snippets do.
    """
    words = sorted(set(terms(q)), key=len, reverse=True)      # longest first: one pass, no nesting
    if not words or not text:
        return text or ""
    pattern = "(" + "|".join(re.escape(w) for w in words) + ")"
    return re.sub(pattern, lambda m: MARK_OPEN + m.group(1) + MARK_CLOSE, text, flags=re.IGNORECASE)
