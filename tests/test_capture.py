"""Email capture — flagged emails listed by folder-explorer become Inbox tasks.

Everything here runs against a fake folder-explorer (``tests/fixtures/folder_explorer_fake.py``)
serving the synthetic ``tests/fixtures/emails_fixture`` mails through ``mail/flagged``,
never a real mailbox or index (``tests/conftest.write_test_config`` blanks
``search.folder_explorer_url`` for the whole suite). task-os opens no database of
folder-explorer's, so the thing worth proving is what a *failed* read looks like:
never zero flagged mail, always the state it is in.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from src import email_capture
from src import tasks_repo as repo
from src.config import AppConfig, CaptureConfig, SearchConfig
from src.email_capture import EmailCaptureService, FlaggedEmailIndex, capture_once
from src.search.folder_explorer import FolderExplorerClient
from tests.fixtures.emails_fixture import FLAGGED, build_emails_db
from tests.fixtures.flagged_mail import flagged_mails
from tests.fixtures.folder_explorer_fake import FakeFolderExplorer


@pytest.fixture
def od(tmp_path: Path) -> Path:
    return tmp_path / "od"


@pytest.fixture
def placeholders(od: Path) -> dict[str, str]:
    return {"onedrive": str(od).replace("\\", "/")}


@pytest.fixture
def fake(tmp_path: Path, od: Path) -> Iterator[FakeFolderExplorer]:
    """A folder-explorer whose ``mail/flagged`` lists the fixture's two flagged mails."""
    built = build_emails_db(tmp_path / "emails.db", root=od)
    server = FakeFolderExplorer(flagged=flagged_mails(built["path"]))
    yield server
    server.stop()


def _index(fake: FakeFolderExplorer, placeholders: dict[str, str], timeout_s: float = 5.0) -> FlaggedEmailIndex:
    return FlaggedEmailIndex(FolderExplorerClient(fake.url, timeout_s=timeout_s), placeholders)


def _config(url: str, minutes: int = 10, placeholders: dict[str, str] | None = None) -> AppConfig:
    return AppConfig(
        search=SearchConfig(folder_explorer_url=url),
        capture=CaptureConfig(email_poll_minutes=minutes),
        placeholders=dict(placeholders or {}),
    )


def _service(fake: FakeFolderExplorer, placeholders: dict[str, str], timeout_s: float = 5.0) -> EmailCaptureService:
    return EmailCaptureService(_config(fake.url, placeholders=placeholders),
                               _index(fake, placeholders, timeout_s), initial_delay=999)


# ------------------------------------------------------------------- state


def test_no_folder_explorer_address_is_not_configured_with_that_reason(placeholders: dict[str, str]) -> None:
    index = FlaggedEmailIndex(FolderExplorerClient(""), placeholders)
    assert index.is_configured() == (False, "search.folder_explorer_url not configured")


def test_an_address_is_enough_to_be_enabled_no_request_at_startup(
    fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """Whether folder-explorer answers is each pass's finding; a startup probe would hold the app's boot."""
    service = _service(fake, placeholders)
    assert service.enabled is True
    assert fake.requests == []
    assert service.status()["source"]["state"] == "unknown"


def _outage(name: str, fake: FakeFolderExplorer) -> tuple[str, float]:
    """Put the fake in the named failure; returns the state the pass must report and the client timeout."""
    if name == "unreachable":
        fake.stop()
    elif name == "slow":
        fake.delay = 1.5
        return "slow", 0.3
    elif name in ("indexing", "not-configured"):
        fake.set_state("flagged", name, f"the email index is {name}")
    elif name == "failed":
        fake.set_state("flagged", "error", "cannot read the index")
    elif name == "no-envelope":
        fake.mode = "bare422"
        return "failed", 5.0
    return name, 5.0


@pytest.mark.parametrize("name", ["unreachable", "slow", "indexing", "not-configured", "failed", "no-envelope"])
def test_an_outage_is_its_own_state_and_never_zero_flagged_mail(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str], name: str
) -> None:
    """Acceptance: folder-explorer being down is *unavailable*, never "no flagged mail".

    A pass that cannot list creates nothing, keeps the last good result (a "0 flagged"
    that would be a lie never appears) and reports the state it met, so the fix can differ.
    """
    service = _service(fake, placeholders)
    first = service.run_now(conn)
    assert first is not None and first.created == 2          # a good pass first
    good = service.status()["last_result"]
    state, timeout_s = _outage(name, fake)
    service.index = _index(fake, placeholders, timeout_s)

    assert service.run_now(conn) is None

    st = service.status()
    assert st["source"]["state"] == state
    assert st["source"]["failures"] == 1 and st["source"]["since"] and st["source"]["last_ok"]
    assert st["last_error"].startswith(f"{state} since ")
    assert st["last_result"] == good and st["last_result"]["listed"] == 2
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2


