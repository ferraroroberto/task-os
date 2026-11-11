"""Batch archiving of the Outlook Inbox through folder-explorer's archive verbs.

One gesture files the whole Inbox: every mail is written into the archive
folder the archiver ranks best, moved to Outlook's *Archive* folder and tagged,
and the run is recorded here so a human can review it and undo any single mail.
This module is the backend half — the schema (v14/v15), the service that drives
the archiver, and the state machine the API in ``app/webapp/routers/archive.py``
exposes. The screen builds on it.

**Which folder** is decided in two layers. The archiver's suggester ranks the
candidates; the local model then picks among them (``src/archive_rank.py``)
with a confidence and a one-line reason, and every human correction is
stored in ``archive_corrections`` and fed back into the next run's prompt. A hub
that is down, off or answering junk degrades that batch to the suggester's own
top candidate, with the reason on every mail in it and on the run — the run
still completes, because a mail nobody could rank is a filing decision, not a
broken feature.

**task-os never imports the archiver.** Everything crosses an HTTP boundary as
JSON: folder-explorer's v1 archive API (``POST /api/v1/archive/{plan,apply,
revert,index}`` at ``search.folder_explorer_url``, :mod:`src.archive_client`),
the one app that talks to Outlook and owns the email index, bounded by
``archive.timeout_seconds``. That is not fastidiousness — every verb drives
Outlook over COM, and a COM modal (the address-book prompt, a profile chooser)
blocks whatever thread it is raised on. folder-explorer runs each verb in a
child it kills on its own budget, so a hung Outlook is a typed ``timeout``
answer, never a wedged webapp on either side. The archiver keeps sole ownership
of Outlook, of the filenames and of its index; task-os only decides *which
folder*.

The answer's contract (folder-explorer's ``docs/service-api.md``, pinned there
by contract tests):

- ``acknowledged`` says the verb ran to its end; a mail is filed only when its
  own result is ``ok``. Individual mails may fail, each with its own
  ``error.code`` (``bad_decision`` · ``not_in_inbox`` · ``not_in_archive_folder`` ·
  ``archive_failed`` · ``move_failed`` · ``category_failed``).
- ``refused`` / ``not-found`` outcomes mean nothing was touched
  (``outlook_unavailable``, ``config_missing``, ``busy`` …).
- ``acknowledged: false`` (a timeout, a crash, an unreadable answer) means nobody
  can say what was written, so the call fails by name and the rows it covered
  are not left reading as filed.
- every envelope carries ``schema_version`` (1 today). A version this build
  does not understand is refused by name rather than read field by field.

Failures a caller has to be able to tell apart get distinct codes and messages:
folder-explorer is **not configured** here (409), **unreachable** (502),
**timed out** (504), **busy** with another archive call (409), Outlook
**unreachable** (502), and a run already in flight in *this* app (409). A last
one — the re-index afterwards, one ``index`` call per folder the run filed
into — is deliberately *not* fatal: the mails are filed either way, so the run
finishes ``done`` and carries the rescan's failure in its ``error`` column.
"Filed, but the index has not confirmed it" is its own state, never folded into
a clean run.

State machine, one ``archive_items`` row per mail:

    archived      filed on disk and moved in Outlook (or already filed, per the
                  archiver's index, and recorded with the existing file)
    needs_review  left in the Inbox: the best candidate scored below
                  ``archive.confidence_threshold``, or there was none. A human
                  resolves it from the report screen — ``accept`` to
                  leave it in the Inbox as seen, or ``move`` into any folder,
                  which files it for the first time (no undo leg)
    failed        the archiver refused or broke on this mail; ``error`` says
                  which of its codes. Revertible when files were still written
                  (``apply`` fills ``files`` *before* the move on purpose) — and
                  ``retry``-able for exactly that reason: the same
                  decision goes back to ``apply``, which reuses the file it has
                  already written and finishes the move Outlook refused. Also
                  every row handed to an ``apply`` that failed as a whole
                  (timeout, error document, unreadable output): nothing was
                  confirmed, so none may stay ``archived``
    reverted     the files are gone and the mail is back in the Inbox
    moved         re-filed into a folder a human picked

``archived`` and ``moved`` are the two "filed" states, and the partial unique
index on ``message_id`` covers exactly those — a mail cannot be filed twice,
whatever the archiver's index believes, and a reverted mail is free to be
archived again.

Both verbs that disturb a folder's numbering also ask the archiver to repair it
(``renumber``, ``archive.renumber``) — and the archiver
heals only its own index, so every path it renames is healed from the map it
returns — by :func:`~src.archive_renumber.apply_renumber_map`, which rewrites
``archive_items.files_json``, the email link's ref and the captured task's
``external_id``. Asking for the repair without healing would be strictly worse
than not asking.

Idempotency is the Internet Message-ID throughout (never an Outlook EntryID,
which the ``apply`` move itself rewrites). A second run over a mail this
database has already filed writes **nothing**: no row, no archive call for it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

from src import archive_rank
from src.ai.client import AIClient
from src.archive_actions import ArchiveError, ItemActions
from src.archive_client import ArchiveApiClient
from src.archive_rank import Pick, Ranking
from src.archive_renumber import (
    apply_renumber_map,
    last_component,
    path_key,
    rename_files,
    rename_index,
    renumbered_folders,
)
from src.archive_state import INTERRUPTED_ERROR, ItemStatus, RunStatus, annotate_run
from src.archive_store import (
    create_run,
    filed_message_ids,
    finish_run,
    get_item,
    insert_item,
    list_runs,
    open_run_ids,
    recent_corrections,
    sync_run_counts,
    update_item,
)
from src.config import AppConfig
from src.db import connect
from src.search.folder_explorer import FolderExplorerClient

logger = logging.getLogger(__name__)

#: Seconds a re-index waits for another email run (a nightly scan's email stage)
#: to release the email lock before it reports busy.
SCAN_WAIT_S = 60.0

#: Seconds the whole post-apply re-index phase may take, across every folder.
#: The mails are already filed by then and the run's lock is held until it
#: ends, so a slow or wedged index costs this one bounded wait, not a timeout
#: per folder. A call still in flight at the deadline is given up on (the
#: service finishes it by itself); whatever was not confirmed is reported on
#: the run.
SCAN_BUDGET_S = 300.0


@dataclass(frozen=True)
class Decision:
    """One mail's filing decision — what the run loop acts on and its row records.

    Every branch of :meth:`ArchiveBatchService._decide` states what happens to
    the mail and why; the rest defaults to *nothing chosen, nothing handed to
    the archiver's* ``apply`` — so a branch sets only what differs.
    """

    status: str                       # "archived" | "needs_review"
    reason: str
    apply: bool = False               # hand it to the archiver's ``apply``
    chosen_folder: str | None = None
    chosen_rank: int | None = None
    confidence: float | None = None
    date_prefix: bool = False
    files: tuple[str, ...] = ()


# -------------------------------------------------------------- folder paths


def _folder_of(path: str) -> str:
    """The folder an archived file sits in — either separator, whatever the host.

    ``os.path.dirname`` splits on ``\\`` only on Windows, and the archiver reports
    Windows paths wherever this runs, so the split is done by hand rather than by
    a function whose answer depends on the platform reading it.
    """
    head, _, _ = str(path).replace("\\", "/").rstrip("/").rpartition("/")
    return head


# ------------------------------------------------------------------- service


class ArchiveBatchService(ItemActions):
    """Drives folder-explorer's archive API and records what it did (``app.state.archive``).

    One run at a time, and one archive call at a time: ``revert`` and ``move``
    take the same lock a run does, because they all reach the same single-
    threaded Outlook COM apartment. A second caller gets 409 with that as the
    reason, never a queue that quietly reorders someone's Inbox.
    """

    def __init__(self, config: AppConfig, *, ai_client: Any | None = None) -> None:
        cfg = config.archive
        self.configured_enabled = bool(cfg.enabled)
        self.client = ArchiveApiClient(FolderExplorerClient(config.search.folder_explorer_url))
        self.candidates = max(1, int(cfg.candidates))
        self.threshold = float(cfg.confidence_threshold)
        self.timeout = float(cfg.timeout_seconds)
        self.batch_size = max(1, int(cfg.batch_size))
        self.examples = max(0, int(cfg.examples))
        self.renumber = bool(cfg.renumber)
        # A second hub client, bound to ``archive.model``: its own in-flight
        # lock, so an Inbox triage running at the same time does not make one
        # of the two wait, and its own model, because filing mail and triaging
        # tasks are different jobs.
        self.ai = ai_client if ai_client is not None else AIClient(
            config, model=cfg.model, timeout=cfg.ai_timeout_seconds,
        )
        self.model = getattr(self.ai, "model", "") or ""
        self.placeholders = dict(config.placeholders)
        self.enabled, self.reason = self._configured()
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        #: The run row the lock is held for; ``None`` while no worker drives one.
        self._active_run_id: int | None = None
        if not self.enabled:
            logger.warning("⚠️ archive: batch archiving off — %s", self.reason)

    # ----------------------------------------------------------- readiness
    def _configured(self) -> tuple[bool, str | None]:
        """``(True, None)``, or ``False`` + the one reason that actually applies.

        Two distinct failures, two distinct messages: "you turned it off" and
        "you never said where folder-explorer is". Whether it is *up* is not a
        configuration fact and is never guessed here — the first call says so.
        """
        if not self.configured_enabled:
            return False, "disabled in config (archive.enabled)"
        if not self.client.configured:
            return False, (
                "search.folder_explorer_url not configured — point it at folder-explorer, "
                "which does the archiving"
            )
        return True, None

    def status(self, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        """What ``/api/status``'s ``archive`` key, the Archive tab and the CLI render."""
        last_run: dict[str, Any] | None = None
        own = conn is None
        c = conn or connect()
        try:
            runs = list_runs(c, limit=1)
            last_run = self.annotate(runs[0]) if runs else None
        except sqlite3.Error as exc:  # a status must never be the thing that 500s
            logger.warning("⚠️ archive: could not read the last run — %s", exc)
        finally:
            if own:
                c.close()
        return {
            "configured": self.enabled,
            "reason": None if self.enabled else self.reason,
            "running": self.running,
            "url": self.client.host if self.client.configured else None,
            "candidates": self.candidates,
            "confidence_threshold": self.threshold,
            "timeout_seconds": self.timeout,
            "model": self.model or None,
            "batch_size": self.batch_size,
            "examples": self.examples,
            "last_run": last_run,
            "last_error": self.last_error,
        }

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def annotate(self, run: dict[str, Any]) -> dict[str, Any]:
        """A run row plus its derived ``state`` — the one way a run row leaves this service."""
        return annotate_run(run, worker_alive=self._active_run_id == run["id"])

    def close_interrupted_runs(self) -> list[int]:
        """Close the rows a previous process left ``running``; the ids it closed.

        Called once at the app's startup, never from the constructor: the CLI
        builds this service just to read a status while the app may be mid-run,
        and a sweep there would close a live run's row. Skipped while this
        service holds a worker. The close recomputes the counters from the items
        the run wrote, so the mails it had already decided still show.
        """
        if self.running:
            return []
        conn = connect()
        try:
            closed = open_run_ids(conn)
            for run_id in closed:
                finish_run(conn, run_id, status=RunStatus.FAILED, error=INTERRUPTED_ERROR)
        finally:
            conn.close()
        if closed:
            logger.warning(
                "⚠️ archive: closed %d run(s) the app stopped in the middle of — %s",
                len(closed), ", ".join(f"#{i}" for i in closed),
            )
        return closed

    def stop(self, timeout: float = 5.0) -> None:
        """Let an in-flight run finish (lifespan shutdown, and the tests' join)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if not thread.is_alive():
                self._thread = None

    # ------------------------------------------------------------ the service
    def _call(self, verb: str, body: dict[str, Any]) -> dict[str, Any]:
        """One archive verb -> the archiver's one document, or :class:`ArchiveError`.

        ``apply`` and ``revert`` are the two verbs that leave a folder's
        numbering ragged, so both are asked to repair it (``archive.renumber``)
        — and every path the repair renames is healed by the caller from the
        map the document returns. Asking for it without healing would be worse
        than not asking.
        """
        if verb in ("apply", "revert") and self.renumber:
            body = {**body, "renumber": True}
        return self.client.run(verb, body, timeout=self.timeout)

    def _rescan_index(self, folders: list[str]) -> str | None:
        """Re-index each folder this run filed into; the reasons any did not, or ``None``.

        One ``index`` call per folder: it lists only that folder and takes only
        the email lock, so it never waits behind a disk scan.
        """
        problems: list[str] = []
        deadline = time.monotonic() + SCAN_BUDGET_S
        for position, folder in enumerate(folders):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                skipped = [last_component(f) or f for f in folders[position:]]
                problems.append(
                    f"{len(skipped)} folder(s) not asked ({', '.join(skipped)}): "
                    f"the {SCAN_BUDGET_S:g} s re-index budget was spent"
                )
                break
            # The wait for the email lock is kept under the call's bound so a
            # busy lock arrives as the service's typed answer, not a client timeout.
            problem = self.client.index(folder, min(SCAN_WAIT_S, remaining / 2), timeout=remaining)
            if problem:
                problems.append(f"{last_component(folder) or folder}: {problem}")
        if problems:
            return "the email index has not confirmed what was filed — " + " · ".join(problems)
        logger.info("ℹ️ archive: folder-explorer re-indexed the %d folder(s) this run filed", len(folders))
        return None

    # ---------------------------------------------------------------- runs
    def _begin(self) -> dict[str, Any]:
        """Claim the archiver and open a run row, or refuse with the reason."""
        if not self.enabled:
            raise ArchiveError("archive_disabled", self.reason or "batch archiving is off", http_status=409)
        if not self._lock.acquire(blocking=False):
            raise ArchiveError(
                "archive_in_flight",
                "an archiving run is already in progress — one Outlook, one run at a time",
                http_status=409,
            )
        try:
            conn = connect()
            try:
                run = create_run(conn)
            finally:
                conn.close()
            self._active_run_id = int(run["id"])
            return self.annotate(run)
        except BaseException:
            self._lock.release()
            raise

    def start_run(self, *, limit: int | None = None) -> dict[str, Any]:
        """Open the run and drive it in a worker thread; returns the ``running`` row.

        The API answers 202 with this: a full-Inbox run walks every mail over
        COM and takes minutes, which is not a request to hold open.
        """
        run = self._begin()
        thread = threading.Thread(
            target=self._drive, args=(int(run["id"]), limit), name="task-os-archive", daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:  # pragma: no cover - the process is out of threads
            self._lock.release()
            raise
        self._thread = thread
        return run

    def run_now(self, *, limit: int | None = None) -> dict[str, Any]:
        """The same run, synchronously — the deterministic path for tests and the CLI."""
        return self._drive(int(self._begin()["id"]), limit)

    def _drive(self, run_id: int, limit: int | None) -> dict[str, Any]:
        """Plan → decide → apply → rescan, then close the run. Never raises."""
        conn = connect()
        try:
            try:
                run = self._execute(conn, run_id, limit)
            except ArchiveError as exc:
                self.last_error = f"{exc.code}: {exc}"
                logger.error("❌ archive: run %d failed — %s", run_id, exc)
                return finish_run(conn, run_id, status=RunStatus.FAILED, error=str(exc))
            except Exception as exc:  # noqa: BLE001 — a bad run is a recorded state, not a dead app
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("❌ archive: run %d failed unexpectedly", run_id)
                return finish_run(conn, run_id, status=RunStatus.FAILED, error=self.last_error)
            self.last_error = None
            return run
        finally:
            conn.close()
            self._active_run_id = None
            self._lock.release()

    def _execute(self, conn: sqlite3.Connection, run_id: int, limit: int | None) -> dict[str, Any]:
        plan = self._call("plan", {"candidates": self.candidates})
        mails = [m for m in plan.get("mails") or [] if isinstance(m, dict)]
        already_filed = filed_message_ids(conn)
        decisions: list[dict[str, Any]] = []
        item_by_message: dict[str, int] = {}
        skipped = 0

        # Which mails this run is about is settled *before* the model sees any
        # of them: the ranking is one bounded pass over exactly the mails that
        # will be decided, never a request per mail.
        selected: list[dict[str, Any]] = []
        for mail in mails:
            message_id = str(mail.get("message_id") or "").strip()
            if not message_id or message_id in already_filed:
                skipped += 1
                continue
            if limit is not None and len(selected) >= limit:
                break
            selected.append(mail)
        ranking = self._rank(conn, selected)

        for mail in selected:
            message_id = str(mail.get("message_id") or "").strip()
            decision = self._decide(mail, ranking.picks.get(message_id))
            try:
                item_id = insert_item(conn, run_id, **self._item_fields(mail, decision))
            except sqlite3.IntegrityError:
                # The unique index is the last word on "a mail is filed once",
                # even against a plan this database disagrees with.
                logger.warning("⚠️ archive: %s is already filed — skipped", message_id)
                skipped += 1
                continue
            item_by_message[message_id] = item_id
            if decision.status == "archived":
                already_filed.add(message_id)
            if decision.apply:
                decisions.append({
                    "message_id": message_id,
                    "folder_path": decision.chosen_folder,
                    # Handed straight back, unchanged: the archiver inferred the
                    # naming form this folder uses, and it owns that rule.
                    "date_prefix": decision.date_prefix,
                })

        logger.info(
            "ℹ️ archive: run %d — %d mail(s) in the Inbox, %d decided, %d to file, %d skipped",
            run_id, len(mails), len(item_by_message), len(decisions), skipped,
        )
        sync_run_counts(conn, run_id)
        if decisions:
            try:
                result = self._call("apply", {"decisions": decisions})
            except Exception as exc:
                # The rows went in as ``archived`` before the call; a whole-call
                # failure confirmed none of them, and left that way they would
                # be skipped by every later run while the mails sit in the Inbox.
                self._fail_unconfirmed(conn, decisions, item_by_message, str(exc))
                raise
            self._record_apply(conn, result, item_by_message)
            # Which mail is why a folder was re-sequenced: the first this run
            # filed into it. A second mail into the same folder rode the same
            # single renumber, so naming them all would report one repair
            # several times over.
            triggers: dict[str, int] = {}
            for decision in decisions:
                item_id = item_by_message.get(str(decision["message_id"]))
                if item_id is not None:
                    triggers.setdefault(path_key(str(decision["folder_path"])), item_id)
            self._heal_renumber(conn, result, triggers)
            sync_run_counts(conn, run_id)
        filed = sorted({str(d["folder_path"]) for d in decisions}, key=str.casefold)
        if filed:
            logger.info("ℹ️ archive: run %d — applied, re-indexing %d folder(s)", run_id, len(filed))
        scan_error = self._rescan_index(filed) if decisions else None
        if scan_error:
            logger.warning("⚠️ archive: %s", scan_error)
        logger.info("ℹ️ archive: run %d — closing", run_id)
        # Two different partial failures, both recorded rather than folded into
        # a clean run: the model did not rank part of this Inbox, and the
        # archiver's index has not confirmed what was filed.
        notes = [*ranking.errors, scan_error] if scan_error else list(ranking.errors)
        return finish_run(
            conn, run_id, status=RunStatus.DONE, error=" · ".join(notes) or None,
            agreement=ranking.agreement,
        )

    def _rank(self, conn: sqlite3.Connection, mails: list[dict[str, Any]]) -> Ranking:
        """Let the local model choose among the archiver's candidates.

        Reads the correction memory here, where the database is, and hands
        :func:`src.archive_rank.rank` plain data — that function stays pure, and
        a failure of the hub never reaches this method as an exception.
        """
        if not mails:
            return Ranking()
        corrections = recent_corrections(conn, limit=self.examples)
        ranking = archive_rank.rank(
            mails, corrections, self.ai, batch_size=self.batch_size,
        )
        if ranking.ranked:
            logger.info(
                "ℹ️ archive: the model ranked %d mail(s) with %d correction(s) in the prompt "
                "— %.0f%% agreement with the archiver",
                ranking.ranked, len(corrections), (ranking.agreement or 0.0) * 100,
            )
        return ranking

    def _decide(self, mail: dict[str, Any], pick: Pick | None = None) -> Decision:
        """Pick this mail's destination and the state that follows from it.

        Three sources, in order: the archiver's index already has the mail (then
        nothing is decided at all), the **model** chose among the candidates
