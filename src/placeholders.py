"""Folder refs ↔ absolute paths — the placeholder contract (Step 9).

A folder ref is stored **unresolved**: ``{onedrive}/house/kitchen``,
``{user}/code/garden-bot``, ``{sharepoint:docs}/plans``. Two things resolve
it, never the browser:

- **this server**, for display (the chip tooltip, the phone's copy popover,
  the drawer's field) — :func:`resolve` with ``config.placeholders``, where a
  ``{sharepoint:<name>}`` token reads ``placeholders.sharepoint.<name>``
  (flattened by ``src.config`` to the key ``sharepoint:<name>``);
- **the per-PC opener** (``opener/opener.cmd``), for opening — the same tokens
  from that PC's environment (``%OneDrive%`` / ``%OneDriveCommercial%``,
  ``%USERNAME%``) and its ``opener.env``.

:func:`to_ref` is the reverse mapping for a pasted absolute path (the drawer's
Folder field, the folder-index picker): the **longest** configured value that
prefixes the path, on a segment boundary, case-insensitively, becomes the
token — ``E:/onedrive/house`` → ``{onedrive}/house``. Paths are compared and
returned with forward slashes (the folder index and the config use them; the
opener flips them for Explorer).

Unknown tokens are left verbatim and reported in ``unresolved`` — an
unestablished fact is its own visible state, never a silently wrong path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from urllib.parse import quote

from src.config import resolve_placeholders, unresolved_placeholders

OPENER_SCHEME = "taskos"
_TOKEN_START = "{"


def normalize_path(path: str) -> str:
    """Forward slashes, no duplicate separators, no trailing slash (drive roots keep ``X:/``)."""
    p = (path or "").strip().replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    if len(p) > 3 and p.endswith("/"):
        p = p.rstrip("/")
    if len(p) == 2 and p[1] == ":":
        p += "/"
    return p


def is_ref(value: str) -> bool:
    """``True`` when the value carries at least one ``{token}``."""
    return bool(unresolved_placeholders(value or ""))


def opener_url(ref: str) -> str:
    """The ``taskos://open?ref=…`` link the folder chip carries (``encodeURIComponent``-style)."""
    return f"{OPENER_SCHEME}://open?ref={quote(ref or '', safe='')}"


@dataclass(frozen=True)
class Resolved:
    """What the API hands the UI for one ref."""

    ref: str
    path: str
    resolved: bool
    unresolved: list[str] = field(default_factory=list)

    @property
    def href(self) -> str:
        return opener_url(self.ref)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["href"] = self.href
        return d


def resolve(ref: str, placeholders: Mapping[str, str]) -> Resolved:
    """Expand every known ``{token}`` in ``ref``; unknown ones stay and are listed.

    A value with no token at all (an absolute path pasted as-is) resolves to
    itself. The result path uses forward slashes.
    """
    ref = (ref or "").strip()
    expanded = resolve_placeholders(ref, placeholders)
    missing = unresolved_placeholders(expanded)
    return Resolved(
        ref=ref,
        path=normalize_path(expanded) if expanded else "",
        resolved=not missing and bool(expanded),
        unresolved=missing,
    )


def to_ref(path: str, placeholders: Mapping[str, str]) -> str:
    """Absolute path → the shortest ref the configured placeholders allow.

    Longest configured value wins (``{sharepoint:docs}`` = ``E:/onedrive/Tenant/docs``
    beats ``{onedrive}`` = ``E:/onedrive``); the match must end on a segment
    boundary so ``E:/onedrive2/x`` never becomes ``{onedrive}2/x``. A value
    that already carries a token is returned normalized, untouched otherwise.
    """
    raw = (path or "").strip()
    if not raw:
        return ""
    if is_ref(raw):
        return normalize_path(raw)
    p = normalize_path(raw)
    p_low = p.lower()
    best_name = ""
    best_len = 0
    for name, value in placeholders.items():
        v = normalize_path(str(value or ""))
        if not v:
            continue
        v_low = v.lower()
        if p_low == v_low:
            candidate_len = len(v)
        elif p_low.startswith(v_low.rstrip("/") + "/"):
            candidate_len = len(v.rstrip("/"))
        else:
            continue
        if candidate_len > best_len:
            best_len = candidate_len
            best_name = name
    if not best_name:
        return p
    rest = p[best_len:].lstrip("/")
    return _TOKEN_START + best_name + "}" + ("/" + rest if rest else "")
