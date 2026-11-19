"""Available features — the coarse blocks of the app a machine can switch off.

A block is one coherent part of the app that sits on one source or primitive (an
integration, a data source, a background poller, a whole tab), never a single
button. Every block is **on by default**; the machine-local choice is the
``features`` block of ``config/config.json`` (gitignored), ``{"<key>": false}``
for each block that is off. One block is the exception: it writes outside this
install (a shared folder), so it is **off by default** and a machine opts in with
``{"<key>": true}``. The code is identical on every machine — only that
config and Settings → Available features differ.

Off means three things at once, all from this one table: the block's UI is
hidden (``data-feature`` + the page's ``data-features-off``), its background work
is stopped (:mod:`app.webapp.features`) and its backend routes answer
:class:`FeatureOff` instead of calling out. A block whose dependency is missing on
this machine is a different state — *unavailable*, with the reason — and is not
decided here: the router reads it from each service's own status.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: The opt-in block that publishes this PC's address to a shared-folder file.
PUBLISH_ADDRESS = "publish_address"

#: The reason every surface of a switched-off block gives.
OFF_REASON = "switched off in Settings → Available features"


class FeatureOff(Exception):
    """A route of a block this machine switched off was called. The app-level
    handler in ``server.py`` answers it as the one JSON envelope, 409 ``feature_off``."""

    code = "feature_off"
    http_status = 409


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    #: One line on what the block covers, shown under its row's title.
    summary: str
    #: ``False`` for a block that only an explicit ``true`` switches on.
    default_on: bool = True


FEATURES: tuple[Feature, ...] = (
    Feature(
        "time", "Time tracker",
        "The Time tab: timers, the day's log, totals and history.",
    ),
    Feature(
        "calendar", "Calendar lane",
        "The calendar beside Today, read from a private ICS address.",
    ),
    Feature(
        "issues", "Issue sync",
        "Open forge issues as tasks: the sync, the drawer panel, issue search.",
    ),
    Feature(
        "email", "Email and folders",
        "Folder-explorer: folder and email search, mail capture, Inbox archiving.",
    ),
    Feature(
        "ai", "Local AI",
        "The local model hub: voice quick-add, enrichment, AI Inbox triage.",
    ),
    Feature(
        "mirror", "Mirror and backups",
        "The markdown mirror folder with its watcher, and the daily database copies.",
    ),
    Feature(
        PUBLISH_ADDRESS, "Publish host address",
        "At startup, writes this PC's address to the file named in network_sharing.host_ip_file.",
        default_on=False,
    ),
)

KEYS: tuple[str, ...] = tuple(f.key for f in FEATURES)

#: The search kinds each block owns (``src.search.base.KINDS``).
SEARCH_KINDS: dict[str, str] = {"folders": "email", "emails": "email", "issues": "issues"}


def feature(key: str) -> Feature | None:
    """The block named ``key``, or ``None`` for a key that is not one."""
    return next((f for f in FEATURES if f.key == key), None)


def _default_on(key: str) -> bool:
    f = feature(key)
    return f is not None and f.default_on


def off_keys(raw: object) -> frozenset[str]:
    """The default-on block keys the ``features`` config value switches off.

    Only an explicit ``false`` switches a block off; anything else — a missing key,
    ``true``, a stray value — leaves it on, and a key that names no block (or an opt-in
    block, see :func:`on_keys`) is ignored, so a hand edit can never take away more
    than it names.
    """
    if not isinstance(raw, dict):
        return frozenset()
    return frozenset(k for k in KEYS if _default_on(k) and raw.get(k) is False)


def on_keys(raw: object) -> frozenset[str]:
    """The opt-in block keys the ``features`` config value switches on.

    Only an explicit ``true`` does; a missing, malformed or stray value stays off.
    """
    if not isinstance(raw, dict):
        return frozenset()
    return frozenset(k for k in KEYS if not _default_on(k) and raw.get(k) is True)


def features_block(off: Iterable[str], on: Iterable[str] = ()) -> dict[str, bool]:
    """The ``features`` config value: ``false`` for each default-on block in ``off``,
    ``true`` for each opt-in block in ``on`` — only the choices that differ from the default."""
    off_set, on_set = set(off), set(on)
    return {
        k: not _default_on(k)
        for k in KEYS
        if (_default_on(k) and k in off_set) or (not _default_on(k) and k in on_set)
    }


def search_kind_off_reason(off: Iterable[str], kind: str) -> str | None:
    """Why the search ``kind`` is off (its block is switched off), else ``None``."""
    return OFF_REASON if SEARCH_KINDS.get(kind) in set(off) else None
