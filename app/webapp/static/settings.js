/* task-os — the Settings tab: what this install is and what it can reach.
 *
 * One module per tab, like Board · Table · Tree · Today · Search:
 * `mountSettings(opts)` looks up the pane's cards once, wires their controls
 * and returns the handle the bootstrap calls when something it owns changes.
 * Every card is the vendored disclosure (issue #46) whose summary carries a
 * state word — on · synced · indexed · off — never a count.
 *
 *   Phone access   https + auth (Step 7) — how this connection came in and
 *                  what the install accepts; "Sign out on this device".
 *   Mirror/backup  the markdown mirror and the dated .db copies (Step 6).
 *   Issues         the issue provider's status (Step 8) + "Sync now". The
 *                  sync itself belongs to the bootstrap (the header ↻, the
 *                  drawer and the palette funnel through the same call), so
 *                  it arrives as `opts.onSyncIssues` and the status arrives
 *                  through `renderIssues(status)`.
 *   Search         which of the four indexes this install can query (Step 10);
 *                  the Search tab's own idle view is refreshed through
 *                  `opts.onSearchStatus`.
 *   Folder opener  the per-PC opener install command + the folder index
 *                  (Step 9), with "Reindex folders now".
 *
 * ONE `GET /api/status` feeds the access, mirror/backup and opener cards
 * (`refreshStatus()`); the search card has its own `GET /api/search/status`
 * (`refreshSearchStatus()`). An unreachable endpoint is its own visible
 * state — "unknown — <reason>" — never a stale "Loading…".
 */

'use strict';

import { api } from './api.js';
import { copyText, fmtTsShort } from './format.js';
import { toast } from './toast.js';

const SEARCH_KIND_ROWS = { tasks: 'statusSearchTasks', folders: 'statusSearchFolders', emails: 'statusSearchEmails', issues: 'statusSearchIssues' };

/**
 * Wire the Settings pane once and hand back the bootstrap's handle.
 * @param {{onSyncIssues: () => Promise<any>, onSearchStatus: () => void}} opts
 * @returns {{refreshStatus: () => Promise<void>, refreshSearchStatus: () => Promise<void>,
 *            renderIssues: (status: object|null) => void, revealCard: (key: string) => void}}
 */
