"""Issue providers — ``get_provider(config)`` picks the forge for this install.

    issues.provider = "github"   → GitHubProvider(owner, assignee)   (src/issues/github.py)
    issues.provider = "gitlab"   → arrives with a later step: add the class next to
                                   GitHub in ``_PROVIDERS`` below — the sync, the
                                   router, the CLI and the UI are provider-agnostic
    anything else / blank        → NullProvider (reports *not configured*, never syncs)

Env override (tests, the e2e disposable instance): ``TASKOS_ISSUE_PROVIDER``
= ``none`` (force the NullProvider so no test spawns ``gh``) or ``fake``
(``src/issues/fake.py`` over ``TASKOS_ISSUE_FAKE_PATH``).
"""

from __future__ import annotations

import os
from collections.abc import Callable

from src.config import AppConfig
from src.issues.base import (
    IssueInfo,
    IssueProvider,
    IssueProviderError,
    NotConfigured,
    NullProvider,
    short_repo,
)

PROVIDER_ENV = "TASKOS_ISSUE_PROVIDER"
FAKE_PATH_ENV = "TASKOS_ISSUE_FAKE_PATH"


def _github(config: AppConfig) -> IssueProvider:
    from src.issues.github import GitHubProvider

    return GitHubProvider(config.issues.owner, config.issues.assignee)


# provider name → factory. A GitLab entry ("gitlab": _gitlab) is the whole
# registration a later step needs; nothing else in the app keys on the name.
_PROVIDERS: dict[str, Callable[[AppConfig], IssueProvider]] = {
    "github": _github,
}


def get_provider(config: AppConfig) -> IssueProvider:
    """The provider for this process — env override first, then ``config.issues.provider``."""
    override = os.environ.get(PROVIDER_ENV, "").strip().lower()
    if override == "none":
        return NullProvider(f"issue provider disabled ({PROVIDER_ENV}=none)")
    if override == "fake":
        from src.issues.fake import FakeProvider

        path = os.environ.get(FAKE_PATH_ENV, "").strip()
        if not path:
            return NullProvider(f"{PROVIDER_ENV}=fake but {FAKE_PATH_ENV} is not set")
        return FakeProvider(path)
    name = (config.issues.provider or "").strip().lower()
    if not name or name == "none":
        return NullProvider("issues.provider is blank in config — no issue sync")
    factory = _PROVIDERS.get(name)
    if factory is None:
        known = ", ".join(sorted(_PROVIDERS))
        return NullProvider(f"issues.provider {name!r} is not supported (known: {known})")
    return factory(config)


__all__ = [
    "FAKE_PATH_ENV", "PROVIDER_ENV", "IssueInfo", "IssueProvider", "IssueProviderError", "NotConfigured",
    "NullProvider", "get_provider", "short_repo",
]