, or the model could not be asked and the archiver's own top
        candidate stands, with the reason saying so.
        """
        already = mail.get("already_archived")
        if already:
            # A mail whose file is on disk **and** which is still sitting in the
            # Inbox is the shape a refused move leaves behind:
            # recording it as done would leave it in the Inbox forever. ``apply``
            # finishes it — it writes nothing, moves the mail and tags it — so the
            # decision goes back with the folder the file already lives in.
            #
            # ``in_inbox`` is additive: a plan that does not state it comes from
            # an older archiver whose ``apply`` would file the mail a second
            # time, so anything but a literal ``True`` keeps the old no-op.
            if mail.get("in_inbox") is True:
                folder = _folder_of(str(already))
                return Decision(
                    status="archived", apply=True, chosen_folder=folder,
                    date_prefix=self._date_prefix_for(mail, folder), files=(already,),
                    reason="finished a mail already on disk — its file is reused, "
                           "nothing is written",
                )
            return Decision(
                status="archived", files=(already,),
                reason="the archiver's index already has this mail filed — nothing was written",
            )
        candidates = [c for c in mail.get("candidates") or [] if isinstance(c, dict)]
        if not candidates:
            return Decision(status="needs_review", reason="the archiver ranked no folder for this mail")
        if pick is not None and pick.source == "model":
            return self._model_decision(candidates, pick)
        return self._suggester_decision(candidates, note=pick.reason if pick else None)

    def _model_decision(self, candidates: list[dict[str, Any]], pick: Pick) -> Decision:
        """The local model's own choice — an index into ``candidates``, never a path."""
        if pick.candidate is None:
            return Decision(
                status="needs_review", confidence=pick.confidence,
                reason=f"none of the ranked folders fits: {pick.reason}",
            )
        chosen = candidates[pick.candidate]
        folder = str(chosen.get("folder_path") or "")
        if not folder:
            return Decision(
                status="needs_review", chosen_rank=pick.candidate, confidence=pick.confidence,
                reason="the folder the model picked names no path",
            )
        confidence = float(pick.confidence or 0.0)
        filed = Decision(
            status="archived", apply=True, chosen_folder=folder, chosen_rank=pick.candidate,
            confidence=confidence, date_prefix=bool(chosen.get("date_prefix")), reason=pick.reason,
        )
        if confidence < self.threshold:
            return replace(
                filed, status="needs_review", apply=False,
                reason=f"{pick.reason} — {confidence:.2f} confidence is below the "
                       f"{self.threshold:.2f} threshold, so it is left in the Inbox for you",
            )
        return filed

    def _suggester_decision(
        self, candidates: list[dict[str, Any]], *, note: str | None = None
    ) -> Decision:
        """The archiver's own top candidate — what stands when the model was not asked.

        ``note`` is why the model did not decide this one (the hub was down, off
        or answering junk). It rides the reason so the report never shows a
        rank-0 filing as if a model had chosen it.
        """
        prefix = f"{note} — " if note else ""
        top = candidates[0]
        score = float(top.get("score") or 0.0)
        folder = str(top.get("folder_path") or "")
        if not folder:
            return Decision(
                status="needs_review", confidence=score,
                reason=f"{prefix}the archiver's top candidate names no folder",
            )
        filed = Decision(
            status="archived", apply=True, chosen_folder=folder, chosen_rank=0, confidence=score,
            date_prefix=bool(top.get("date_prefix")),
            reason=f"{prefix}the archiver's top folder at {score:.2f} ≥ the "
                   f"{self.threshold:.2f} threshold",
        )
        if score < self.threshold:
            return replace(
                filed, status="needs_review", apply=False,
                reason=f"{prefix}the best folder scored {score:.2f}, below the "
                       f"{self.threshold:.2f} threshold — left in the Inbox for you",
            )
        return filed

    @staticmethod
    def _item_fields(mail: dict[str, Any], decision: Decision) -> dict[str, Any]:
        return {
            "message_id": str(mail.get("message_id") or ""),
            "entry_id": str(mail.get("entry_id") or "") or None,
            "subject": str(mail.get("subject") or ""),
            "sender": str(mail.get("sender") or ""),
            "sent_at": str(mail.get("date_sent") or "") or None,
            "attachments": int(mail.get("attachment_count") or 0),
            "candidates_json": json.dumps(mail.get("candidates") or [], ensure_ascii=False),
            "chosen_folder": decision.chosen_folder,
            "chosen_rank": decision.chosen_rank,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "date_prefix": int(bool(decision.date_prefix)),
            "files_json": json.dumps(list(decision.files), ensure_ascii=False),
            "status": decision.status,
        }

    @staticmethod
    def _fail_unconfirmed(
        conn: sqlite3.Connection, decisions: list[dict[str, Any]],
        item_by_message: dict[str, int], reason: str,
    ) -> None:
        """Turn every row handed to a failed ``apply`` from ``archived`` into ``failed``.

        ``files`` is left alone: a finish row already knows its ``.msg``,
        and what a call that never answered wrote is not known either way.
        """
        message = f"apply failed as a whole, so this mail was not confirmed filed: {reason}"
        for decision in decisions:
            item_id = item_by_message.get(str(decision["message_id"]))
            if item_id is not None:
                update_item(conn, item_id, status=ItemStatus.FAILED.value, error=message)
        logger.warning("⚠️ archive: apply failed as a whole — %d mail(s) marked failed", len(decisions))

    def _record_apply(
        self, conn: sqlite3.Connection, result: dict[str, Any], item_by_message: dict[str, int]
    ) -> None:
        """Fold one ``apply`` document back onto the rows it belongs to.

        The document's own ``files`` are read **through** its renumber map: with
        ``--renumber`` they name what each mail was written as, before the
        re-sequencing that ran after it, and storing those
        would record a path that no longer exists.
        """
        renames = rename_index(result)
        for entry in result.get("results") or []:
            if not isinstance(entry, dict):
                continue
            item_id = item_by_message.get(str(entry.get("message_id") or ""))
            if item_id is None:
                logger.warning("⚠️ archive: apply reported a mail this run never decided on")
                continue
            files = rename_files([str(f) for f in entry.get("files") or []], renames)
            if not files:
                # Naming no file is not "the file is gone". A reuse is
                # answered for a row that was inserted already knowing where its
                # ``.msg`` is, and overwriting that with an empty list would make
                # a mail that *is* on disk look unrevertible. What the archiver
                # does not say leaves the row's own value alone — the same rule
                # :meth:`retry` reads its answer by.
                known = get_item(conn, item_id)
                # Through the map as well: the file the row already knew about
                # is in the folder that was just re-sequenced, so it may be
                # exactly one of the ones that moved.
                files = rename_files(list(known["files"]), renames) if known else []
            error = entry.get("error") or None
            if entry.get("ok"):
                update_item(
                    conn, item_id, status="archived", files_json=json.dumps(files, ensure_ascii=False),
                    sequence=str(entry.get("sequence_number") or "") or None,
                    entry_id=str(entry.get("entry_id") or "") or None, error=None,
                )
                self._log_finish(entry)
                continue
            # ``files`` is filled in before the move, so a failure here can still
            # have written to disk — recorded as such, because that is exactly
            # what makes it revertible.
            message = self._apply_error_message(error, files)
            update_item(
                conn, item_id, status=ItemStatus.FAILED.value,
                files_json=json.dumps(files, ensure_ascii=False),
                sequence=str(entry.get("sequence_number") or "") or None,
                entry_id=str(entry.get("entry_id") or "") or None, error=message,
            )
            logger.warning("⚠️ archive: a mail did not file — %s", message)

    def _heal_renumber(
        self, conn: sqlite3.Connection, doc: Any, triggers: dict[str, int] | None = None
    ) -> None:
        """Apply one verb's ``renumbered`` map to every path this database stores.

        ``triggers`` maps a folder to the item whose filing (or undoing) is why
        that folder was re-sequenced, so the report can say so: the row gets
        ``· renumbered N file(s) in <folder>`` appended to its reason. A folder
        with no trigger — one the same run touched through another mail — is
        still healed; it just has nobody to attribute it to.

        Runs after the item's own update, never before: ``move`` writes the
        reason, and appending to it first would only have it overwritten.
        """
        for folder, entries in renumbered_folders(doc).items():
            counts = apply_renumber_map(
                conn, folder, entries, placeholders_map=self.placeholders,
            )
            item_id = (triggers or {}).get(path_key(folder))
            if counts["renames"] and item_id is not None:
                self._note_renumber(conn, item_id, folder, counts["renames"])

    @staticmethod
    def _note_renumber(conn: sqlite3.Connection, item_id: int, folder: str, count: int) -> None:
        """Append the renumbering to the item's reason — the screen's own breadcrumb."""
        item = get_item(conn, item_id)
        if item is None:  # pragma: no cover - the row was just written
            return
        note = f" · renumbered {count} file(s) in {last_component(folder)}"
        reason = str(item["reason"] or "")
        if note in reason:
            return
        update_item(conn, item_id, reason=reason + note)

    @staticmethod
    def _log_finish(entry: dict[str, Any]) -> None:
        """Breadcrumb for the two additive ``apply`` fields.

        Neither is stored — they describe *how* one archive call went, not the
        state of the mail — but which of them applied is the first thing anyone
        asks when a stuck mail finally leaves the Inbox, so the log has to be
        able to answer it. Read by name and defensively: an older archiver
        states neither and this stays quiet rather than inventing a path.
        """
        if entry.get("reused"):
            logger.info(
                "ℹ️ archive: %s was finished from the file already on disk (moved via %s)",
                entry.get("message_id"), entry.get("move_via") or "an unnamed path",
            )
        elif entry.get("move_via") in ("refetched", "saved_retry"):
            logger.info(
                "ℹ️ archive: %s needed the archiver's %s path to move",
                entry.get("message_id"), entry.get("move_via"),
            )

    @staticmethod
    def _apply_error_message(error: Any, files: list[str]) -> str:
        code = str((error or {}).get("code", "")) if isinstance(error, dict) else ""
        message = str((error or {}).get("message", "")) if isinstance(error, dict) else ""
        base = f"{code or 'unknown'}: {message}" if message else (code or "the archiver gave no reason")
        if code == "move_failed":
            return f"{base} — the files are on disk and the mail is still in the Inbox"
        if code == "category_failed":
            return f"{base} — the mail is filed and moved, only the Outlook category is missing"
        if files:
            return f"{base} — {len(files)} file(s) were already written"
        return base



__all__ = [
    "ArchiveBatchService",
    "ArchiveError",
]
