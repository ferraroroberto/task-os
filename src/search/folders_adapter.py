"""Folders adapter — the folder index (:class:`src.folder_index.FolderIndexService`, Step 9).

Configured when the service is (``search.folder_roots`` set and at least one
root usable on this PC); otherwise the service's own ``reason`` is the group's
reason. An index that is still building is *configured* with no hits yet —
the ``note`` says so.

Hit: title = the folder name · subtitle = the portable ref (``{onedrive}/…``)
· snippet = the resolved path with ``[match]`` marks (substring search has no
snippet function, so :func:`mark_terms` does it) · ref = the portable ref ·
url = the ``taskos://open?ref=…`` opener link · extra = ``path, name, depth``.
"""

from __future__ import annotations

from typing import Any

from src.placeholders import opener_url
from src.search.base import Hit, mark_terms

__all__ = ["FoldersAdapter"]


class FoldersAdapter:
    name = "folders"
    kind = "folders"

    def __init__(self, service: Any | None) -> None:
        self.service = service

    def is_configured(self) -> tuple[bool, str | None]:
        if self.service is None:
            return False, "folder index service not started"
        if not self.service.enabled:
            return False, self.service.reason or "folder index not configured"
        return True, None

    def note(self) -> str | None:
        """A configured-but-not-ready state the group shows next to the count."""
        if self.service is None or not self.service.enabled:
            return None
        st = self.service.status()
        if st.get("indexing"):
            return "index still building"
        if not st.get("entries"):
            return "index empty — reindex from Settings"
        return None

    def search(self, q: str, limit: int) -> list[Hit]:
        out: list[Hit] = []
        for i, f in enumerate(self.service.search(q, limit=limit)):
            out.append(Hit(
                kind="folders",
                title=f["name"],
                subtitle=f["ref"],
                snippet=mark_terms(f["path"], q),
                ref=f["ref"],
                url=opener_url(f["ref"]),
                score=float(limit - i),                 # the index already orders by relevance
                extra={"path": f["path"], "name": f["name"], "depth": f.get("depth")},
            ))
        return out
