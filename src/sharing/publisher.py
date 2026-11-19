"""Publish this host's address to the shared-folder file a launcher reads.

One address and a newline, written only when it differs from what the file
holds, so an unchanged address leaves the file's modification time alone. The
share can be slow or gone, so the work runs in a daemon thread and a caller never
waits on it past the bound it names; a failure is an outcome to show, never an
exception that reaches startup.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src import clock
from src.config import AppConfig
from src.features import PUBLISH_ADDRESS
from src.runtime import files as runtime_files
from src.sharing.address import Discovery, discover

logger = logging.getLogger(__name__)

PUBLISHED, UNCHANGED, UNAVAILABLE, FAILED, OFF, PENDING = (
    "published", "unchanged", "unavailable", "failed", "off", "pending",
)


@dataclass(frozen=True)
class Outcome:
    """What the last publish attempt did, in words a Settings row can show."""

    state: str
    reason: str = ""
    address: str = ""
    at: str = ""

    @property
    def detail(self) -> str:
        if self.state in (PUBLISHED, UNCHANGED):
            return f"{self.state.capitalize()}: {self.address}"
        if self.state == PENDING:
            return "Publishing…"
        return f"{self.state.capitalize()}: {self.reason}"

    @property
    def attention(self) -> bool:
        return self.state in (UNAVAILABLE, FAILED)


def path_problem(path_text: str) -> str | None:
    """Why ``path_text`` cannot be published to (no I/O), else ``None``."""
    if not path_text.strip():
        return "network_sharing.host_ip_file is blank — no file to publish to"
    target = Path(path_text)
    if not target.is_absolute():
        return "network_sharing.host_ip_file is not an absolute path"
    if target.name == "":
        return "network_sharing.host_ip_file names a folder, not a file"
    return None


def _outcome(state: str, reason: str = "", address: str = "") -> Outcome:
    return Outcome(state, reason, address, clock.now_iso())


def _why(exc: Exception) -> str:
    """The failure in words, never the exception's text: an ``OSError`` carries the full path."""
    return (getattr(exc, "strerror", None) or type(exc).__name__).strip()


def publish(path_text: str, *, discover_address: Callable[[str], Discovery] = discover) -> Outcome:
    """Write the discovered address into ``path_text`` when it differs. Never raises."""
    problem = path_problem(path_text)
    if problem:
        return _outcome(UNAVAILABLE, problem)
    try:
        found = discover_address(path_text)
    except Exception as exc:  # the OS can fail in ways no list covers; the outcome carries it
        return _outcome(UNAVAILABLE, f"the address could not be worked out ({type(exc).__name__})")
    if found.address is None:
        return _outcome(UNAVAILABLE, found.reason)
    target = Path(path_text)
    try:
        current = target.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        current = None
    except (OSError, ValueError) as exc:
        return _outcome(FAILED, f"the file could not be read ({_why(exc)})", found.address)
    if current == found.address:
        return _outcome(UNCHANGED, address=found.address)
    try:
        runtime_files.save_text(target, found.address + "\n", newline="\n")
    except (OSError, ValueError) as exc:
        return _outcome(FAILED, f"the file could not be written ({_why(exc)})", found.address)
    return _outcome(PUBLISHED, address=found.address)


class AddressPublisher:
    """The app's one publisher: runs :func:`publish` off the caller's thread, keeps the last outcome."""

    def __init__(
        self, get_config: Callable[[], AppConfig], *,
        discover_address: Callable[[str], Discovery] = discover,
    ) -> None:
        self._get_config = get_config
        self._discover = discover_address
        self._lock = threading.Lock()
        self._outcome: Outcome | None = None
        self._thread: threading.Thread | None = None

    @property
    def outcome(self) -> Outcome | None:
        return self._outcome

    def row_fields(self) -> dict[str, object]:
        """The Settings row's reading of the last outcome: ``detail`` words, ``attention``
        and ``pending``. An on switch with no run yet says so, never "on" alone."""
        outcome = self._outcome
        if outcome is None:
            return {"detail": "Not run yet", "attention": False, "pending": False}
        return {"detail": outcome.detail, "attention": outcome.attention, "pending": outcome.state == PENDING}

    def run(self, *, wait: float = 0.0) -> Outcome:
        """Publish once, unless the switch is off or a run is already in flight.

        The attempt runs in a daemon thread; ``wait`` is how long to give it before
        returning whatever is known, so a slow share costs the caller at most that."""
        config = self._get_config()
        if PUBLISH_ADDRESS not in config.features_on:
            self._outcome = _outcome(OFF)
            return self._outcome
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._outcome or _outcome(PENDING)
            self._outcome = _outcome(PENDING)
            thread = threading.Thread(
                target=self._work, args=(config.network_sharing.host_ip_file,),
                name="publish-address", daemon=True,
            )
            self._thread = thread
            thread.start()
        if wait > 0:
            thread.join(wait)
        return self._outcome or _outcome(PENDING)

    def _work(self, path_text: str) -> None:
        outcome = publish(path_text, discover_address=self._discover)
        self._outcome = outcome
        if outcome.state == FAILED:
            logger.warning("⚠️ address publish: %s", outcome.reason)
        elif outcome.state == UNAVAILABLE:
            logger.warning("⚠️ address publish: unavailable — %s", outcome.reason)
        else:
            logger.info("✅ address publish: %s (%s)", outcome.state, outcome.address)
