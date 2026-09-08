"""Email capture (#98) — flagged emails in the archiver's index become Inbox tasks.

Everything here runs against the synthetic ``tests/fixtures/emails_fixture``
index, never a real ``emails.db`` (``tests/conftest.write_test_config`` blanks
``search.email_db`` for the whole suite; these tests point it at the fixture
explicitly). The archiver's file is read-only from this repo, so the one thing
worth proving over and over is that a pass never writes to it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src import db as dbmod
from src import email_capture
from src import tasks_repo as repo
from src.config import AppConfig, CaptureConfig, SearchConfig
from src.email_capture import EmailCaptureService, FlaggedEmailIndex, capture_once
from tests.fixtures.emails_fixture import FLAGGED, build_emails_db


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    dbmod.init_db()
    c = dbmod.connect()
    yield c
    c.close()


@pytest.fixture
def od(tmp_path: Path) -> Path:
    return tmp_path / "od"


@pytest.fixture
def placeholders(od: Path) -> dict[str, str]:
    return {"onedrive": str(od).replace("\\", "/")}


def _index(tmp_path: Path, od: Path, placeholders: dict[str, str], **kw: Any) -> FlaggedEmailIndex:
    built = build_emails_db(tmp_path / "emails.db", root=od, **kw)
    return FlaggedEmailIndex(built["path"], placeholders)


# ------------------------------------------------------------------- state


def test_not_configured_names_the_reason_that_actually_applies(
    tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """Four distinct failures must not collapse into one message — the fix
    differs for each, so the reason has to say which one it is."""
    ok, reason = FlaggedEmailIndex("", placeholders).is_configured()
    assert ok is False and reason == "search.email_db not configured"

    missing = tmp_path / "nope.db"
    ok, reason = FlaggedEmailIndex(str(missing), placeholders).is_configured()
    assert ok is False and "not found" in reason

    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()
    ok, reason = FlaggedEmailIndex(str(empty), placeholders).is_configured()
    assert ok is False and "not an email-archiver index" in reason

    # The one that matters: a real index from an archiver too old to record flags.
    old = _index(tmp_path, od, placeholders, flags=False)
    ok, reason = old.is_configured()
    assert ok is False
    assert email_capture.FLAG_COLUMN in reason and "email-archiver" in reason

    assert _index(tmp_path, od, placeholders).is_configured() == (True, None)


def test_a_pass_never_writes_to_the_archivers_file(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """The archiver owns emails.db; capture opens it ``mode=ro``. Proven by the
    file's own bytes, not by trusting the URI."""
    index = _index(tmp_path, od, placeholders)
    before = Path(index.db_path).read_bytes()
    capture_once(conn, index)
    assert Path(index.db_path).read_bytes() == before

    # and the read-only connection genuinely refuses a write
    c = sqlite3.connect(email_capture.email_db_uri(index.db_path), uri=True)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("UPDATE emails SET flag_status = 0")
    c.close()


# ------------------------------------------------------------------- a pass