export function mountSettings(opts) {
  const els = {
    accessClient: document.getElementById('accessClient'),
    accessRows: document.getElementById('accessRows'),
    signOutBtn: document.getElementById('signOutBtn'),
    mirrorCardMeta: document.getElementById('mirrorCardMeta'),
    statusMirror: document.getElementById('statusMirror'),
    statusBackup: document.getElementById('statusBackup'),
    statusMirrorEvents: document.getElementById('statusMirrorEvents'),
    mirrorEventsClear: document.getElementById('mirrorEventsClear'),
    folderCard: document.getElementById('folderCard'),
    folderCardMeta: document.getElementById('folderCardMeta'),
    statusOpener: document.getElementById('statusOpener'),
    statusIndex: document.getElementById('statusIndex'),
    openerInstall: document.getElementById('openerInstall'),
    openerCopy: document.getElementById('openerCopy'),
    openerUninstall: document.getElementById('openerUninstall'),
    openerEnv: document.getElementById('openerEnv'),
    openerEnvCopy: document.getElementById('openerEnvCopy'),
    reindexBtn: document.getElementById('reindexBtn'),
    issuesCardMeta: document.getElementById('issuesCardMeta'),
    statusIssues: document.getElementById('statusIssues'),
    statusIssuesSync: document.getElementById('statusIssuesSync'),
    issuesSyncNow: document.getElementById('issuesSyncNow'),
    searchCard: document.getElementById('searchCard'),
    searchCardMeta: document.getElementById('searchCardMeta'),
  };
  // The two cards a deep link (`#settings/opener`, `#settings/search`) opens.
  const DEEP_LINK_CARDS = { opener: els.folderCard, search: els.searchCard };

  // ------------------------------------------------------ phone access card
  function accessRow(label, ok, text) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.className = ok === null ? '' : (ok ? 'ok' : 'warn');
    dd.textContent = text;
    return [dt, dd];
  }

  function renderAccessCard(st) {
    const client = { loopback: 'this PC', token: 'signed in', public: 'public', denied: 'denied' }[st.auth.client] || st.auth.client;
    els.accessClient.textContent = client;
    els.accessRows.replaceChildren(
      ...accessRow('HTTPS', st.https, st.https ? 'on — Tailscale certificate' : 'off — plain HTTP (run scripts/gen_tailscale_cert.py)'),
      ...accessRow('Access token', st.auth.enabled, st.auth.enabled ? 'configured — other devices sign in at /login' : 'not set — only this PC can use the app (scripts/gen_token.py)'),
      ...accessRow('Password', null, st.auth.password ? 'set — accepted at /login' : 'not set (optional; scripts/set_password.py)'),
    );
    els.signOutBtn.hidden = st.auth.client !== 'token';
  }

  function renderAccessUnknown(message) {
    els.accessRows.replaceChildren(...accessRow('Status', false, 'unknown — ' + message));
  }

  function wireSignOut() {
    els.signOutBtn.addEventListener('click', async function () {
      try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { toast(err.message, 'error'); return; }
      location.assign('/login');
    });
  }

  // ----------------------------------------------- mirror + backup status
  function renderMirrorRow(dd, m) {
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!m || !m.enabled) {
      dd.append(statusPart('off', 'not configured'), ' — ' + ((m && m.reason) || 'unknown'));
      return;
    }
    dd.append(
      statusPart(m.errors ? 'warn' : 'ok', m.errors ? 'enabled · ' + m.errors + ' file(s) skipped' : 'enabled'),
      ' · ', codeEl(m.dir), ' · ' + (m.files == null ? '?' : m.files) + ' file(s)',
      ' · last export ' + (m.last_export ? fmtTsShort(m.last_export) : '–'),
      ' · last import ' + (m.last_import ? fmtTsShort(m.last_import) : '–')
    );
    if (m.error_files && m.error_files.length) dd.append(' · skipped: ' + m.error_files.join(', '));
  }

  // Mirror import diagnostics (issue #84) — recorded as `mirror_events` rows,
  // never as a comment on the task; this row is the "visible at app level"
  // half of the fix, with an inline preview (inspect) and a Clear action.
  async function renderMirrorEventsRow(m) {
    const dd = els.statusMirrorEvents;
    if (!dd) return;
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!m || !m.enabled) {
      dd.append(statusPart('off', 'not configured'));
      els.mirrorEventsClear.hidden = true;
      return;
    }
    const n = m.events || 0;
    if (!n) {
      dd.append(statusPart('ok', 'none since the last review'));
      els.mirrorEventsClear.hidden = true;
      return;
    }
    dd.append(statusPart('warn', n + ' since the last review'));
    els.mirrorEventsClear.hidden = false;
    try {
      const r = await api('/api/mirror/events');
      const items = (r.events || []).slice(0, 3).map(function (e) {
        return e.field + ': file said ' + e.file_value + ', kept ' + e.kept_value;
      });
      if (items.length) dd.append(' — ' + items.join('; ') + (n > items.length ? '; +' + (n - items.length) + ' more' : ''));
    } catch (_) { /* the count above still stands */ }
  }

  function wireMirrorEventsClear() {
    if (!els.mirrorEventsClear) return;
    els.mirrorEventsClear.addEventListener('click', async function () {
      els.mirrorEventsClear.disabled = true;
      try {
        const r = await api('/api/mirror/events', { method: 'DELETE' });
        toast('Cleared ' + r.cleared + ' import conflict(s)', 'success');
      } catch (err) { toast(err.message || 'Clear failed', 'error'); }
      els.mirrorEventsClear.disabled = false;
      refreshStatus();
    });
  }

  function renderBackupRow(dd, b) {
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!b || !b.enabled) {
      dd.append(statusPart('off', 'not configured'), ' — ' + ((b && b.reason) || 'unknown'));
      return;
    }
    dd.append(
      statusPart(b.last_error ? 'warn' : 'ok', b.last_error ? 'error' : 'enabled'),
      ' · ', codeEl(b.dir), ' · last ' + (b.last_file || '–'), ' · next ' + (b.next_run ? fmtTsShort(b.next_run) : '–')
    );
    if (b.last_error) dd.append(' · ' + b.last_error);
  }

  // --------------------------------------------- folder opener + index card
  function renderOpener(op) {
    const dd = els.statusOpener;
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!op) { dd.append(statusPart('warn', 'unknown')); return; }
    if (op.installed_here === true) dd.append(statusPart('ok', 'installed on the server PC'));
    else if (op.installed_here === false) dd.append(statusPart('off', 'not installed on the server PC'));
    else dd.append(statusPart('warn', 'unknown on this OS'));
    // Which registration shape is in use is its own state: the fallback hands the
    // URL to a command interpreter as a string, so it must not read as "installed".
    if (op.mode === 'launcher') dd.append(' · ', statusPart('ok', 'launcher mode'));
    else if (op.mode === 'fallback') dd.append(' · ', statusPart('warn', 'fallback mode — re-run the command below; see opener/README.md'));
    dd.append(' · other PCs: paste the command below once (this browser asks "Open task-os opener?" the first time)');
    const cmd = (op.install || '').split(op.base_url_token || '<base-url>').join(location.origin);
    els.openerInstall.textContent = cmd || 'install.txt missing';
    els.openerUninstall.textContent = op.uninstall || '';
    els.openerEnv.textContent = op.env_template || '';
    els.openerCopy.onclick = function () { copyText(cmd, els.openerCopy); };
    els.openerEnvCopy.onclick = function () { copyText(op.env_template || '', els.openerEnvCopy); };
  }

  function renderIndexRow(dd, f) {
    dd.replaceChildren();
    dd.classList.remove('muted');
    if (!f || !f.enabled) {
      dd.append(statusPart('off', 'not configured'), ' — ' + ((f && f.reason) || 'unknown'));
      els.reindexBtn.hidden = true;
      return;
    }
    els.reindexBtn.hidden = false;
    const roots = (f.roots || []).map(function (r) { return r.ref + (r.exists ? '' : ' (missing)'); }).join(', ');
    dd.append(
      statusPart(f.indexing ? 'warn' : (f.last_error ? 'warn' : 'ok'), f.indexing ? 'indexing…' : (f.last_error ? 'error' : 'indexed')),
      ' · ', codeEl(roots), ' · ' + (f.entries == null ? '?' : f.entries) + ' folder(s)',
      ' · last indexed ' + (f.last_indexed ? fmtTsShort(f.last_indexed) : '–') + (f.stale && f.last_indexed ? ' (stale, >24 h)' : '')
    );
    if (f.last_error) dd.append(' · ' + f.last_error);
  }

  function wireReindex() {
    if (!els.reindexBtn) return;
    els.reindexBtn.addEventListener('click', async function () {
      els.reindexBtn.disabled = true;
      try {
        const r = await api('/api/folders/reindex', { method: 'POST', body: {} });
        toast('Folder index: ' + r.entries + ' folder(s) in ' + r.seconds + ' s', 'success');
      } catch (err) { toast(err.message || 'Reindex failed', 'error'); }
      els.reindexBtn.disabled = false;
      refreshStatus();
    });
  }

  // One GET /api/status feeds the Settings pane's Phone access card (https +
  // auth, Step 7), the mirror / backup card (Step 6) and the opener card (Step 9).
  // The card headers carry a state word (on · synced · indexed · off), never a count.
  async function refreshStatus() {
    if (!els.statusMirror) return;
    try {
      const body = await api('/api/status');
      renderAccessCard(body);
      renderMirrorRow(els.statusMirror, body.mirror);
      renderBackupRow(els.statusBackup, body.backup);
      renderMirrorEventsRow(body.mirror).catch(function () {});
      const on = [body.mirror && body.mirror.enabled, body.backup && body.backup.enabled].filter(Boolean).length;
      els.mirrorCardMeta.textContent = on === 2 ? 'both on' : on === 1 ? 'one of two on' : 'off';
      if (els.folderCard) {
        renderOpener(body.opener);
        renderIndexRow(els.statusIndex, body.folders);
        const f = body.folders;
        els.folderCardMeta.textContent = f && f.enabled ? (f.indexing ? 'indexing' : (f.last_error ? 'error' : 'indexed')) : 'index off';
      }
    } catch (err) {
      // An unreachable status is its own visible state, never a stale "Loading…".
      renderAccessUnknown(err.message);
      els.statusMirror.textContent = 'unknown — ' + err.message;
      els.statusBackup.textContent = 'unknown — ' + err.message;
      els.statusMirrorEvents.textContent = 'unknown — ' + err.message;
      els.mirrorCardMeta.textContent = 'unknown';
      if (els.statusOpener) { els.statusOpener.textContent = 'unknown — ' + err.message; els.statusIndex.textContent = 'unknown — ' + err.message; }
    }
  }

  // ------------------------------------------------------------ issue sync
  /** The Settings card's half of the issue-provider status; the header ↻ and
   *  the sync call itself stay with the bootstrap (they are not this tab's). */
  function renderIssues(st) {
    const configured = !!(st && st.enabled);
    if (els.issuesSyncNow) els.issuesSyncNow.disabled = !configured;
    if (!els.statusIssues) return;
    els.statusIssues.replaceChildren();
    els.statusIssuesSync.replaceChildren();
    els.statusIssues.classList.remove('muted');
    els.statusIssuesSync.classList.remove('muted');
    if (!st) {
      els.statusIssues.textContent = 'unknown';
      els.statusIssuesSync.textContent = '–';
      els.issuesCardMeta.textContent = 'unknown';
      return;
    }
    if (!configured) {
      els.statusIssues.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
      els.statusIssuesSync.textContent = '–';
      els.issuesCardMeta.textContent = 'off';
      return;
    }
    els.statusIssues.append(
      statusPart(st.last_error ? 'warn' : 'ok', st.last_error ? 'error' : 'enabled'),
      ' · ', codeEl(st.provider), ' · every ' + st.sync_minutes + ' min',
      st.next_run ? ' · next ' + fmtTsShort(st.next_run) : ''
    );
    if (st.last_error) els.statusIssues.append(' · ' + (st.last_error_code ? st.last_error_code + ': ' : '') + st.last_error);
    const r = st.last_result;
    if (!st.last_sync) {
      els.statusIssuesSync.textContent = 'not yet';
    } else {
      els.statusIssuesSync.append(fmtTsShort(st.last_sync));
      if (r) {
        els.statusIssuesSync.append(' · ' + r.listed + ' open issue(s) · ' + r.created + ' new · ' + r.retitled + ' retitled · ' + r.reopened + ' reopened · ' + r.closed + ' closed' + (r.errors && r.errors.length ? ' · ' + r.errors.length + ' error(s)' : ''));
      }
    }
    if (st.repos && st.repos.length) els.statusIssuesSync.append(' · repos: ' + st.repos.join(', '));
    els.issuesCardMeta.textContent = st.last_error ? 'error' : (st.last_sync ? 'synced' : 'on');
  }

  function wireIssueSyncNow() {
    if (els.issuesSyncNow) els.issuesSyncNow.addEventListener('click', function () { opts.onSyncIssues().catch(function () {}); });
  }

  // ---------------------------------------------------------- search card
  /** Which indexes this install can query (GET /api/search/status). */
  async function refreshSearchStatus() {
    if (!els.searchCard) return;
    let adapters = null;
    try { adapters = (await api('/api/search/status')).adapters || []; } catch (err) { adapters = null; }
    let on = 0;
    Object.keys(SEARCH_KIND_ROWS).forEach(function (kind) {
      const dd = document.getElementById(SEARCH_KIND_ROWS[kind]);
      if (!dd) return;
      dd.replaceChildren();
      dd.classList.remove('muted');
      const a = adapters && adapters.find(function (x) { return x.kind === kind; });
      if (!adapters) { dd.append(statusPart('warn', 'unknown')); return; }
      if (a && a.configured) {
        on += 1;
        dd.append(statusPart('ok', 'indexed'));
        if (a.note) dd.append(' · ' + a.note);
      } else {
        dd.append(statusPart('off', 'not configured'), ' — ' + ((a && a.reason) || 'unknown'));
      }
    });
    els.searchCardMeta.textContent = adapters ? (on ? 'indexed' : 'off') : 'unknown';
    opts.onSearchStatus();
  }

  // ------------------------------------------------------------ deep links
  /** `#settings/opener` / `#settings/search`: open that card and scroll to it.
   *  The tab switch and the URL are the bootstrap's (routing lives there). */
  function revealCard(key) {
    const card = DEEP_LINK_CARDS[key];
    if (!card) return;
    if ('open' in card) card.open = true;
    card.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  wireSignOut();
  wireReindex();
  wireMirrorEventsClear();
  wireIssueSyncNow();

  return {
    refreshStatus: refreshStatus,
    refreshSearchStatus: refreshSearchStatus,
    renderIssues: renderIssues,
    revealCard: revealCard,
  };
}

// ------------------------------------------------------------------ bits
function statusPart(state, text) {
  const s = document.createElement('span');
  s.className = 'status-' + state;
  s.textContent = text;
  return s;
}

function codeEl(text) {
  const c = document.createElement('code');
  c.textContent = text;
  return c;
}
