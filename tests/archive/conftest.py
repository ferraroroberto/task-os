"""The batch-archiving tests' fixtures: a fresh database and the real app over it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.archive._support import (
    ARCHIVED_FILE,
    client_for,
)
from tests.fixtures.archiver_fake import (
    FOLDER_BILLS,
    FOLDER_HOUSE,
    apply_doc,
    apply_result,
    build_fake_archiver,
    candidate,
    mail,
    plan_doc,
    revert_doc,
    revert_result,
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """One confident mail and one below the threshold, through the whole app."""
    repo = build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([
            mail("api-filed@example.invalid", candidates=[candidate(FOLDER_HOUSE, 0.9)]),
            mail("api-unsure@example.invalid", candidates=[candidate(FOLDER_BILLS, 0.1)]),
        ])],
        apply=[apply_doc([apply_result("api-filed@example.invalid", FOLDER_HOUSE,
                                       files=[ARCHIVED_FILE])])],
        revert=[revert_doc([revert_result("api-filed@example.invalid", deleted=[ARCHIVED_FILE])])],
    )
    with client_for(tmp_path, monkeypatch, repo) as c:
        yield c
