"""Per-mail actions on an archived item: undo, move by hand, retry, accept.

Each one is a short archiver call (or none) on one row of the report screen,
taken under the same lock a run holds. :class:`ItemActions` is mixed into
``src.archive_batch.ArchiveBatchService``, which supplies the spawn, the lock,
the placeholders and the renumber healing these methods lean on."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from src import clock, placeholders
from src.archive_renumber import path_key, rename_files, rename_index
from src.archive_store import (
    FILED_STATUSES,
    REVIEWABLE_STATUSES,
    get_item,
    record_correction,
    update_item,
)

logger = logging.getLogger(__name__)



class ArchiveError(RuntimeError):
    """A classified archiving failure, ready for the one JSON error envelope."""

    def __init__(self, code: str, message: str, *, http_status: int, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.detail = detail



def _same_folder(a: str | None, b: str | None) -> bool:
    """Two folder paths naming the same place, separators and case aside.

    The archiver reports Windows paths with backslashes; ``placeholders.resolve``
    returns forward slashes. Comparing them raw would call every move a move
    into a new folder.
    """
    if not a or not b:
        return False
    return path_key(a) == path_key(b)


class ItemActions:
    """The report screen's per-mail actions — see the module docstring."""

    def _claim(self) -> None:
        """Take the archiver for one short call (revert / move)."""
        if not self.enabled:
            raise ArchiveError("archive_disabled", self.reason or "batch archiving is off", http_status=409)
        if not self._lock.acquire(blocking=False):
            raise ArchiveError(
                "archive_in_flight",
                "an archiving run is already in progress — one Outlook, one run at a time",
                http_status=409,
            )

    @staticmethod
    def _require(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
        item = get_item(conn, item_id)
        if item is None:
            raise ArchiveError("not_found", f"no archive item {item_id}", http_status=404)
        return item

    @staticmethod
    def _has_files_on_disk(item: dict[str, Any]) -> bool:
        """Is there anything of this mail in the archive tree right now?

        The two filed states always have files; a ``failed`` row has them
        whenever ``apply`` got as far as writing before it broke. Everything
        else — ``needs_review``, ``reverted`` — is a mail that is still (or
        again) in the Inbox with nothing on disk.
        """
        return item["status"] in FILED_STATUSES or (
            item["status"] == "failed" and bool(item["files"])
        )

    @classmethod
    def _require_revertible(cls, item: dict[str, Any]) -> None:
        """Filed, or failed with files already on disk — the two undoable shapes."""
        if cls._has_files_on_disk(item):
            return
        raise ArchiveError(
            "archive_bad_state",
            f"archive item {item['id']} is {item['status']} and has no archived file — there is "
            "nothing to undo",
            http_status=409,
        )

    @classmethod
    def _require_movable(cls, item: dict[str, Any]) -> None:
        """The shapes a human may file into a folder they picked.

        Wider than :meth:`_require_revertible` on purpose: a ``needs_review``
        mail is the one the screen (#159) most needs to move — the system was
        not confident enough to file it, so a human names the folder. There is
        nothing on disk to undo first, which is the only difference; every
        other state is either already handled (filed → undo, then re-file) or
        genuinely nothing to act on (``reverted``: the mail is back in the
        Inbox and a fresh run owns it again).
        """
        if cls._has_files_on_disk(item) or item["status"] == "needs_review":
            return
        raise ArchiveError(
            "archive_bad_state",
            f"archive item {item['id']} is {item['status']} — there is nothing here to file",
            http_status=409,
        )

    def revert(self, conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
        """Delete this mail's archive files and put it back in the Inbox."""
        item = self._require(conn, item_id)
        self._require_revertible(item)
        self._claim()
        try:
            result = self._revert_once(item)
        finally:
            self._lock.release()
        if not result["ok"]:
            # The row keeps its state on purpose: a partial undo is not a
            # revert, and re-running it is safe (a file already gone comes back
            # as ``missing``, not as an error).
            update_item(conn, item_id, error=result["message"])
            # The verb still completed — a per-mail failure is reported *inside*
            # a successful run — so it may have renumbered anyway. A map that
            # describes the disk is healed whether or not this mail's undo went
            # through; dropping it on the error path is how a stale path
            # survives.
            self._heal_renumber(conn, result["doc"])
            raise ArchiveError("archive_revert_failed", result["message"], http_status=502)
        reverted = update_item(
            conn, item_id, status="reverted", files_json="[]", error=None,
            decided_at=clock.now_iso(),
        )
        # The undo left a hole in the folder's numbering and the archiver closed
        # it, which renamed files belonging to the *other* mails in there —
        # never this one, whose files are now gone.
        self._heal_renumber(conn, result["doc"], {path_key(item["chosen_folder"] or ""): item_id})
        return get_item(conn, item_id) or reverted

    def _revert_once(self, item: dict[str, Any]) -> dict[str, Any]:
        """One ``revert`` child call for one item → ``{ok, message, entry, doc}``.

        The whole document rides back, not only this mail's entry: the
        renumbering that closed the hole this undo left is reported per
        *folder*, and healing it is the caller's step (:meth:`_heal_renumber`)
        because only the caller has the connection.
        """
        doc = self._spawn_with_payload(
            "revert", "--items", [{"message_id": item["message_id"], "files": item["files"]}]
        )
        entry = next((r for r in doc.get("results") or [] if isinstance(r, dict)), None)
        if entry is None:
            return {
                "ok": False, "message": "the archiver reported no result for this mail",
                "entry": None, "doc": doc,
            }
        if entry.get("ok"):
            return {"ok": True, "message": "", "entry": entry, "doc": doc}
        error = entry.get("error") or {}
        code = str(error.get("code", "")) if isinstance(error, dict) else ""
        message = str(error.get("message", "")) if isinstance(error, dict) else ""
        refused = entry.get("refused") or []
        file_errors = entry.get("file_errors") or []
        parts = [f"the archiver could not fully undo this mail ({code or 'no code'})"]
        if message:
            parts.append(message)
        if refused:
            parts.append(f"{len(refused)} file(s) refused as outside the archive roots")
        if file_errors:
            parts.append(f"{len(file_errors)} file(s) could not be deleted")
        return {"ok": False, "message": " — ".join(parts), "entry": entry, "doc": doc}

    def move(
        self, conn: sqlite3.Connection, item_id: int, folder: str, *, hint: str | None = None
    ) -> dict[str, Any]:
        """File this mail into ``folder``: undo the current filing, then apply again.

        ``folder`` takes a folder ref or an absolute path and is resolved
        through the same placeholders ``POST /api/resolve`` uses, so the phone
        and a second PC can name a folder the way they already do everywhere.

        A ``needs_review`` mail has nothing on disk, so there is no undo leg for
        it — it is simply filed where the human said, which is how the report
        screen (#159) resolves the rows the ranking refused to decide. Every
        other movable row is undone first and then filed afresh; the archiver
        owns the filenames either way.

        A move that lands is also the clearest correction there is, so it writes
        an ``archive_corrections`` row (#158) carrying the optional ``hint`` —
        the one-line note the report screen (#159) offers — into every later
        prompt.
        """
        item = self._require(conn, item_id)
        self._require_movable(item)
        filed = self._has_files_on_disk(item)
        destination = self._move_destination(item, folder, filed)
        date_prefix = self._date_prefix_for(item, destination)
        applied, undo = self._undo_and_apply(conn, item, destination, date_prefix, filed)
        return self._record_move(conn, item, applied, undo, destination, date_prefix, filed, hint)

    def _move_destination(self, item: dict[str, Any], folder: str, filed: bool) -> str:
        """``folder`` resolved on this install — refused when it does not resolve, or
        when a filed mail already sits there."""
        target = placeholders.resolve(
            placeholders.to_ref(folder, self.placeholders), self.placeholders
        )
        if not target.resolved:
            raise ArchiveError(
                "archive_bad_folder",
                f"{folder!r} does not resolve on this install"
                + (f" (unknown {', '.join(target.unresolved)})" if target.unresolved else ""),
                http_status=422,
            )
        destination = target.path
        # Only a mail that is actually filed there can be "already filed there".
        # A ``needs_review`` row often carries the folder the model was not
        # confident enough about, and filing it into exactly that folder is the
        # commonest thing a human does on this screen — refusing it would refuse
        # the feature.
        if filed and _same_folder(destination, item["chosen_folder"]):
            raise ArchiveError(
                "archive_bad_folder", "this mail is already filed in that folder", http_status=409,
            )
        return destination

    def _undo_and_apply(
        self, conn: sqlite3.Connection, item: dict[str, Any], destination: str, date_prefix: bool,
        filed: bool,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Under the lock: undo the current filing (when there is one), then ``apply``
        into ``destination`` → (the apply document, the undo result or ``None``)."""
        item_id = item["id"]
        self._claim()
        undo: dict[str, Any] | None = None
        try:
            if filed:
                undo = self._revert_once(item)
                if not undo["ok"]:
                    update_item(conn, item_id, error=undo["message"])
                    self._heal_renumber(conn, undo["doc"])
                    raise ArchiveError(
                        "archive_revert_failed",
                        f"nothing was moved: {undo['message']}", http_status=502,
                    )
            try:
                applied = self._spawn_with_payload("apply", "--decisions", [{
                    "message_id": item["message_id"], "folder_path": destination,
                    "date_prefix": date_prefix,
                }])
            except Exception as exc:
                # The undo leg already deleted the files and sent the mail back
                # to the Inbox. Leaving the row ``archived`` would name files
                # that no longer exist — and ``filed_message_ids`` would then
                # keep every later run from filing this mail again.
                if undo is not None:
                    logger.warning(
                        "⚠️ archive: item %s was undone but its re-file failed — %s", item_id, exc,
                    )
                    update_item(
                        conn, item_id, status="reverted", files_json="[]",
                        error=f"the move was undone but the re-file failed, so the mail is back "
                        f"in the Inbox: {exc}",
                        decided_at=clock.now_iso(),
                    )
                    self._heal_renumber(conn, undo["doc"])
                raise
        finally:
            self._lock.release()

        return applied, undo

    def _record_move(
        self, conn: sqlite3.Connection, item: dict[str, Any], applied: dict[str, Any],
        undo: dict[str, Any] | None, destination: str, date_prefix: bool, filed: bool,
        hint: str | None,
    ) -> dict[str, Any]:
        """Write what the move did to the row (and the correction memory), heal
        both legs' renumbering, and raise when the archiver did not land it."""
        item_id = item["id"]
        entry = next((r for r in applied.get("results") or [] if isinstance(r, dict)), None)
        if entry is None:
            # Whatever was on disk has been deleted by the undo leg (when there
            # was one) and nothing was written, so the mail is in the Inbox
            # either way — but a row that was never filed did not become an
            # *undo*, and calling it one would invent a filing that never was.
            where = "back in" if filed else "still in"
            update_item(
                conn, item_id, status="reverted" if filed else item["status"], files_json="[]",
                error=f"the archiver reported no result for the move; the mail is {where} the Inbox",
                decided_at=clock.now_iso(),
            )
            # Both verbs completed, so both maps describe the disk — the undo
            # renumbered the folder the mail left whatever the apply said.
            if undo is not None:
                self._heal_renumber(conn, undo["doc"])
            self._heal_renumber(conn, applied)
            raise ArchiveError(
                "archive_move_failed",
                f"the archiver reported no result for the move — the mail is {where} the Inbox",
                http_status=502,
            )
        files = rename_files([str(f) for f in entry.get("files") or []], rename_index(applied))
        common = {
            "chosen_folder": destination, "chosen_rank": None, "confidence": None,
            "date_prefix": int(bool(date_prefix)),
            "files_json": json.dumps(files, ensure_ascii=False),
            "sequence": str(entry.get("sequence_number") or "") or None,
            "entry_id": str(entry.get("entry_id") or "") or None,
            "decided_at": clock.now_iso(),
        }
        if entry.get("ok"):
            # Where it actually came from, not where it was ranked for: a
            # ``needs_review`` mail carries the folder the model was unsure
            # about, and reading that back as its previous home would record a
            # filing that never happened.
            reason = (
                f"moved here by hand from {item['chosen_folder'] or 'its previous folder'}"
                if filed else "filed here by hand from the Inbox"
            )
            moved = update_item(
                conn, item_id, status="moved", error=None, reason=reason, **common,
            )
            record_correction(conn, item, chosen_folder=destination, hint=hint)
            # Both legs can have re-sequenced a folder — the one the mail left
            # (the undo closed its hole) and the one it landed in — and this
            # item is what triggered each. Healed after the row is written, so
            # the reason the note is appended to is the final one.
            if undo is not None:
                self._heal_renumber(
                    conn, undo["doc"], {path_key(item["chosen_folder"] or ""): item_id},
                )
            self._heal_renumber(conn, applied, {path_key(destination): item_id})
            return get_item(conn, item_id) or moved
        message = self._apply_error_message(entry.get("error"), files)
        update_item(conn, item_id, status="failed", error=message, **common)
        if undo is not None:
            self._heal_renumber(conn, undo["doc"])
        self._heal_renumber(conn, applied)
        raise ArchiveError("archive_move_failed", message, http_status=502)

    @staticmethod
    def _require_retryable(item: dict[str, Any]) -> None:
        """The one shape a retry finishes: refused *after* the files were written.

        Two distinct refusals, because the fix differs: a row in any other state
        has nothing half-done to finish, and a ``failed`` row that never reached
        disk has no folder to send back — re-deciding that one is a *run*'s job,
        not a retry's.
        """
        if item["status"] != "failed" or not item["files"]:
            raise ArchiveError(
                "archive_bad_state",
                f"archive item {item['id']} is {item['status']} with no archived file — a retry "
                "only finishes a mail whose files are already on disk",
                http_status=409,
            )
        if not item["chosen_folder"]:
            raise ArchiveError(
                "archive_bad_state",
                f"archive item {item['id']} has files but no folder to retry into — file it by "
                "hand instead",
                http_status=409,
            )

    def retry(self, conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
        """Send a refused move back to the archiver, unchanged (#174).

        The shape this exists for: ``apply`` wrote the ``.msg`` and then Outlook
        refused the move (``move_failed``), so the files are on disk and the mail
        is still in the Inbox — and every later ``plan`` reports it
        ``already_archived``, so no run would ever pick it up again. The remedy
        the archiver names is *apply the same decision again*
        (email-archiver#59): it writes nothing, reuses the existing file, moves
        the mail and tags it.

        So nothing is re-decided here. The **same** message, folder and naming
        form go back, and on ``ok`` the row becomes ``archived`` keeping the
        files and sequence it already had — a reused apply allocates no new
        sequence number and reports the existing file, and neither is a reason to
        forget what the row knows. A second refusal leaves the row ``failed``
        with the archiver's new message, which is the one that says whether
        restarting Outlook is what is left to try.
        """
        item = self._require(conn, item_id)
        self._require_retryable(item)
        self._claim()
        try:
            applied = self._spawn_with_payload("apply", "--decisions", [{
                "message_id": item["message_id"], "folder_path": item["chosen_folder"],
                "date_prefix": bool(item["date_prefix"]),
            }])
        finally:
            self._lock.release()

        entry = next((r for r in applied.get("results") or [] if isinstance(r, dict)), None)
        if entry is None:
            # Nothing was asked of Outlook that could have half-succeeded: the
            # row keeps its files and its state, and only the reason changes.
            message = ("the archiver reported no result for the retry — the files are still on "
                       "disk and the mail is still in the Inbox")
            update_item(conn, item_id, error=message)
            raise ArchiveError("archive_retry_failed", message, http_status=502)

        # Read back defensively: a reuse reports the existing file and an empty
        # sequence, but an index row whose file had gone is archived for real and
        # comes back with a new file and a new number. Whichever happened, what
        # the archiver says now wins over what the row remembered — and what it
        # does not say leaves the row's own value alone.
        renames = rename_index(applied)
        files = rename_files(
            [str(f) for f in entry.get("files") or []] or list(item["files"]), renames,
        )
        if entry.get("ok"):
            self._log_finish(entry)
            finished = update_item(
                conn, item_id, status="archived",
                files_json=json.dumps(files, ensure_ascii=False),
                sequence=str(entry.get("sequence_number") or "") or item["sequence"],
                entry_id=str(entry.get("entry_id") or "") or item["entry_id"],
                error=None, decided_at=clock.now_iso(),
            )
            self._heal_renumber(
                conn, applied, {path_key(str(item["chosen_folder"] or "")): item_id},
            )
            return get_item(conn, item_id) or finished
        message = self._apply_error_message(entry.get("error"), files)
        update_item(
            conn, item_id, status="failed",
            files_json=json.dumps(files, ensure_ascii=False), error=message,
        )
        self._heal_renumber(conn, applied)
        logger.warning("⚠️ archive: the retry did not finish item %d — %s", item_id, message)
        raise ArchiveError("archive_retry_failed", message, http_status=502)

    @staticmethod
    def _date_prefix_for(item: dict[str, Any], destination: str) -> bool:
        """The naming form the destination uses, per the archiver's own inference.

        ``plan`` reported one per candidate folder; when the destination is one
        of them that value is handed back unchanged. For a folder the plan never
        ranked there is nothing to infer from here — the archiver's rule is
        per-folder and it owns it — so the item's current form is kept, which is
        the closest thing to "what this mail already looked like".
        """
        for candidate in item.get("candidates") or []:
            if isinstance(candidate, dict) and _same_folder(
                str(candidate.get("folder_path") or ""), destination
            ):
                return bool(candidate.get("date_prefix"))
        return bool(item.get("date_prefix"))

    def accept(
        self, conn: sqlite3.Connection, item_id: int, *, hint: str | None = None
    ) -> dict[str, Any]:
        """Mark a row reviewed — no file moves, nothing written to Outlook.

        Only the two rows that ask for a human (``needs_review``, ``failed``)
        can be accepted: an ``archived`` row is finished, not reviewed, and
        answering 409 there keeps "I have seen this" from silently meaning two
        different things on the screen (#159).

        Accepting a ``needs_review`` mail that *had* a folder is the other half
        of the correction memory (#158): the system was not confident enough to
        file it and a human said that folder was right after all, which is a
        worked example exactly as a ``move`` is. A ``failed`` row teaches
        nothing about folders — the archiver broke, the ranking did not — and
        neither does a mail no folder was ever ranked for, so neither writes one.
        """
        item = self._require(conn, item_id)
        if item["status"] not in REVIEWABLE_STATUSES:
            raise ArchiveError(
                "archive_bad_state",
                f"archive item {item_id} is {item['status']}, which needs no review",
                http_status=409,
            )
        accepted = update_item(conn, item_id, decided_at=clock.now_iso())
        if item["status"] == "needs_review" and item["chosen_folder"]:
            record_correction(conn, item, chosen_folder=item["chosen_folder"], hint=hint)
        return accepted
