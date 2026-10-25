/* task-os — Settings → Email archiving: the review levels one row offers — the
 * phone card's buttons and the desktop row's ⋮ menu. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { acceptItem, actionButton, retryItem, revertItem, runAction } from './actions.js';
import { movePanel } from './movepanel.js';
import { REVIEWABLE, canMove, canRetry, isDecided, isFiled } from './rules.js';

/** The buttons one row offers, and (when it can be moved) the panel that
 *  goes with them. `onToggle` lets the grid show/hide the extra row the
 *  panel lives in. */
export function actionsFor(ctx, item, hooks) {
  const wrap = document.createElement('div');
  wrap.className = 'archive-row-actions icon-button-group';
  if (REVIEWABLE.indexOf(item.status) >= 0 && !isDecided(item)) {
    wrap.appendChild(actionButton(ctx, 'check', 'Accept', function () { return acceptItem(item, null); }));
  }
  let body = null;
  if (canMove(item)) {
    const panel = movePanel(ctx, item, hooks);
    wrap.appendChild(panel.toggle);
    body = panel.body;
  }
  // Finish it before offering to undo it: on the one row that has both, the
  // mail is still in the Inbox and getting it out is what was meant to happen.
  if (canRetry(item)) {
    wrap.appendChild(actionButton(ctx, 'refresh-cw', 'Retry', function () { return retryItem(item); }));
  }
  // Revert deletes the archived file, so it is never a visible verb: it is
  // the last item of the card's kebab, behind its confirm.
  if (isFiled(item)) wrap.appendChild(revertKebab(ctx, item));
  const controls = wrap.childElementCount > 0;
  if (!controls) wrap.appendChild(nothingToPress(item));
  return { el: wrap, body: body, controls: controls };
}

/** The phone card's kebab: the destructive Revert, alone and last, behind
 *  the same confirm the desktop row menu uses. */
function revertKebab(ctx, item) {
  const kebab = document.createElement('button');
  kebab.type = 'button';
  kebab.className = 'icon-button archive-kebab action-row-kebab';
  kebab.setAttribute('aria-label', 'More actions for ' + (item.subject || '(no subject)'));
  kebab.title = 'More actions';
  kebab.innerHTML = icon('ellipsis-vertical');
  ctx.rowMenu.attach(String(item.id), kebab, [{
    label: 'Revert', glyph: 'rotate-ccw', danger: true, dataset: { action: 'revert' },
    onTap: function () { runAction(ctx, kebab, function () { return revertItem(item); }); },
  }]);
  return kebab;
}

/** A reverted mail is back in the Inbox and free to be filed by the next
 *  run; a decided one has already had its human. Nothing to press, said out
 *  loud rather than left as an empty cell. */
function nothingToPress(item) {
  const none = document.createElement('span');
  none.className = 'muted';
  none.textContent = item.status === 'reverted' ? 'back in the Inbox'
    : isDecided(item) ? 'nothing left to do' : '–';
  return none;
}

/** The desktop row's review levels behind one ⋮ (design.md
 *  action-row): the same Accept · Move to… / File it… · Retry · Revert the
 *  phone card holds, as the vendored row menu's items, so the row itself
 *  carries only its file chips and the kebab. *Move to…* opens the move
 *  panel in its own full-width row under the mail (`hooks.onToggle`), where
 *  focus lands on its first control. */
export function rowMenuFor(ctx, item, hooks) {
  const items = [];
  let body = null;
  const kebab = document.createElement('button');
  kebab.type = 'button';
  kebab.className = 'icon-button archive-kebab action-row-kebab';
  kebab.setAttribute('aria-label', 'Actions for ' + (item.subject || '(no subject)'));
  kebab.innerHTML = icon('ellipsis-vertical');
  if (REVIEWABLE.indexOf(item.status) >= 0 && !isDecided(item)) {
    items.push({ label: 'Accept', glyph: 'check', dataset: { action: 'accept' },
      onTap: function () { runAction(ctx, kebab, function () { return acceptItem(item, null); }); } });
  }
  if (canMove(item)) {
    const panel = movePanel(ctx, item, hooks);
    body = panel.body;
    const word = isFiled(item) ? 'Move to…' : 'File it…';
    items.push({
      label: function () { return body.hidden ? word : 'Close ' + word.replace('…', ''); },
      glyph: 'folder', dataset: { action: 'move' },
      onTap: function () {
        panel.toggle.click();
        if (!body.hidden) {
          const first = body.querySelector('button, input');
          if (first) first.focus();
        }
      },
    });
  }
  if (canRetry(item)) {
    items.push({ label: 'Retry', glyph: 'refresh-cw', dataset: { action: 'retry' },
      onTap: function () { runAction(ctx, kebab, function () { return retryItem(item); }); } });
  }
  if (isFiled(item)) {
    items.push({ label: 'Revert', glyph: 'rotate-ccw', danger: true, dataset: { action: 'revert' },
      onTap: function () { runAction(ctx, kebab, function () { return revertItem(item); }); } });
  }
  if (!items.length) return { el: nothingToPress(item), body: null };
  ctx.rowMenu.attach(String(item.id), kebab, items);
  return { el: kebab, body: body };
}
