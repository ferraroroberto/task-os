/* task-os — Settings → Email archiving: the listeners the sheet's own controls
 * and the two width breakpoints carry. */

'use strict';

import { api } from '../../api.js';
import { confirmDialog } from '../../confirm.js';
import { toast } from '../../toast.js';
import { runAction } from './actions.js';
import { renderHead, renderRecent } from './head.js';
import { loadRun } from './load.js';
import { renderReport } from './report.js';
import { startRun } from './run.js';

/** "Accept all": the bulk button's own confirm, then one accept per row it
 *  counted. */
function acceptAllPending(ctx) {
  const acceptAll = ctx.els.acceptAll;
  const ids = String(acceptAll.dataset.ids || '').split(',').filter(Boolean);
  if (!ids.length) return;
  runAction(ctx, acceptAll, async function () {
    const ok = await confirmDialog({
      title: 'Accept ' + ids.length + ' row(s)?',
      lines: [
        'They stay exactly where they are — this only records that you have seen them.',
        'Each one that has a folder also teaches the next run that the folder was right.',
      ],
      action: 'Accept them',
    });
    if (!ok) return;
    let failed = 0;
    for (const id of ids) {
      try {
        await api('/api/archive/items/' + id + '/accept', { method: 'POST', body: {} });
      } catch (_) { failed += 1; }
    }
    toast(failed
      ? (ids.length - failed) + ' accepted · ' + failed + ' refused'
      : ids.length + ' row(s) accepted', failed ? 'error' : 'success');
  });
}

export function wireArchive(ctx) {
  const els = ctx.els;
  els.run.addEventListener('click', function () { startRun(ctx); });
  els.pick.addEventListener('change', function () {
    ctx.st.runId = Number(els.pick.value) || null;
    loadRun(ctx);
  });
  els.acceptAll.addEventListener('click', function () { acceptAllPending(ctx); });
  if (ctx.phoneMq.addEventListener) ctx.phoneMq.addEventListener('change', function () { renderReport(ctx); });
  // The head's wording, the reasons and the bulk label are width-dependent too
  // a rotation must re-draw them, not leave the phone reading the
  // desktop's sentences.
  if (ctx.narrowMq.addEventListener) {
    ctx.narrowMq.addEventListener('change', function () {
      renderHead(ctx);
      renderRecent(ctx);
      renderReport(ctx);
    });
  }
}
