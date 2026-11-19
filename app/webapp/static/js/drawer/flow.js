/* task-os — what the drawer does as a whole on the open task: set its
 * status (Done closes the drawer), unfold the link editors, and answer its
 * own keys. Each takes the drawer's `ctx` first (see drawer.js). */

'use strict';

import { Status } from '../tasks/status.js';

/** A status segment (or its key). Done is the end of the owner's flow on a
 *  task, so it closes the drawer; the action runner's toast offers Undo. A
 *  recurring task's Done is the roll to its next date (`complete`), unless
 *  `endSeries` closes it for good (the ⋯ menu). Every other status stays on
 *  the open task.
 *  @param {object} ctx
 *  @param {string} status
 *  @param {{endSeries?: boolean}} [o] */
export async function setStatus(ctx, status, o) {
  const t = ctx.current;
  if (!t || t.status === status) return;
  const value = status === Status.DONE && t.recurrence && !(o && o.endSeries) ? 'complete' : status;
  try {
    await ctx.opts.onStatus(t.id, value);
  } catch (_) {
    return;   // the write already said why
  }
  if (status === Status.DONE && ctx.current && ctx.current.id === t.id) ctx.opts.onClose();
}

/** Fold or unfold the folder and link editors under the Links row; unfolded,
 *  they come into view with the cursor in their first field. */
export function toggleLinks(ctx) {
  if (!ctx.current) return;
  ctx.linksEditing = !ctx.linksEditing;
  ctx.render();
  if (!ctx.linksEditing) return;
  const editor = ctx.el.querySelector('.drawer-links-editor');
  if (editor) editor.scrollIntoView({ block: 'nearest' });
  const first = ctx.el.querySelector('.drawer-links-editor input');
  if (first) first.focus();
}

/**
 * The drawer's own keys while a task is open: X done, C the comment field,
 * L the folder and link editors, D the calendar. The row keys that write
 * (1-3, T, W, P) go through keys.js's action runner instead, for the Undo.
 * @param {object} ctx
 * @param {string} key  lower-cased
 * @returns {boolean} whether the key was the drawer's
 */
export function handleKey(ctx, key) {
  if (!ctx.current) return false;
  if (key === 'x') { setStatus(ctx, Status.DONE); return true; }
  if (key === 'l') { toggleLinks(ctx); return true; }
  if (key === 'c') {
    const field = ctx.el.querySelector('.comment-input');
    if (field) { field.focus(); field.scrollIntoView({ block: 'nearest' }); }
    return true;
  }
  if (key === 'd') {
    const pick = ctx.el.querySelector('.drawer-due .snooze-pick');
    if (pick) pick.click();
    return true;
  }
  return false;
}
