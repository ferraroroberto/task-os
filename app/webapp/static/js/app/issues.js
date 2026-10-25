/* task-os — the build readout and the issue sync: the provider status the
 * Settings card renders and the drawer and palette read, and the one sync
 * pass every ↻ funnels into. Each takes the app composer's `app` first.
 */

'use strict';

import { buildReadoutText } from '../../_vendored/page-foot/page-foot.js';
import { api } from '../../api.js';
import { toast } from '../../toast.js';

// ---------------------------------------------------------- build identity
export async function fetchVersion(app) {
  try {
    const res = await fetch('/api/version', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const body = await res.json();
    app.els.buildReadout.textContent = buildReadoutText(body.git_sha || 'unknown', body.built_at || '');
    if (app.els.settingsSite && body.schema_version != null) {
      app.els.settingsSite.textContent = 'version ' + body.schema_version;   // the Database row's value: plain words
    }
  } catch (err) {
    // An unreachable version endpoint is its own visible state, never blank.
    app.els.buildReadout.textContent = 'Build: unknown';
    app.state.headNote = 'Server unreachable';
    app.renderHeadStatus();
  }
}

// ------------------------------------------------------------ issue sync
// The provider status is shared state: the Settings card renders it
// (settings.js), the drawer and the palette read `state.issues`.
export async function fetchIssuesStatus(app) {
  try {
    app.state.issues = await api('/api/issues/status');
  } catch (err) {
    app.state.issues = null;
  }
  app.settings.renderIssues(app.state.issues);
}

let syncing = null;
/** One sync pass now; every ↻ in the app funnels here (Settings, drawer, palette). */
export async function syncIssues(app) {
  if (syncing) return syncing;
  syncing = (async function () {
    try {
      const r = await api('/api/issues/sync', { method: 'POST' });
      const bits = [];
      if (r.created) bits.push(r.created + ' new');
      if (r.retitled) bits.push(r.retitled + ' retitled');
      if (r.reopened) bits.push(r.reopened + ' reopened');
      if (r.closed) bits.push(r.closed + ' closed');
      if (r.errors && r.errors.length) bits.push(r.errors.length + ' error(s)');
      toast('Issues synced: ' + r.listed + ' open' + (bits.length ? ' · ' + bits.join(' · ') : ' · nothing changed'), r.errors && r.errors.length ? 'error' : 'success');
      await app.refreshAll();
      if (app.drawer.currentId() != null) app.drawer.refresh();
      return r;
    } catch (err) {
      toast('Issue sync failed: ' + (err.message || 'unknown'), 'error');
      throw err;
    } finally {
      await app.fetchIssuesStatus();
      syncing = null;
    }
  })();
  return syncing;
}
