"""The ``network_sharing`` config block, parsed.

Kept beside the publisher rather than in ``src/config.py`` (which imports it), so
the block has no dependency on the config loader and the loader stays small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NetworkSharingConfig:
    """How this install lets another computer find it.

    ``host_ip_file``  a text file in a shared folder that a launcher on another
                      computer reads the host's address from. The path is
                      machine-local, so it lives in the gitignored real config
                      only and is kept out of this dataclass's ``repr``. Blank =
                      nothing to publish to (Settings says so).
    """

    host_ip_file: str = field(default="", repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> NetworkSharingConfig:
        """The block from its raw config value; anything but an object is the defaults."""
        if not isinstance(raw, dict):
            return cls()
        return cls(host_ip_file=str(raw.get("host_ip_file", "") or "").strip())
