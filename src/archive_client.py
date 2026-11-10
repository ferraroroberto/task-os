"""Thin client for folder-explorer's v1 archive API (``/api/v1/archive/{plan,apply,revert,index}``).

folder-explorer owns Outlook, the filenames and its email index; task-os asks it
over HTTP and decides only *which folder*. Every call ends in exactly one of
these, so a caller never reads "folder-explorer is down" as "nothing to do" or
an acknowledged call as a confirmed mail:

- the archiver's own document, returned as ``result`` — for ``plan`` always, and
  for ``apply`` / ``revert`` whenever the verb ran, even when some or all of its
  mails failed (each mail's own ``ok`` / ``error`` is what the run records);
- an :class:`~src.archive_actions.ArchiveError` with a code that names the
  condition: ``archive_unreachable`` (no answer at all), ``archive_timeout``,
  ``archive_busy`` (folder-explorer is serving another archive call),
  ``archive_outlook_unavailable``, ``archive_child_unconfigured``,
  ``archive_not_this_pc``, ``archive_refused``, ``archive_not_found``,
  ``archive_child_failed``, ``archive_bad_output`` and ``archive_schema_mismatch``.

``docs/service-api.md`` in folder-explorer is the contract. A write verb whose
answer is missing or unreadable says plainly that nothing is confirmed: plan
again before assuming either way.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from src.archive_actions import ArchiveError
from src.search.folder_explorer import FolderExplorerClient

logger = logging.getLogger(__name__)

__all__ = ["ArchiveApiClient", "SCHEMA_VERSION"]

SCHEMA_VERSION = 1
_PATH = "/api/v1/archive/"
#: Verbs that write files or move mail: a call of these without an answer leaves
#: the outcome unknown, which the message has to say.
_WRITE_VERBS = frozenset({"apply", "revert"})
_UNCONFIRMED = " — nothing is confirmed, so plan again before assuming it was or was not done"

#: Codes that mean Outlook (or the COM bridge) could not be reached, nothing touched.
_OUTLOOK_CODES = frozenset({"outlook_unavailable", "com_unavailable", "outlook_off"})
#: Codes that mean folder-explorer's own archiver config could not be loaded.
_CONFIG_CODES = frozenset({"config_missing", "mailbox_registry_invalid"})


class ArchiveApiClient:
    """One folder-explorer address; each call is a POST over the shared keep-alive pool."""

    def __init__(self, base: FolderExplorerClient) -> None:
        self._base = base

    @property
    def configured(self) -> bool:
        return self._base.configured

    @property
    def host(self) -> str:
        return self._base.host

    def run(self, verb: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """``POST /api/v1/archive/<verb>`` → the archiver's document, or :class:`ArchiveError`.

        ``timeout`` is how long this app waits for the answer. It has to outlast
        folder-explorer's own budget for the verb, so that a stuck Outlook comes
        back as folder-explorer's typed ``timeout`` and not as this side giving
        up first.
        """
        reply = self.call(verb, body, timeout=timeout)
        return self._document(verb, reply)

    def call(self, verb: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """The raw envelope; :class:`ArchiveError` only when there is no readable v1 envelope."""
        if not self.configured:
            raise ArchiveError(
                "archive_disabled", "search.folder_explorer_url is not set, so there is no archive service to call",
                http_status=409,
            )
        logger.info("ℹ️ archive: %s — asking folder-explorer at %s", verb, self.host)
        suffix = _UNCONFIRMED if verb in _WRITE_VERBS else ""
        try:
            resp = self._base.post(_PATH + verb, body, timeout)
        except requests.exceptions.Timeout as exc:
            raise ArchiveError(
                "archive_timeout",
                f"folder-explorer at {self.host} did not answer {verb} within {timeout:g} s{suffix}",
                http_status=504,
            ) from exc
        except requests.RequestException as exc:
            raise ArchiveError(
                "archive_unreachable",
                f"folder-explorer at {self.host} did not answer ({type(exc).__name__}){suffix}",
                http_status=502,
            ) from exc
        try:
            doc = resp.json()
        except ValueError:
            doc = None
        if not isinstance(doc, dict) or "outcome" not in doc:
            # A 422 (FastAPI's validation body), a proxy page, a build without the archive routes.
            raise ArchiveError(
                "archive_bad_output",
                f"folder-explorer answered {verb} with HTTP {resp.status_code} and no v1 archive envelope{suffix}",
                http_status=502, detail=(resp.text or "")[-800:] or None,
            )
        if doc.get("schema_version") != SCHEMA_VERSION:
            raise ArchiveError(
                "archive_schema_mismatch",
                f"folder-explorer's archive API is schema_version {doc.get('schema_version')!r}; "
                f"this build understands {SCHEMA_VERSION}",
                http_status=502,
            )
        return doc

    def index(self, root: str, wait: float, *, timeout: float) -> str | None:
        """Re-index one filed folder → ``None`` when indexed, else the plain-text reason it was not.

        Not an exception: the mails are filed either way, so the caller records
        the reason on the run instead of failing it.
        """
        try:
            reply = self.call("index", {"root": root, "wait": wait}, timeout=timeout)
        except ArchiveError as exc:
            return str(exc)
        if reply.get("outcome") == "done":
            return None
        code, reason = str(reply.get("code") or ""), str(reply.get("reason") or "")
        return f"{reason} ({code})" if reason and code else (reason or code or "the re-index failed")

    def _document(self, verb: str, reply: dict[str, Any]) -> dict[str, Any]:
        """The archiver's document for a ran verb; otherwise the one error its outcome names."""
        outcome = str(reply.get("outcome") or "")
        code = str(reply.get("code") or "")
        reason = str(reply.get("reason") or "")
        result = reply.get("result")
        doc = result if isinstance(result, dict) else None
        suffix = _UNCONFIRMED if verb in _WRITE_VERBS else ""

        if reply.get("acknowledged") and doc is not None and "error" not in doc:
            if verb == "plan" and outcome == "done":
                return doc
            # Each mail carries its own result, so a failed mail is a recorded state, not a failed call.
            if verb in _WRITE_VERBS and isinstance(doc.get("results"), list):
                return doc
        raise self._error(verb, outcome, code, reason, suffix)

    def _error(self, verb: str, outcome: str, code: str, reason: str, suffix: str) -> ArchiveError:
        said = f"{reason} ({code})" if reason and code else (reason or code or outcome)
        if code == "busy":
            return ArchiveError(
                "archive_busy",
                f"folder-explorer is already running an archive call — one Outlook, one call at a time: {said}",
                http_status=409,
            )
        if code == "not_this_pc":
            return ArchiveError(
                "archive_not_this_pc",
                f"folder-explorer only archives for a caller on its own PC: {said}", http_status=502, detail=code,
            )
        if code in _OUTLOOK_CODES:
            return ArchiveError(
                "archive_outlook_unavailable",
                f"Outlook could not be reached, so no mail was touched by {verb}: {said}", http_status=502, detail=code,
            )
        if code in _CONFIG_CODES:
            return ArchiveError(
                "archive_child_unconfigured",
                f"the email archiver's own config could not be loaded: {said}", http_status=502, detail=code,
            )
        if code == "timeout":
            return ArchiveError(
                "archive_timeout",
                f"folder-explorer's archiver did not finish {verb}: {said}{suffix}", http_status=504,
            )
        if code in ("no_answer", "spawn_failed", "schema_mismatch"):
            return ArchiveError(
                "archive_bad_output", f"folder-explorer's archiver gave no readable {verb} answer: {said}{suffix}",
                http_status=502, detail=code,
            )
        if outcome == "not-found":
            return ArchiveError("archive_not_found", f"the archiver found nothing for {verb}: {said}", http_status=502, detail=code)
        if outcome == "refused":
            return ArchiveError("archive_refused", f"the archiver refused {verb}: {said}", http_status=502, detail=code)
        return ArchiveError(
            "archive_child_failed",
            f"the archiver failed {verb}: {said}" + ("; mails may be filed, plan again" if verb in _WRITE_VERBS else ""),
            http_status=502, detail=code or outcome,
        )
