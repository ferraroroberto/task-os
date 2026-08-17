"""The issue-provider contract — what a forge (GitHub today, GitLab with a
later step) must offer for issues to become tasks.

Read-mostly by design (plan §05): a provider *lists* the open issues assigned
to the configured user, *reads* one issue, and *creates* one from a task.
task-os never edits titles / labels or closes issues remotely in v1 — the
sync writes only into the local database (``src/issue_sync.py``).

Every failure is a :class:`IssueProviderError` with a ``code`` naming the
condition (``not_installed`` · ``not_authenticated`` · ``timeout`` ·
``rate_limited`` · ``not_found`` · ``error``) so the sync status, the
Settings card and ``tasks issues status`` can show *which* thing is wrong —
never an empty list masquerading as "no issues".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "IssueInfo", "IssueProvider", "IssueProviderError", "NotConfigured", "NullProvider",
    "short_repo",
]


class IssueProviderError(RuntimeError):
    """A provider call failed; ``code`` names the condition (see module doc)."""

    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


class NotConfigured(IssueProviderError):
    """The provider cannot run at all (no owner, tool missing, provider ``none``)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="not_configured")


@dataclass(frozen=True)
class IssueInfo:
    """One issue as the forge reports it — the sync's input shape."""

    provider: str
    repo: str                       # full path, e.g. ``owner/name``
    number: int
    title: str
    url: str
    state: str                      # ``open`` | ``closed`` (lower-case)
    labels: tuple[str, ...] = ()
    updated_at: str | None = None
    body: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.provider, self.repo, self.number)

    @property
    def ref(self) -> str:
        """``owner/name#N`` — the label the chips and comments use."""
        return f"{self.repo}#{self.number}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "repo": self.repo, "number": self.number, "title": self.title,
            "url": self.url, "state": self.state, "labels": list(self.labels),
            "updated_at": self.updated_at, "body": self.body,
        }


def short_repo(repo: str) -> str:
    """``owner/name`` → ``name`` (the task ``code`` uses the short form)."""
    return (repo or "").rstrip("/").split("/")[-1]


@runtime_checkable
class IssueProvider(Protocol):
    """What ``src/issue_sync.py`` and the issues router need from a forge."""

    name: str

    def is_configured(self) -> tuple[bool, str | None]:
        """``(True, None)`` when calls can be attempted; else ``(False, reason)``."""

    def list_open_assigned(self) -> list[IssueInfo]:
        """Open issues assigned to the configured user across the owner's repos."""

    def get(self, repo: str, number: int) -> IssueInfo:
        """One issue, any state — ``not_found`` when it does not exist."""

    def create(self, repo: str, title: str, body: str) -> IssueInfo:
        """Open a new issue and return it (assigned to the configured user)."""


class NullProvider:
    """The "no provider" provider — every call says so instead of pretending.

    Selected when ``issues.provider`` is blank / ``none`` / unknown, or forced
    with ``TASKOS_ISSUE_PROVIDER=none`` (the unit-test default, so no test ever
    spawns ``gh``). A GitLab implementation is a later step: register it in
    ``src/issues/__init__.py::get_provider`` next to GitHub.
    """

    name = "none"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def is_configured(self) -> tuple[bool, str | None]:
        return False, self.reason

    def list_open_assigned(self) -> list[IssueInfo]:
        raise NotConfigured(self.reason)

    def get(self, repo: str, number: int) -> IssueInfo:
        raise NotConfigured(self.reason)

    def create(self, repo: str, title: str, body: str) -> IssueInfo:
        raise NotConfigured(self.reason)
