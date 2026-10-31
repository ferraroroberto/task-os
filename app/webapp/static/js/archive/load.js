/* task-os — Settings → Email archiving: reading the service, the picker's runs
 * and the selected run. */

'use strict';

import { api } from '../../api.js';
import { toast } from '../../toast.js';
import { renderHead, renderPicker, renderRecent } from './head.js';
import { renderReport } from './report.js';

const RUNS_LIMIT = 20;

export async function refreshStatus(ctx) {
  try {
    ctx.st.status = (await api('/api/status')).archive || null;
  } catch (_) {
    ctx.st.status = null;     // unknown, which is not "off"
  }
  renderHead(ctx);
  ctx.opts.onStatus(ctx.st.status);
}

export async function loadRuns(ctx) {
  try {
    ctx.st.runs = (await api('/api/archive/runs?limit=' + RUNS_LIMIT)).runs || [];
  } catch (err) {
    ctx.st.runs = [];
    toast(err.message || 'Could not read the archive runs', 'error');
  }
  renderPicker(ctx);
  renderRecent(ctx);
}

export async function loadRun(ctx) {
  const st = ctx.st;
  if (st.runId == null) { st.run = null; renderReport(ctx); return; }
  try {
    st.run = await api('/api/archive/runs/' + st.runId);
  } catch (err) {
    st.run = null;
    toast(err.message || 'Could not read that run', 'error');
  }
  renderReport(ctx);
}

/** Everything this pane shows, in one pass — after an action, after a run. */
export async function reload(ctx) {
  await Promise.all([refreshStatus(ctx), loadRuns(ctx)]);
  await loadRun(ctx);
  ctx.opts.onChanged();
}

/** The pane was opened (or a run was started elsewhere): read it all, and
 *  pick the poll back up when the service says a run is in flight. */
export async function refresh(ctx) {
  const st = ctx.st;
  await Promise.all([refreshStatus(ctx), loadRuns(ctx)]);
  // A live run is the one to follow, whichever run the picker was last on:
  // `tick` polls `runId`, and a finished run there would end the poll (and the
  // Settings row's "running", which follows this pane's) while the new run
  // is still going.
  if (st.status && st.status.running && st.runs.length && st.runs[0].status === 'running') {
    st.runId = st.runs[0].id;
    st.liveRunId = st.runs[0].id;
    ctx.els.pick.value = String(st.runId);
  } else if (st.status && st.status.running && !st.polling) {
    st.liveRunId = null;   // `tick` looks the latest run up
  }
  await loadRun(ctx);
  if (st.status && st.status.running && !st.polling) ctx.startPolling();
}
