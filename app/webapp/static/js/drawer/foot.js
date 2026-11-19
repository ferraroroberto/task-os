/* task-os — the drawer's one destructive action, reached from the head's ⋯
 * menu (last, after a divider, as every row menu puts Delete). */

'use strict';

import { api } from '../../api.js';
import { confirmDialog } from '../../confirm.js';
import { toast } from '../../toast.js';

/** Delete the open task. The dialog names the task, the subtree that goes
 *  with it, and — for a synced coding task whose issue is still open — that
 *  the next sync brings it back (Roberto's call, never a silent
 *  resurrection). */
export async function deleteCurrent(ctx, t) {
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