def test_a_first_pass_that_cannot_list_creates_nothing_and_reports_the_state(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    fake.set_state("flagged", "not-configured", "the email index has no flag_status column")
    service = _service(fake, placeholders)

    assert service.run_now(conn) is None

    st = service.status()
    assert st["last_result"] is None and st["last_run"] is None
    assert st["source"]["state"] == "not-configured"
    assert "flag_status" in st["source"]["reason"] and "flag_status" in st["last_error"]
    assert repo.list_tasks(conn, status=["inbox"]) == []


def test_recovery_clears_the_error_and_the_failure_count(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    fake.set_state("flagged", "indexing", "the first build is running")
    service = _service(fake, placeholders)
    assert service.run_now(conn) is None and service.run_now(conn) is None
    assert service.status()["source"]["failures"] == 2

    fake.set_state("flagged", "ok")
    result = service.run_now(conn)

    st = service.status()
    assert result is not None and result.created == 2
    assert st["last_error"] is None
    assert st["source"]["state"] == "ok" and st["source"]["failures"] == 0 and st["source"]["reason"] is None


def test_a_pass_only_ever_reads_the_flagged_route(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    capture_once(conn, _index(fake, placeholders))
    assert fake.requests == ["/api/v1/mail/flagged?limit=200&offset=0"]


def test_the_listing_pages_by_offset_until_the_total(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(email_capture, "PAGE_SIZE", 1)
    result = capture_once(conn, _index(fake, placeholders))

    assert result.listed == result.created == 2
    assert fake.requests == ["/api/v1/mail/flagged?limit=1&offset=0", "/api/v1/mail/flagged?limit=1&offset=1"]


def test_the_listing_stops_paging_once_the_limit_is_met(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(email_capture, "PAGE_SIZE", 1)
    result = capture_once(conn, _index(fake, placeholders), limit=1)

    assert result.created == 1
    assert fake.requests == ["/api/v1/mail/flagged?limit=1&offset=0"]


# ------------------------------------------------------------------- a pass


def test_one_pass_lands_exactly_the_flagged_emails(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    result = capture_once(conn, _index(fake, placeholders))

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
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """Acceptance: the ``.msg`` is openable through the existing chip — so the
    link is the folded ref attach-from-search already stores."""
    capture_once(conn, _index(fake, placeholders))
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


def test_the_description_names_the_sender_the_date_and_the_preview(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    capture_once(conn, _index(fake, placeholders))
    task = next(t for t in repo.list_tasks(conn, status=["inbox"])
                if t["title"].startswith("Kitchen quotes"))
    body = repo.get_task(conn, task["id"])["description"]

    assert body.startswith("From email: Sam Rivera <sam@example.com> · 2026-08-10\n\nHi — attached")
    assert "three kitchen quotes" in body


# --------------------------------------------------------------- idempotency


def test_a_re_run_creates_nothing(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    index = _index(fake, placeholders)
    first = capture_once(conn, index)
    second = capture_once(conn, index)

    assert first.created == 2
    assert second.created == 0 and second.unchanged == 2 and second.listed == 2
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2
    # and no second link piled onto the same task
    for t in repo.list_tasks(conn, status=["inbox"]):
        assert len(repo.list_links(conn, t["id"])) == 1


def test_capture_is_one_way_a_later_pass_never_undoes_your_edits(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """"A task, once real, is yours" — moving it on, retitling it, or clearing
    the flag in Outlook must all survive the next pass untouched."""
    index = _index(fake, placeholders)
    capture_once(conn, index)
    task = next(t for t in repo.list_tasks(conn, status=["inbox"])
                if t["title"].startswith("Kitchen quotes"))
    repo.update_task(conn, task["id"], actor="me", status="standby", title="Chase the worktop quote")

    capture_once(conn, index)

    after = repo.get_task(conn, task["id"])
    assert after["status"] == "standby"
    assert after["title"] == "Chase the worktop quote"


def test_clearing_the_flag_leaves_the_task_alone(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    index = _index(fake, placeholders)
    capture_once(conn, index)
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2

    fake.flagged = []        # a real "nothing is flagged" answer: state ok, total 0

    result = capture_once(conn, index)
    assert result.listed == 0 and result.created == 0
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2      # both still there


def test_the_external_id_is_the_folded_ref_not_the_rowid(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """A rebuilt index reassigns the mail ids; keying on one would re-capture
    everything. The ref survives a rebuild, so a rebuild must be a no-op."""
    index = _index(fake, placeholders)
    capture_once(conn, index)
    ids = {t["id"] for t in repo.list_tasks(conn, status=["inbox"])}

    task = repo.get_task(conn, min(ids))
    assert task["external_id"].startswith(email_capture.EXTERNAL_ID_PREFIX + "{onedrive}/")

    # rebuild the index from scratch — same emails, brand-new ids
    for mail in fake.flagged:
        mail["id"] += 1000
    result = capture_once(conn, index)
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


def test_a_deleted_capture_stays_gone_while_the_email_stays_flagged(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """Deleting a captured task is a dismissal, not a reset. The archived
    ``.msg`` keeps its flag, so before the capture key outlived the row the very
    next pass landed the same mail again under a new id. Both delete paths."""
    index = _index(fake, placeholders)
    first = capture_once(conn, index)
    assert first.created == 2
    one, two = first.created_ids
    repo.delete_task(conn, one)
    repo.bulk_delete(conn, [two])

    again = capture_once(conn, index)

    assert again.listed == 2 and again.created == 0
    assert again.dismissed == 2 and again.unchanged == 0
    assert repo.list_tasks(conn, status=["inbox"]) == []
    assert "2 dismissed" in again.summary()


def test_capture_task_tells_a_live_capture_from_a_dismissed_one(conn: sqlite3.Connection) -> None:
    task, outcome = repo.capture_task(conn, external_id="wa:1", title="Kept", actor="t")
    assert outcome == "created"
    kept, outcome = repo.capture_task(conn, external_id="wa:1", title="Kept", actor="t")
    assert outcome == "unchanged" and kept["id"] == task["id"]

    repo.delete_task(conn, task["id"])
    gone, outcome = repo.capture_task(conn, external_id="wa:1", title="Kept", actor="t")
    assert (gone, outcome) == (None, "dismissed")
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0

    # a key never offered before still lands
    _, outcome = repo.capture_task(conn, external_id="wa:2", title="New", actor="t")
    assert outcome == "created"


def test_a_renamed_ref_keeps_a_dismissed_capture_dismissed(conn: sqlite3.Connection) -> None:
    """The archiver renumbers a folder after the task was already deleted: the
    key must follow the new name even though no task carries it any more."""
    old_ref, new_ref = "{onedrive}/mail/0042 - quote.msg", "{onedrive}/mail/0002 - quote.msg"
    task, _ = repo.capture_task(
        conn, external_id=email_capture.external_id_for(old_ref), title="Quote", actor="t"
    )
    repo.delete_task(conn, task["id"])

    moved = email_capture.rename_ref(conn, old_ref, new_ref)

    assert moved == {"links": 0, "tasks": 0}
    _, outcome = repo.capture_task(
        conn, external_id=email_capture.external_id_for(new_ref), title="Quote", actor="t"
    )
    assert outcome == "dismissed"


def test_capture_task_refuses_a_blank_external_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(repo.ValidationError):
        repo.capture_task(conn, external_id="  ", title="No key", actor="t")


def test_one_unusable_row_becomes_an_error_and_the_pass_carries_on(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """A row whose ``.msg`` path is empty makes a usable title but an unusable
    link. The failure must stay inside that one email — before the try covered
    the link too, it escaped ``capture_once`` and killed the whole pass, so the
    *other* flagged email (sorted later by date) was never captured at all."""
    for mail in fake.flagged:
        if mail["filename"] == "2026-08-10 Kitchen quotes.msg":
            mail["path"] = ""

    result = capture_once(conn, _index(fake, placeholders))

    assert result.listed == 2
    assert len(result.errors) == 1 and "link url is required" in result.errors[0]
    # the later email still landed, with its link
    school = next(t for t in repo.list_tasks(conn, status=["inbox"])
                  if t["title"].startswith("School"))
    assert result.created_ids == [school["id"]]
    assert len(repo.list_links(conn, school["id"])) == 1


def test_the_batch_limit_caps_one_pass_and_the_rest_arrive_next_time(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    """A first run against a large archive must not flood Inbox in one go."""
    index = _index(fake, placeholders)
    first = capture_once(conn, index, limit=1)
    assert first.listed == 1 and first.created == 1

    second = capture_once(conn, index, limit=10)
    assert second.created == 1 and second.unchanged == 1
    assert len(repo.list_tasks(conn, status=["inbox"])) == 2


def test_a_backlog_larger_than_the_limit_drains_across_passes(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The oldest ``limit`` flagged mails used to be re-read every pass.

    The flag on an archived ``.msg`` never clears, so once the oldest ``limit``
    were captured they came back as "unchanged" forever and the mail after them
    was never reached. Already-captured and dismissed keys must not use up the
    limit — across pages too, so the page size is pinned below the backlog.
    """
    monkeypatch.setattr(email_capture, "PAGE_SIZE", 2)
    older = [  # three more flagged mails, all older than the fixture's two
        {"id": 100 + n, "path": f"{placeholders['onedrive']}/backlog/m{n}.msg", "filename": f"m{n}.msg",
         "folder": f"{placeholders['onedrive']}/backlog", "subject": f"Backlog {n}", "sender": "a@example.invalid",
         "from_name": "", "from_addr": "a@example.invalid", "date": f"2026-01-0{n}T09:00:00+02:00", "preview": ""}
        for n in range(1, 4)
    ]
    fake.flagged = older + fake.flagged
    index = _index(fake, placeholders)

    first = capture_once(conn, index, limit=2)
    assert first.created == 2 and first.listed == 2
    # One of the two is deleted: a dismissal must not hold its place in the window either.
    repo.delete_task(conn, first.created_ids[0])

    second = capture_once(conn, index, limit=2)
    assert second.created == 2
    assert (second.unchanged, second.dismissed) == (1, 1)
    assert second.listed == 4

    third = capture_once(conn, index, limit=2)
    assert third.created == 1
    assert (third.unchanged, third.dismissed) == (3, 1)

    assert len(repo.list_tasks(conn, status=["inbox"])) == 4  # five flagged, one dismissed

    # Nothing left: a fourth pass lands nothing and reports every key as known.
    fourth = capture_once(conn, index, limit=2)
    assert fourth.created == 0 and fourth.unchanged + fourth.dismissed == fourth.listed == 5


# ---------------------------------------------------------------- the service


def test_service_status_is_visible_when_off() -> None:
    service = EmailCaptureService(_config(""), initial_delay=999)
    st = service.status()
    assert st["enabled"] is False
    assert st["reason"] == "search.folder_explorer_url not configured"
    assert st["last_run"] is None and st["running"] is False
    assert st["source"] == {"url": None, "state": "unknown", "reason": None, "since": None,
                            "last_ok": None, "failures": 0}
    # every key the CLI and the Settings card read is present even when off
    assert set(st) == {"enabled", "reason", "source", "poll_minutes", "last_run",
                       "last_result", "last_error", "next_run", "running"}


def test_a_zero_poll_interval_is_off_with_that_as_the_reason(
    fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    service = EmailCaptureService(_config(fake.url, minutes=0, placeholders=placeholders), initial_delay=999)
    assert service.enabled is False
    assert "email_poll_minutes" in service.reason


def test_the_default_service_asks_with_the_capture_timeout() -> None:
    service = EmailCaptureService(_config("http://127.0.0.1:1"), initial_delay=999)
    assert service.index.client.timeout_s == email_capture.CAPTURE_TIMEOUT_S == 10.0


def test_run_now_records_the_pass_on_the_status(
    conn: sqlite3.Connection, fake: FakeFolderExplorer, placeholders: dict[str, str]
) -> None:
    service = _service(fake, placeholders)
    assert service.enabled is True

    result = service.run_now(conn)

    assert result is not None and result.created == 2
    st = service.status()
    assert st["enabled"] is True and st["last_error"] is None
    assert st["last_run"] and st["last_result"]["created"] == 2
    assert st["source"]["state"] == "ok" and st["source"]["last_ok"] and st["source"]["url"] == fake.url
    assert "2 flagged email(s)" in result.summary()


def test_run_now_on_a_disabled_service_is_a_no_op_not_a_crash(
    conn: sqlite3.Connection
) -> None:
    service = EmailCaptureService(_config(""), initial_delay=999)
    assert service.run_now(conn) is None
    assert repo.list_tasks(conn, status=["inbox"]) == []
