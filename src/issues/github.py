"""GitHub issue provider — the ``gh`` CLI, JSON in and out.

Same shape as the fleet launcher's ``src/github_client.py``: ``gh`` is a
subprocess per call (``CREATE_NO_WINDOW``, 20 s timeout, UTF-8), never a
library dependency, and it is never invoked on a poll — only by the sync job
(every ``issues.sync_minutes``) and on explicit user demand (↻, create).

    list_open_assigned  gh search issues --assignee <assignee> --state open --owner <owner> --json …
    get                 gh issue view <n> --repo <owner/name> --json …
    create              gh issue create --repo <owner/name> --title … --body … --assignee <assignee>

Failures are classified from the process outcome so the status can name the
condition: ``gh`` missing → ``not_installed`` (reported by ``is_configured``
so the sync never even tries), ``TimeoutExpired`` → ``timeout``, and from
``gh``'s stderr: an auth hint → ``not_authenticated``, a rate-limit line →
``rate_limited``, a 404 / "could not resolve" → ``not_found``; anything else
→ ``error`` with the first stderr line. Never an empty list on failure.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Sequence
from typing import Any

from src.issues.base import CliHints, IssueInfo, IssueProviderError, run_cli

logger = logging.getLogger(__name__)

GH_TIMEOUT_S = 20.0
SEARCH_LIMIT = 300
_FIELDS = "number,title,url,state,labels,updatedAt,body"
_ISSUE_URL_RE = re.compile(r"https?://[^/\s]+/([^/\s]+/[^/\s]+)/issues/(\d+)")

_HINTS = CliHints(
    auth=("gh auth login", "not logged in", "authentication", "http 401", "bad credentials"),
    rate=("rate limit", "secondary rate", "abuse detection"),
    not_found=("could not resolve", "not found", "http 404", "no issues matched"),
)


def run_gh(args: Sequence[str], *, timeout: float = GH_TIMEOUT_S) -> str:
    """Run ``gh <args>`` and return stdout; :class:`IssueProviderError` on any failure."""
    return run_cli(
        "gh", args, timeout=timeout, label="gh " + " ".join(args[:2]),
        install="the GitHub CLI", hints=_HINTS,
    )


def _json(out: str) -> Any:
    try:
        return json.loads(out or "null")
    except ValueError as exc:
        raise IssueProviderError(f"gh returned unparseable JSON: {exc}", code="error") from exc


def _labels(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(lab.get("name")) for lab in (row.get("labels") or [])
        if isinstance(lab, dict) and lab.get("name")
    )


class GitHubProvider:
    """``gh``-backed :class:`~src.issues.base.IssueProvider`."""

    name = "github"

    def __init__(self, owner: str, assignee: str = "@me", *, timeout: float = GH_TIMEOUT_S) -> None:
        self.owner = (owner or "").strip()
        self.assignee = (assignee or "@me").strip() or "@me"
        self.timeout = timeout

    # ------------------------------------------------------------ helpers
    def _info(self, row: dict[str, Any], repo: str | None = None) -> IssueInfo:
        repository = row.get("repository") or {}
        full = repo or str(repository.get("nameWithOwner") or "")
        if not full and repository.get("name"):
            full = f"{self.owner}/{repository['name']}"
        if not full:
            m = _ISSUE_URL_RE.search(str(row.get("url") or ""))
            full = m.group(1) if m else ""
        return IssueInfo(
            provider=self.name,
            repo=full,
            number=int(row.get("number") or 0),
            title=str(row.get("title") or "").strip(),
            url=str(row.get("url") or ""),
            state=str(row.get("state") or "open").lower(),
            labels=_labels(row),
            updated_at=row.get("updatedAt"),
            body=row.get("body"),
        )

    # ----------------------------------------------------------- contract
    def is_configured(self) -> tuple[bool, str | None]:
        if not self.owner:
            return False, "issues.owner is not set in config"
        if shutil.which("gh") is None:
            return False, "gh not on PATH — install the GitHub CLI"
        return True, None

    def list_open_assigned(self) -> list[IssueInfo]:
        rows = _json(run_gh([
            "search", "issues",
            "--assignee", self.assignee,
            "--state", "open",
            "--owner", self.owner,
            "--sort", "updated",
            "--limit", str(SEARCH_LIMIT),
            "--json", _FIELDS + ",repository",
        ], timeout=self.timeout))
        if not isinstance(rows, list):
            raise IssueProviderError("gh search issues: expected a JSON list", code="error")
        issues = [self._info(r) for r in rows if isinstance(r, dict)]
        return [i for i in issues if i.repo and i.number]

    def get(self, repo: str, number: int) -> IssueInfo:
        row = _json(run_gh(["issue", "view", str(int(number)), "--repo", repo, "--json", _FIELDS], timeout=self.timeout))
        if not isinstance(row, dict):
            raise IssueProviderError(f"gh issue view {repo}#{number}: unexpected output", code="error")
        return self._info(row, repo=repo)

    def create(self, repo: str, title: str, body: str) -> IssueInfo:
        out = run_gh([
            "issue", "create", "--repo", repo,
            "--title", title, "--body", body or "",
            "--assignee", self.assignee,
        ], timeout=self.timeout)
        m = _ISSUE_URL_RE.search(out or "")
        if not m:
            raise IssueProviderError(f"gh issue create {repo}: no issue URL in output ({(out or '').strip()[:80]!r})", code="error")
        number = int(m.group(2))
        try:
            return self.get(repo, number)
        except IssueProviderError as exc:  # created, but the read-back failed: still a usable answer
            logger.warning("⚠️ issues: created %s#%d but could not read it back (%s)", repo, number, exc)
            return IssueInfo(provider=self.name, repo=repo, number=number, title=title, url=m.group(0), state="open", body=body)


__all__ = ["GH_TIMEOUT_S", "SEARCH_LIMIT", "GitHubProvider", "run_gh"]
