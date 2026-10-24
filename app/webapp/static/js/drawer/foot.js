/* task-os — the drawer's foot: the one destructive control. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { confirmDialog } from '../../confirm.js';
import { toast } from '../../toast.js';

async function deleteCurrent(ctx, t) {
  const n = Number(t.descendant_count) || 0;
  const ref = t.issue_ref;
  const ok = await confirmDialog({
    title: 'Delete "' + t.title + '"?',
    lines: [
      n ? 'Its ' + n + ' child task' + (n === 1 ? ' goes' : 's go') + ' with it.' : null,
      'This cannot be undone: the task, its comments, links and history are removed.',
    ],
    warn: ref && ref.state === 'open'
      ? 'Synced coding task: the next issue sync recreates it while ' + ref.repo + '#' + ref.number + ' stays open. Unlink it first, or close the issue.'
      : null,
    action: 'Delete',
  });
  if (!ok || !ctx.current || ctx.current.id !== t.id) return;
  try {
    const r = await api('/api/tasks/' + t.id, { method: 'DELETE' });
    ctx.opts.onClose();
    const gone = Number(r && r.deleted) || 1;
    toast('Deleted "' + t.title + '"' + (gone > 1 ? ' · ' + gone + ' tasks' : ''), 'success');
    ctx.opts.onChanged();
  } catch (err) {
    toast(err.message || 'Delete failed', 'error');
  }
}

/** A `Delete task` at the foot, away from the status select. The dialog
 *  names the task, the subtree that goes with it, and — for a synced coding
 *  task whose issue is still open — that the next sync brings it back
 *  (Roberto's call, never a silent resurrection). The one destructive
 *  control (#121), last and quiet. */
export function deleteFoot(ctx, t) {
  const foot = document.createElement('div');
  foot.className = 'drawer-section drawer-danger';
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'button-ghost drawer-delete';
  del.innerHTML = icon('trash-2') + ' Delete task';
  del.title = 'Delete this task' + (t.descendant_count ? ' and its ' + t.descendant_count + ' child task' + (t.descendant_count === 1 ? '' : 's') : '') + ' — asks first';
  del.addEventListener('click', function () { deleteCurrent(ctx, t); });
  foot.appendChild(del);
  return foot;
}
