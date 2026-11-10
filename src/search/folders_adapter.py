"""Folders adapter — folder-explorer's v1 folder search (:mod:`src.search.folder_explorer`).

task-os holds no folder index: the words go to folder-explorer and the hits
come back with this PC's path, which :func:`folder_item` folds onto the
placeholders so attaching a hit to a task stores a portable ref, never this
PC's path. Configured when ``search.folder_explorer_url`` is set; every other
state (folder-explorer down, still on its first scan, nothing set up there)
is :class:`~src.search.folder_explorer.Unavailable` out of :meth:`search`, a
visible group state and never an empty list.

Hit: title = the folder name · subtitle = the portable ref (``{onedrive}/…``)
· snippet = the resolved path with ``[match]`` marks · ref = the portable ref ·
url = the ``taskos://open?ref=…`` opener link · extra = ``path, name, depth``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.placeholders import normalize_path, opener_url, to_ref
from src.search.base import Hit, mark_terms
from src.search.folder_explorer import OK, FolderExplorerClient

__all__ = ["FoldersAdapter", "folder_item"]


def folder_item(hit: Mapping[str, Any], placeholders: Mapping[str, str]) -> dict[str, Any]:
    """One folder-explorer folder hit → ``{path, ref, name, depth}``, the shape the folder picker reads."""
    path = normalize_path(str(hit.get("path") or ""))
    return {
        "path": path,
        "ref": to_ref(path, placeholders),
        "name": str(hit.get("name") or path.rsplit("/", 1)[-1] or path),
        "depth": hit.get("depth"),
    }


class FoldersAdapter:
    name = "folders"
    kind = "folders"

    def __init__(self, client: FolderExplorerClient | None, placeholders: Mapping[str, str] | None = None) -> None:
        self.client = client
        self.placeholders = dict(placeholders or {})

    def is_configured(self) -> tuple[bool, str | None]:
        if self.client is None or not self.client.configured:
            return False, "search.folder_explorer_url not configured"
        return True, None

    def availability(self) -> tuple[str, str | None, str | None]:
        """``(state, reason, note)`` from folder-explorer's status — the Settings row; one request."""
        assert self.client is not None
        state, reason, detail = self.client.part_state("folders")
        note = None
        if state == OK:
            note = f"{detail.get('scanned', '?')} of {detail.get('roots', '?')} root(s) scanned"
            if detail.get("scanning"):
                note += " · scanning now"
        return state, reason, note

    def search(self, q: str, limit: int) -> list[Hit]:
        assert self.client is not None
        out: list[Hit] = []
        for r in self.client.folders(q, limit).get("results") or []:
            item = folder_item(r, self.placeholders)
            out.append(Hit(
                kind="folders",
                title=item["name"],
                subtitle=item["ref"],
                snippet=mark_terms(item["path"], q),
                ref=item["ref"],
                url=opener_url(item["ref"]),
                score=float(r.get("score") or 0.0),
                extra={"path": item["path"], "name": item["name"], "depth": item["depth"]},
            ))
        return out
