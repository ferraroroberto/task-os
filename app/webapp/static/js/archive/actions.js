/* task-os — Settings → Email archiving: the review verbs (accept · move ·
 * retry · revert) and the one runner that serialises them. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { api } from '../../api.js';
import { confirmDialog } from '../../confirm.js';
import { resolveFolderRef } from '../../folderpick.js';
import { toast } from '../../toast.js';
import { isFiled } from './rules.js';
import { shortFolder } from './text.js';

/** A visible row verb (fleet-config#1420): the vendored plain icon-button,
 *  glyph only, its word kept as the accessible name and the tooltip. */
export function verbButton(glyph, label) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'icon-button action-row-verb archive-action';
  b.setAttribute('aria-label', label);
  b.title = label;
  b.innerHTML = icon(glyph);
  return b;
}

export function actionButton(ctx, glyph, label, handler) {
  const b = verbButton(glyph, label);
  b.addEventListener('click', function () {
    runAction(ctx, b, handler);
  });
  return b;
}

/** One place where an action disables its button, runs, and re-reads the
 *  world — so no two actions can race the archiver's single lock. */
export function runAction(ctx, button, handler) {
  if (ctx.st.busy) return;
  ctx.st.busy = true;
  button.disabled = true;
  Promise.resolve()
    .then(handler)
    .catch(function (err) { if (err) toast(err.message || 'Action failed', 'error'); })
    .then(function () {
      ctx.st.busy = false;
      return ctx.reload();
    });
}

export function acceptItem(item, hint) {
  return api('/api/archive/items/' + item.id + '/accept', {
    method: 'POST', body: hint ? { hint: hint } : {},
  }).then(function () { toast('Marked as reviewed', 'success'); });
}

/**
 * File `item` into `folder`.
 * @param {boolean} known  the folder came off the row's own candidates, so it
 *        is already a path this install produced — it goes to the API as it
 *        is (which folds it onto the placeholders itself). Only a folder a
 *        human *typed* is folded here first, where the "Stored as …" answer
 *        is the feedback that the path was understood.
 */
export async function moveItem(item, folder, hint, known) {
  const ref = known ? folder : await resolveFolderRef(folder);
  if (ref === undefined || ref === null) return;   // already toasted / nothing typed
  const ok = await confirmDialog({
    title: isFiled(item) ? 'Move this mail?' : 'File this mail?',
    lines: [
      item.subject || '(no subject)',
      isFiled(item)
        ? 'Its archived file is deleted and the mail is filed again under ' + ref + '.'
        : 'The mail leaves the Inbox and is filed under ' + ref + '.',
      hint ? 'Remembered as: “' + hint + '”' : null,
    ],
    action: isFiled(item) ? 'Move it' : 'File it',
  });
  if (!ok) return;
  const body = { folder: ref };
  if (hint) body.hint = hint;
  await api('/api/archive/items/' + item.id + '/move', { method: 'POST', body: body });
  toast('Filed under ' + shortFolder(ref), 'success');
}

/** One tap, no confirmation: this is the recovery gesture the row's own error
 *  text asks for, it deletes nothing, and it only ever finishes the filing the
 *  run already decided on. */
export function retryItem(item) {
  return api('/api/archive/items/' + item.id + '/retry', { method: 'POST', body: {} })
    .then(function () { toast('Filed — the mail has left the Inbox', 'success'); });
}

export async function revertItem(item) {
  const ok = await confirmDialog({
    title: 'Undo this mail?',
    lines: [
      item.subject || '(no subject)',
      'Its archived file(s) are deleted and the mail goes back to the Outlook Inbox.',
    ],
    warn: 'The file is deleted, not moved to the recycle bin.',
    action: 'Undo it',
  });
  if (!ok) return;
  await api('/api/archive/items/' + item.id + '/revert', { method: 'POST', body: {} });
  toast('Back in the Inbox', 'success');
}
