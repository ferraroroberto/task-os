"""Thin client for folder-explorer's v1 search API (``/api/v1/search/...``).

folder-explorer is the fleet's one folder and email search; task-os asks it
over HTTP and keeps no index of its own. Every call ends in exactly one of
five states, so a caller never reads "folder-explorer is down" or "it has
nothing to search yet" as "no match":

- ``ok``              the answer is the part's real result (an empty list is "no match");
- ``indexing``        the part has nothing to search yet, its first build is running;
- ``not-configured``  folder-explorer cannot search that part on its PC, or this
                      install names no folder-explorer address at all;
- ``failed``          folder-explorer answered but could not read its index, or
                      answered something that is not the contract;
- ``unreachable``     the request itself failed (connection refused, timeout).

Anything but ``ok`` raises :class:`Unavailable` carrying the state and a
plain-text reason; the federated layer turns it into a group's visible
"unavailable" state. The states are taken from the answer as folder-explorer
sends them: this module does not second-guess one (``docs/service-api.md`` in
that repo is the contract).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import requests

from src.pooled_http import pooled_request

logger = logging.getLogger(__name__)

__all__ = [
    "FAILED", "INDEXING", "NOT_CONFIGURED", "OK", "UNREACHABLE", "FolderExplorerClient", "Unavailable",
]

OK, INDEXING, NOT_CONFIGURED, FAILED, UNREACHABLE = "ok", "indexing", "not-configured", "failed", "unreachable"
SCHEMA_VERSION = 1
#: A hung folder-explorer must not hold the Search tab: the federated layer
#: bounds each group at 2 s, so the request gives up a little sooner.
DEFAULT_TIMEOUT_S = 1.8
#: How the wire names a state → the name used here. folder-explorer reports a
#: part it could not read as ``error`` today; ``failed`` is the same state.
_WIRE_STATES = {"ok": OK, "indexing": INDEXING, "not-configured": NOT_CONFIGURED, "error": FAILED, "failed": FAILED}
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class Unavailable(Exception):
    """A search part that cannot answer right now: its ``state`` and a plain-text ``reason``."""

    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"{state}: {reason}")
        self.state = state
        self.reason = reason


class FolderExplorerClient:
    """One folder-explorer address; calls are read-only GETs over the shared keep-alive pool."""

    def __init__(self, base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout_s = float(timeout_s)
        parts = urlsplit(self.base_url)
        # folder-explorer's certificate names the tailnet host, so a loopback
        # https address cannot verify; a non-loopback one always does.
        self._verify = not (parts.scheme == "https" and (parts.hostname or "") in _LOOPBACK)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def host(self) -> str:
        """The address with no path or credentials — what a log line or a reason may show."""
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")

    def summary(self) -> dict[str, Any]:
        """What this install is set to — no request, so ``/api/status`` never waits on folder-explorer.

        The live state of each part is :meth:`part_state` (the Search sheet's rows).
        """
        if not self.configured:
            return {"enabled": False, "reason": "search.folder_explorer_url not configured", "url": None}
        return {"enabled": True, "reason": None, "url": self.host}

    def status(self) -> dict[str, Any]:
        """``GET /api/v1/search/status`` — each part's state (the route itself answers ``ok``)."""
        return self._get("/api/v1/search/status", {})

    def folders(self, q: str, limit: int, within: list[str] | None = None) -> dict[str, Any]:
        """``GET /api/v1/search/folders``; the body when ``ok``, else :class:`Unavailable`."""
        params: dict[str, Any] = {"q": q, "limit": limit}
        if within:
            params["within"] = list(within)
        return self._get("/api/v1/search/folders", params)

    def emails(self, q: str, limit: int) -> dict[str, Any]:
        """``GET /api/v1/search/emails``; the body when ``ok``, else :class:`Unavailable`."""
        return self._get("/api/v1/search/emails", {"q": q, "limit": limit})

    def post(self, path: str, body: dict[str, Any], timeout_s: float) -> requests.Response:
        """One JSON POST over the shared pool, never resent: a write whose reply was lost may have run.

        The archive client interprets the answer; transport errors propagate as ``requests`` ones.
        """
        return pooled_request("POST", self.base_url + path, timeout=timeout_s, json=body, verify=self._verify)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise Unavailable(NOT_CONFIGURED, "search.folder_explorer_url is not set")
        try:
            resp = pooled_request("GET", self.base_url + path, timeout=self.timeout_s, params=params,
                                  verify=self._verify)
        except requests.RequestException as exc:
            logger.warning("⚠️ folder-explorer %s: %s", path, type(exc).__name__)
            raise Unavailable(UNREACHABLE, f"folder-explorer at {self.host} did not answer ({type(exc).__name__})") from exc
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or "state" not in body:
            # A 422 (a query out of range) or a proxy page: no envelope to read.
            logger.warning("⚠️ folder-explorer %s: HTTP %s without a v1 envelope", path, resp.status_code)
            raise Unavailable(FAILED, f"folder-explorer answered HTTP {resp.status_code} without a v1 envelope")
        if body.get("schema_version") != SCHEMA_VERSION:
            raise Unavailable(FAILED, f"folder-explorer speaks schema_version {body.get('schema_version')!r}, not {SCHEMA_VERSION}")
        state = _WIRE_STATES.get(str(body["state"]))
        if state is None:
            raise Unavailable(FAILED, f"folder-explorer answered an unknown state {body['state']!r}")
        if state != OK:
            raise Unavailable(state, str(body.get("reason") or f"folder-explorer reports {state}"))
        return body

    def part_state(self, part: str) -> tuple[str, str | None, dict[str, Any]]:
        """``(state, reason, detail)`` of ``"folders"`` or ``"emails"`` from the status route.

        ``detail`` is that part's own fields (counts); empty unless the part is ``ok``.
        """
        try:
            body = self.status()
        except Unavailable as exc:
            return exc.state, exc.reason, {}
        section = body.get(part)
        if not isinstance(section, dict) or "state" not in section:
            return FAILED, f"folder-explorer's status has no {part} section", {}
        state = _WIRE_STATES.get(str(section["state"]))
        if state is None:
            return FAILED, f"folder-explorer reported an unknown {part} state {section['state']!r}", {}
        reason = section.get("reason")
        return state, (str(reason) if reason else None), (section if state == OK else {})
