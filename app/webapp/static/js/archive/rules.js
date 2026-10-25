/* task-os — Settings → Email archiving: which review levels a row's own state
 * allows. A control that would 409 is never rendered, so every part asks here. */

'use strict';

//: The two states a human can still say "seen" about (the API's own
//: REVIEWABLE_STATUSES — accept answers 409 on anything else).
export const REVIEWABLE = ['needs_review', 'failed'];
//: The two states in which files actually exist on disk, so an undo has
//: something to undo. `failed` joins them only when files were written.
const FILED = ['archived', 'moved'];

/** A row that asked for a human and got one. The API keeps its status — the
 *  mail really is still `needs_review` where it sits — but the screen must
 *  not keep asking: a decided row shows what it is and offers nothing, which
 *  is what makes the bulk button's count and the rows agree. */
export function isDecided(item) {
  return REVIEWABLE.indexOf(item.status) >= 0 && !!item.decided_at;
}

export function isFiled(item) {
  return FILED.indexOf(item.status) >= 0 || (item.status === 'failed' && item.files.length > 0);
}

export function canMove(item) {
  return isFiled(item) || (item.status === 'needs_review' && !item.decided_at);
}

/** A move Outlook refused *after* the file was written — the one row
 *  where sending the same decision again finishes the mail rather than filing
 *  it a second time. Deliberately not gated on `decided_at`: saying "I have
 *  seen this" does not take the mail out of the Inbox, so the offer stands. */
export function canRetry(item) {
  return item.status === 'failed' && item.files.length > 0 && !!item.chosen_folder;
}
