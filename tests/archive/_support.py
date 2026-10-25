"""What the batch-archiving tests share: the fake-checkout service, the canned
mail documents and the file paths they name.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import archive_store, email_capture, placeholders
from src import db as dbmod
from src import tasks_repo as repo
from src.ai import AIClient
from src.archive_batch import ArchiveBatchService
from src.config import AIConfig, AppConfig, ArchiveConfig
from tests.conftest import write_test_config
from tests.fixtures.archiver_fake import (
    FOLDER_BILLS,
    FOLDER_HOUSE,
    apply_doc,
    apply_result,
    build_fake_archiver,
    candidate,
    mail,
    plan_doc,
)

ARCHIVED_FILE = "E:\\archive\\house\\heating\\0042 - boiler service.msg"
OLDER_FILE = "E:\\archive\\house\\heating\\0011 - an older thread.msg"
#: Where those two files live, in the form the folder of an archived file is read
#: back as — the separators the archiver reports are normalised, nothing else.
OLDER_FOLDER = "E:/archive/house/heating"


def service_for(
    repo: Path, *, ai: object | None = None, **archive_kwargs: object
) -> ArchiveBatchService:
    """A service wired to the fake checkout, spawned with this interpreter.

    ``ai`` defaults to a **real** ``AIClient`` over a config with AI switched
    off: no test process may reach the machine's live hub, and the honest
    stand-in for "the model did not answer" is the client's own classified
    ``ai_disabled``, not a mock. The #158 tests pass :class:`FakeHub` instead.
    """
    defaults: dict[str, object] = {
        "enabled": True, "repo": str(repo), "python": sys.executable, "timeout_seconds": 60.0,
    }
    config = AppConfig(
        ai=AIConfig(enabled=False),
        archive=ArchiveConfig(**{**defaults, **archive_kwargs}),  # type: ignore[arg-type]
        placeholders={"archive": "E:/archive"},
    )
    return ArchiveBatchService(config, ai_client=ai if ai is not None else AIClient(config))


# --------------------------------------------------------------------- run


def _three_mail_plan() -> dict:
    return plan_doc([
        mail("confident@example.invalid", subject="Boiler service",
             candidates=[candidate(FOLDER_HOUSE, 0.91, date_prefix=True),
                         candidate(FOLDER_BILLS, 0.40)]),
        mail("unsure@example.invalid", subject="Something ambiguous",
             candidates=[candidate(FOLDER_BILLS, 0.32)]),
        mail("filed@example.invalid", subject="Already on disk",
             already_archived=OLDER_FILE),
    ])


#: What the archiver answers for the third mail of ``_three_mail_plan``: its file
#: is already on disk, so nothing is written, the existing file comes back with
#: ``reused`` and no sequence number is allocated (email-archiver#59).
def _reused_result() -> dict:
    return apply_result(
        "filed@example.invalid", OLDER_FOLDER, files=[OLDER_FILE], sequence="",
        reused=True, move_via="refetched",
    )


def _two_candidate_mail(message_id: str, subject: str = "Boiler service") -> dict:
    """One mail the archiver ranks house-first and bills-second."""
    return mail(message_id, subject=subject, candidates=[
        candidate(FOLDER_HOUSE, 0.9), candidate(FOLDER_BILLS, 0.4, date_prefix=True),
    ])


# --------------------------------------------- revert · move · accept · retry


def _one_archived_item(conn: sqlite3.Connection, svc: ArchiveBatchService) -> dict:
    return archive_store.list_items(conn, svc.run_now()["id"])[0]


def _stuck_then_finished(tmp_path: Path, *, second: dict) -> Path:
    """A fake whose ``apply`` refuses the move once and then answers ``second``."""
    return build_fake_archiver(
        tmp_path / "archiver",
        plan=[plan_doc([mail("stuck@example.invalid", subject="Roof survey",
                             candidates=[candidate(FOLDER_HOUSE, 0.9, date_prefix=True)])])],
        apply=[
            apply_doc([apply_result(
                "stuck@example.invalid", FOLDER_HOUSE, ok=False, files=[ARCHIVED_FILE],
                sequence="0042",
                error={"code": "move_failed",
                       "message": "the operation cannot be performed because the message has "
                                  "been changed"},
            )]),
            apply_doc([second]),
        ],
    )


# ------------------------------------------------------------- renumbering


#: What the archiver renames :data:`ARCHIVED_FILE` to when it closes a gap in
#: front of it, and the attachment that travels with it — a bundle is a number
#: and every file carrying it, so both move together or neither does.
RENUMBERED_FILE = "E:\\archive\\house\\heating\\0002 - boiler service.msg"
ATTACHMENT_FILE = "E:\\archive\\house\\heating\\0042 - report.pdf"
RENUMBERED_ATTACHMENT = "E:\\archive\\house\\heating\\0002 - report.pdf"
OLDER_RENUMBERED = "E:\\archive\\house\\heating\\0001 - an older thread.msg"


def _capture_the_email(conn: sqlite3.Connection, path: str) -> dict:
    """The task a flagged mail at ``path`` leaves behind — the link and the key.

    Built through the same two calls :mod:`src.email_capture` makes, so the
    heal is tested against what capture actually stores rather than against a
    hand-written row.
    """
    ref = placeholders.to_ref(placeholders.normalize_path(path), {"archive": "E:/archive"})
    task, outcome = repo.capture_task(
        conn, external_id=email_capture.external_id_for(ref), title="Boiler service",
        actor=email_capture.CAPTURE_ACTOR,
    )
    assert outcome == "created"
    repo.add_link(conn, task["id"], ref, label=ref.rsplit("/", 1)[-1], kind="email")
    return task


# --------------------------------------------------------------------- API


@contextmanager
def client_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path | None
) -> Iterator[TestClient]:
    """An app wired to ``repo`` — the fake checkout, never the real archiver.

    ``repo=None`` boots the install a fresh clone gets: the block off, and every
    route saying so.
    """
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    block = None if repo is None else {
        "enabled": True, "repo": str(repo), "python": sys.executable, "timeout_seconds": 60,
    }
    monkeypatch.setenv("TASKOS_CONFIG_PATH", str(write_test_config(
        tmp_path / "config.json", archive=block,
    )))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def _finished_run(client: TestClient, **body: object) -> dict:
    started = client.post("/api/archive/run", json=body)
    assert started.status_code == 202 and started.json()["status"] == "running"
    client.app.state.archive.stop(timeout=30)
    detail = client.get(f"/api/archive/runs/{started.json()['id']}")
    assert detail.status_code == 200
    return detail.json()