def test_one_pass_lands_exactly_the_flagged_emails(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    result = capture_once(conn, _index(tmp_path, od, placeholders))

    assert result.listed == len(FLAGGED) == 2
    assert result.created == 2 and result.unchanged == 0 and result.errors == []

    tasks = repo.list_tasks(conn, status=["inbox"])
    assert {t["title"] for t in tasks} == {
        "Kitchen quotes from the installer", "School enrolment forms — deadline Friday"
    }
    for t in tasks:
        assert t["status"] == "inbox"
        assert t["created_by"] == email_capture.CAPTURE_ACTOR


def test_the_task_carries_the_msg_ref_the_opener_chip_opens(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """Acceptance: the ``.msg`` is openable through the existing chip — so the
    link is the folded ref + ``taskos://`` URL attach-from-search already stores."""
    capture_once(conn, _index(tmp_path, od, placeholders))
    task = next(t for t in repo.list_tasks(conn, status=["inbox"])
                if t["title"].startswith("Kitchen quotes"))

    links = repo.list_links(conn, task["id"])
    assert len(links) == 1
    link = links[0]
    assert link["kind"] == "email"
    assert link["label"] == "2026-08-10 Kitchen quotes.msg"
    # The stored value is the **ref**, folded onto the placeholder so a second
    # PC resolves it to its own copy — and because the drawer's chip keys on a
    # leading `{` to build the opener href itself, a pre-built `taskos://` URL
    # here would render as an hrefless web chip (caught by story 21).
    assert link["url"] == "{onedrive}/mail/house/2026-08-10 Kitchen quotes.msg"


def test_the_description_names_the_sender_the_date_and_the_flag(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    capture_once(conn, _index(tmp_path, od, placeholders))
    task = next(t for t in repo.list_tasks(conn, status=["inbox"])
                if t["title"].startswith("Kitchen quotes"))
    body = repo.get_task(conn, task["id"])["description"]

    assert body.startswith("From email: Sam Rivera <sam@example.com> · 2026-08-10")
    assert "Flag: Follow up" in body
    assert "three kitchen quotes" in body


# --------------------------------------------------------------- idempotency


def test_a_re_run_creates_nothing(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    index = _index(tmp_path, od, placeholders)
    first = capture_once(conn, index)
    second = capture_once(conn, index)

    assert first.created == 2
    assert second.created == 0 and second.unchanged == 2 and second.listed == 2
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2
    # and no second link piled onto the same task
    for t in repo.list_tasks(conn, status=["inbox"]):
        assert len(repo.list_links(conn, t["id"])) == 1


def test_capture_is_one_way_a_later_pass_never_undoes_your_edits(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """"A task, once real, is yours" — moving it on, retitling it, or clearing
    the flag in Outlook must all survive the next pass untouched."""
    index = _index(tmp_path, od, placeholders)
    capture_once(conn, index)
    task = next(t for t in repo.list_tasks(conn, status=["inbox"])
                if t["title"].startswith("Kitchen quotes"))
    repo.update_task(conn, task["id"], actor="me", status="standby", title="Chase the worktop quote")

    capture_once(conn, index)

    after = repo.get_task(conn, task["id"])
    assert after["status"] == "standby"
    assert after["title"] == "Chase the worktop quote"


def test_clearing_the_flag_leaves_the_task_alone(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    index = _index(tmp_path, od, placeholders)
    capture_once(conn, index)
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2

    # un-flag every email the way the archiver's next scan would
    c = sqlite3.connect(index.db_path)
    c.execute("UPDATE emails SET flag_status = 0")
    c.commit()
    c.close()

    result = capture_once(conn, index)
    assert result.listed == 0 and result.created == 0
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2      # both still there


def test_the_external_id_is_the_folded_ref_not_the_rowid(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """A rebuilt index reassigns ``emails.id``; keying on it would re-capture
    everything. The ref survives a rebuild, so a rebuild must be a no-op."""
    index = _index(tmp_path, od, placeholders)
    capture_once(conn, index)
    ids = {t["id"] for t in repo.list_tasks(conn, status=["inbox"])}

    task = repo.get_task(conn, min(ids))
    assert task["external_id"].startswith(email_capture.EXTERNAL_ID_PREFIX + "{onedrive}/")

    # rebuild the index from scratch — same emails, brand-new rowids
    rebuilt = _index(tmp_path, od, placeholders)
    result = capture_once(conn, rebuilt)
    assert result.created == 0 and result.unchanged == 2
    assert {t["id"] for t in repo.list_tasks(conn, status=["inbox"])} == ids


def test_capture_task_is_idempotent_under_a_racing_second_pass(
    conn: sqlite3.Connection
) -> None:
    """The v3 partial unique index is the real guard; the loser reads the
    winner's row back rather than raising or double-creating."""
    first, outcome = repo.capture_task(conn, external_id="email:x", title="One", actor="t")
    assert outcome == "created"
    second, outcome = repo.capture_task(conn, external_id="email:x", title="Two", actor="t")
    assert outcome == "unchanged"
    assert second["id"] == first["id"] and second["title"] == "One"
    assert len(repo.list_tasks(conn, status=["inbox"])) == 1


def test_capture_task_refuses_a_blank_external_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(repo.ValidationError):
        repo.capture_task(conn, external_id="  ", title="No key", actor="t")


def test_one_unusable_row_becomes_an_error_and_the_pass_carries_on(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """A row whose ``.msg`` path is empty makes a usable title but an unusable
    link. The failure must stay inside that one email — before the try covered
    the link too, it escaped ``capture_once`` and killed the whole pass, so the
    *other* flagged email (sorted later by date) was never captured at all."""
    index = _index(tmp_path, od, placeholders)
    c = sqlite3.connect(index.db_path)
    c.execute("UPDATE emails SET file_path = '' WHERE filename = ?",
              ("2026-08-10 Kitchen quotes.msg",))
    c.commit()
    c.close()

    result = capture_once(conn, index)

    assert result.listed == 2
    assert len(result.errors) == 1 and "link url is required" in result.errors[0]
    # the later email still landed, with its link
    school = next(t for t in repo.list_tasks(conn, status=["inbox"])
                  if t["title"].startswith("School"))
    assert result.created_ids == [school["id"]]
    assert len(repo.list_links(conn, school["id"])) == 1


def test_the_batch_limit_caps_one_pass_and_the_rest_arrive_next_time(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    """A first run against a large archive must not flood Inbox in one go."""
    index = _index(tmp_path, od, placeholders)
    first = capture_once(conn, index, limit=1)
    assert first.listed == 1 and first.created == 1

    second = capture_once(conn, index, limit=10)
    assert second.created == 1 and second.unchanged == 1
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2


# ---------------------------------------------------------------- the service


def _config(email_db: str, minutes: int = 10, placeholders: dict[str, str] | None = None) -> AppConfig:
    return AppConfig(
        search=SearchConfig(email_db=email_db),
        capture=CaptureConfig(email_poll_minutes=minutes),
        placeholders=dict(placeholders or {}),
    )


def test_service_status_is_visible_when_off(tmp_path: Path, od: Path, placeholders: dict[str, str]) -> None:
    service = EmailCaptureService(_config(""), initial_delay=999)
    st = service.status()
    assert st["enabled"] is False
    assert st["reason"] == "search.email_db not configured"
    assert st["last_run"] is None and st["running"] is False
    # every key the CLI and the Settings card read is present even when off
    assert set(st) == {"enabled", "reason", "source", "poll_minutes", "last_run",
                       "last_result", "last_error", "next_run", "running"}


def test_a_zero_poll_interval_is_off_with_that_as_the_reason(
    tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    built = build_emails_db(tmp_path / "emails.db", root=od)
    service = EmailCaptureService(_config(built["path"], minutes=0, placeholders=placeholders),
                                  initial_delay=999)
    assert service.enabled is False
    assert "email_poll_minutes" in service.reason


def test_run_now_records_the_pass_on_the_status(
    conn: sqlite3.Connection, tmp_path: Path, od: Path, placeholders: dict[str, str]
) -> None:
    built = build_emails_db(tmp_path / "emails.db", root=od)
    service = EmailCaptureService(_config(built["path"], placeholders=placeholders), initial_delay=999)
    assert service.enabled is True

    result = service.run_now(conn)

    assert result is not None and result.created == 2
    st = service.status()
    assert st["enabled"] is True and st["last_error"] is None
    assert st["last_run"] and st["last_result"]["created"] == 2
    assert "2 flagged email(s)" in result.summary()


def test_run_now_on_a_disabled_service_is_a_no_op_not_a_crash(
    conn: sqlite3.Connection
) -> None:
    service = EmailCaptureService(_config(""), initial_delay=999)
    assert service.run_now(conn) is None
    assert repo.list_tasks(conn, status=["inbox"]) == []
