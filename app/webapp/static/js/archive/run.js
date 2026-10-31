/* task-os — Settings → Email archiving: starting a run and following it while
 * it is in flight. */

'use strict';

import { api } from '../../api.js';
import { toast } from '../../toast.js';
import { renderPicker } from './head.js';
import { loadRuns, refresh, refreshStatus } from './load.js';
import { renderReport } from './report.js';
import { counts } from './text.js';

//: How often the screen re-reads a run that is still going. The run itself is
//: minutes-scale over COM; this is only how often the counters move.
const POLL_MS = 1500;

function progressText(r) {
  if (!r) return '';
  if (r.status === 'running') return 'running… ' + counts(r);
  return r.status === 'failed' ? 'failed — ' + (r.error || 'no reason recorded') : 'done · ' + counts(r);
}

export function startPolling(ctx) {
  const st = ctx.st;
  window.clearTimeout(st.poll);
  st.polling = true;
  st.poll = window.setTimeout(function () { return tick(ctx); }, POLL_MS);
  ctx.els.run.disabled = true;
  ctx.els.limit.disabled = true;
  ctx.els.runLabel.textContent = 'Archiving…';
}

async function tick(ctx) {
  const st = ctx.st;
  st.poll = 0;
  let live;
  try {
    if (st.liveRunId == null) { const list = await api('/api/archive/runs?limit=1'); st.liveRunId = (list.runs[0] || {}).id; }
    live = await api('/api/archive/runs/' + st.liveRunId);
  } catch (err) {
    st.polling = false;
    ctx.els.progress.textContent = 'lost contact with the run — ' + (err.message || 'unknown');
    await refreshStatus(ctx);
    return;
  }
  // The picker may be on an older run for comparison: the report is redrawn
  // from the live run only while it is the one on show.
  if (st.runId === st.liveRunId) { st.run = live; renderReport(ctx); }
  ctx.els.progress.textContent = progressText(live);
  if (live.status === 'running') { startPolling(ctx); return; }
  st.polling = false;
  toast(live.status === 'failed'
    ? 'Archive run failed — ' + (live.error || 'see the report')
    : 'Archive run done · ' + counts(live), live.status === 'failed' ? 'error' : 'success');
  await Promise.all([refreshStatus(ctx), loadRuns(ctx)]);
  renderPicker(ctx);   // may settle `runId` on the latest run when none was picked yet
  if (st.runId === st.liveRunId) st.run = live;
  renderReport(ctx);
  ctx.opts.onChanged();
}

export async function startRun(ctx) {
  const st = ctx.st;
  const els = ctx.els;
  if (st.busy || (st.status && st.status.running)) return;
  const raw = els.limit.value.trim();
  const limit = raw === '' ? null : Number(raw);
  if (limit !== null && (!Number.isInteger(limit) || limit < 1 || limit > 1000)) {
    toast('“First N mails” takes a whole number from 1 to 1000, or nothing for the whole Inbox', 'error');
    return;
  }
  st.busy = true;
  els.run.disabled = true;
  els.progress.textContent = 'starting…';
  try {
    const started = await api('/api/archive/run', { method: 'POST', body: limit === null ? {} : { limit: limit } });
    st.runId = started.id;
    st.liveRunId = started.id;
    st.run = Object.assign({}, started, { items: [] });
    await loadRuns(ctx);
    els.pick.value = String(st.runId);
    els.progress.textContent = progressText(st.run);
    renderReport(ctx);
    startPolling(ctx);
    // The Settings row beside this sheet reads "running" from the status it
    // is handed: hand it the one that says so.
    await refreshStatus(ctx);
  } catch (err) {
    // 409 archive_in_flight is the honest answer to a second click, and the
    // API's own sentence is better than anything invented here.
    els.progress.textContent = '';
    toast(err.message || 'Could not start the run', 'error');
    // Released before the redraw, which re-reads it for the button's state.
    st.busy = false;
    // A run this screen had not seen (another device started it): follow
    // it, as opening the sheet would, rather than only re-reading the head.
    await refresh(ctx);
  } finally {
    st.busy = false;
  }
}
