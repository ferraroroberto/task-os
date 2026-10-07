"""The issue-provider contract — what a forge (GitHub, GitLab) must offer for
issues to become tasks.

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

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol, runtime_checkable

from src.no_window import NO_WINDOW

__all__ = [
    "CliHints", "IssueInfo", "IssueProvider", "IssueProviderError", "NotConfigured", "NullProvider",
    "run_cli", "short_repo",
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


class CliHints(NamedTuple):
    """The stderr fragments a forge CLI uses for each condition (lower-case)."""

    auth: tuple[str, ...]
    rate: tuple[str, ...]
    not_found: tuple[str, ...]

    def classify(self, stderr: str) -> str:
        """The error ``code`` a failed call's stderr names; ``error`` when none match."""
        text = (stderr or "").lower()
        if any(h in text for h in self.auth):
            return "not_authenticated"
        if any(h in text for h in self.rate):
            return "rate_limited"
        if any(h in text for h in self.not_found):
            return "not_found"
        return "error"


def run_cli(
    tool: str, args: Sequence[str], *, timeout: float, label: str, install: str, hints: CliHints,
) -> str:
    """Run ``<tool> <args>`` and return stdout; :class:`IssueProviderError` on any failure.

    The one subprocess-and-classify routine behind both forge CLIs: a missing
    binary is ``not_installed``, a timeout is ``timeout``, and a non-zero exit
    is classified from stderr by ``hints`` and carries its first line.
    """
    try:
        proc = subprocess.run(
            [tool, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise IssueProviderError(f"{tool} not on PATH — install {install}", code="not_installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise IssueProviderError(f"{label}: timed out after {timeout:.0f}s", code="timeout") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise IssueProviderError(f"{label}: {exc}", code="error") from exc
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        first = lines[0].strip() if lines else "no output"
        code = hints.classify(proc.stderr or proc.stdout or "")
        raise IssueProviderError(f"{label} exited {proc.returncode}: {first}", code=code)
    return proc.stdout


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
    spawns ``gh`` or ``glab``).
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
