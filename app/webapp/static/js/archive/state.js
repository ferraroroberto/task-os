/* task-os — Settings → Email archiving: the JS mirror of src/archive_state.py.
 * The API sends a derived `state` on every run and every mail; this module
 * names those states and answers what each one allows. No other file compares
 * a status to a word or reads `files` / `decided_at` to guess a mode —
 * tests/archive/test_archive_state.py keeps this table in step with Python's. */

'use strict';

export const ArchiveState = {
  run: {
    RUNNING: 'running',
    INTERRUPTED: 'interrupted',
    DONE: 'done',
    FAILED: 'failed',
  },
  item: {
    ARCHIVED: 'archived',
    MOVED: 'moved',
    NEEDS_REVIEW: 'needs_review',
    REVIEWED: 'reviewed',
    FAILED_ON_DISK: 'failed_on_disk',
    FAILED_CLEAN: 'failed_clean',
    REVERTED: 'reverted',
  },
};

const RUN = ArchiveState.run;
const ITEM = ArchiveState.item;

//: Files exist on disk, so an undo has something to undo.
const ON_DISK = [ITEM.ARCHIVED, ITEM.MOVED, ITEM.FAILED_ON_DISK];
//: A human may say "seen" about these (accept answers 409 on anything else).
const REVIEWABLE = [ITEM.NEEDS_REVIEW, ITEM.REVIEWED, ITEM.FAILED_ON_DISK, ITEM.FAILED_CLEAN];

// ---- runs ------------------------------------------------------------------

/** A worker is driving this run right now. */
export function runIsLive(run) {
  return !!run && run.state === RUN.RUNNING;
}

/** The run ended without finishing its work: it failed, or the app stopped in the middle. */
export function runFailed(run) {
  return !!run && (run.state === RUN.FAILED || run.state === RUN.INTERRUPTED);
}

/** Warn while a run is in flight or ended badly, ok once it is done. */
export function runTone(run) {
  return runIsLive(run) || runFailed(run) ? 'warn' : 'ok';
}

/** Why a failed or interrupted run ended, in the API's own words. */
export function runReason(run) {
  return (run && (run.state_reason || run.error)) || 'no reason recorded';
}

// ---- mails -----------------------------------------------------------------

export function isFiled(item) {
  return ON_DISK.indexOf(item.state) >= 0;
}

export function isReverted(item) {
  return item.state === ITEM.REVERTED;
}

function isReviewed(item) {
  return item.state === ITEM.REVIEWED;
}

/** A row that asked for a human and got one. The API keeps its status — the
 *  mail really is still in the Inbox where it sits — but the screen must not
 *  keep asking: a decided row shows what it is and offers nothing, which is
 *  what makes the bulk button's count and the rows agree. */
export function isDecided(item) {
  return isReviewed(item) || (REVIEWABLE.indexOf(item.state) >= 0 && !!item.decided_at);
}

/** The row still owes a human an answer: it offers *Accept*. */
export function needsAnswer(item) {
  return REVIEWABLE.indexOf(item.state) >= 0 && !isDecided(item);
}

export function canMove(item) {
  return isFiled(item) || item.state === ITEM.NEEDS_REVIEW;
}

/** A move Outlook refused *after* the file was written — the one row
 *  where sending the same decision again finishes the mail rather than filing
 *  it a second time. Deliberately not gated on `decided_at`: saying "I have
 *  seen this" does not take the mail out of the Inbox, so the offer stands. */
export function canRetry(item) {
  return item.state === ITEM.FAILED_ON_DISK && !!item.chosen_folder;
}
