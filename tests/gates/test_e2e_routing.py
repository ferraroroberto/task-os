"""This repo's ``.fleet.toml [e2e]`` rules, held to the paths whose tier matters.

The classifier itself is vendored; what is ours is the rule table, where a file
the browser suite loads can fall through to a broad ``none`` rule and ship with
no browser run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import classify_e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        # loaded by the browser suite, from under a folder whose broad rule is "none"
        ("tests/host/_synthetic_host.py", "full"),
        ("config/config.sample.json", "full"),
        # the broad rules those two are carved out of still hold
        ("tests/test_dates.py", "skip"),
        ("config/sharepoint-mapping.sample.json", "skip"),
        # a generated search-tool ignore list no test opens
        (".ignore", "skip"),
    ],
)
def test_a_path_routes_to_its_tier(path: str, tier: str) -> None:
    assert (REPO_ROOT / path).is_file()
    config = classify_e2e.load_config(REPO_ROOT / ".fleet.toml")
    assert classify_e2e.classify([path], config).tier == tier
