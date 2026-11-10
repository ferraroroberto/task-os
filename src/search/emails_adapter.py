"""Emails adapter — folder-explorer's v1 email search (:mod:`src.search.folder_explorer`).

task-os opens no email database for search: the words go to folder-explorer,
which ranks (bm25 over subject, sender, recipients and preview) and highlights.
Configured when ``search.folder_explorer_url`` is set; every other state is
:class:`~src.search.folder_explorer.Unavailable` out of :meth:`search`, never
an empty list.

Hit: title = subject (else the file name) · subtitle = ``sender · date ·
folder`` · snippet = the subject or body snippet with ``[match]`` marks · ref =
the ``.msg`` path folded onto the placeholders (``{onedrive}/…/mail.msg`` when it
lies under a configured root, else the absolute path) — what "attach" stores as
``links(kind=email)`` and the per-PC opener opens as a file · url = the
``taskos://open?ref=…`` link · extra = ``path, sender, recipients, date, folder,
filename, email_id``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlencode

from src.placeholders import normalize_path, opener_url, to_ref
from src.search.base import MARK_CLOSE, MARK_OPEN, Hit
from src.search.folder_explorer import OK, FolderExplorerClient

__all__ = ["EmailsAdapter"]


class EmailsAdapter:
    name = "emails"
    kind = "emails"

    def __init__(
        self,
        client: FolderExplorerClient | None,
        placeholders: Mapping[str, str] | None = None,
        deep_url: str = "",
    ) -> None:
        self.client = client
        self.placeholders = dict(placeholders or {})
        self.deep_url = (deep_url or "").strip()

    def deep_link(self, q: str) -> str | None:
        """folder-explorer's email search for the same words, or ``None`` when no page is set."""
        if not self.deep_url or not q.strip():
            return None
        return self.deep_url.split("#", 1)[0] + "#search?" + urlencode({"mode": "emails", "q": q.strip()}, quote_via=quote)

    def is_configured(self) -> tuple[bool, str | None]:
        if self.client is None or not self.client.configured:
            return False, "search.folder_explorer_url not configured"
        return True, None

    def availability(self) -> tuple[str, str | None, str | None]:
        """``(state, reason, note)`` from folder-explorer's status — the Settings row; one request."""
        assert self.client is not None
        state, reason, detail = self.client.part_state("emails")
        note = f"{detail['count']} mail(s)" if state == OK and detail.get("count") is not None else None
        return state, reason, note

    def search(self, q: str, limit: int) -> list[Hit]:
        assert self.client is not None
        body = self.client.emails(q, limit)
        start, end = (body.get("marks") or {}).get("start"), (body.get("marks") or {}).get("end")
        hits = body.get("hits") or []
        # folder-explorer sends hits best first and no score, so the rank is the score.
        return [self._hit(h, start, end, float(len(hits) - i)) for i, h in enumerate(hits)]

    def _hit(self, e: Mapping[str, Any], start: str | None, end: str | None, score: float) -> Hit:
        path = normalize_path(str(e.get("path") or ""))
        ref = to_ref(path, self.placeholders)
        subject_marked = self._marks(str(e.get("subject") or ""), start, end)
        subject = subject_marked.replace(MARK_OPEN, "").replace(MARK_CLOSE, "").strip() or str(
            e.get("filename") or path.rsplit("/", 1)[-1])
        snippet = subject_marked if MARK_OPEN in subject_marked else self._marks(str(e.get("snippet") or ""), start, end)
        sender = str(e.get("from_name") or e.get("from_addr") or "").strip()
        folder = normalize_path(str(e.get("folder") or ""))
        sub_bits = [b for b in (sender, str(e.get("date") or "")[:10], folder.rsplit("/", 1)[-1]) if b]
        return Hit(
            kind="emails",
            title=subject,
            subtitle=" · ".join(sub_bits),
            snippet=snippet,
            ref=ref,
            url=opener_url(ref),
            score=score,
            extra={
                "email_id": e.get("id"),
                "path": path,
                "sender": sender,
                "recipients": e.get("recipients"),
                "date": e.get("date"),
                "folder": folder,
                "filename": e.get("filename"),
            },
        )

    @staticmethod
    def _marks(text: str, start: str | None, end: str | None) -> str:
        """folder-explorer's private-use match marks → the ``[`` ``]`` every group's snippet uses."""
        if start and end:
            return text.replace(start, MARK_OPEN).replace(end, MARK_CLOSE)
        return text
