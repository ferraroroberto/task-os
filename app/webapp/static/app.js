/* task-os — app bootstrap and the one place state lives.
 *
 * Nav + theme (Step 1), the Step 4 surfaces: Table (filters ↔ URL query),
 * Tree, the task drawer (↔ #task/<id>) and the quick-add bars; Step 5 adds
 * the Board (five status columns, the project/person/text filters shared
 * with the Table) and Today (due ≤ today grouped by project — the phone's
 * landing tab); Step 8 adds the issue sync (↻ in the header + Settings card,
 * `syncIssues()` → POST /api/issues/sync → refreshAll); Step 10 the Search
 * tab (search.js — one box over tasks · folders · emails · issues, `?q=` in
 * the URL while that tab is active) and the command palette (palette.js —
 * Ctrl+K / ⌘K anywhere, the header button; commands defined in
 * `paletteCommands()` below). Every write funnels
 * through `patchTask` / `moveTask` / `doneTask` / the drawer, then
 * `refreshAll()` re-fetches and re-renders, so the views never drift.
 *
 * ES module; the vendored components are imported by their static paths so
 * the server's fleet-hash stamping rewrites them (`?v=<hash>`) at serve time.
 */

'use strict';

import { initNavTabs } from './_vendored/nav/nav-tabs.js';
import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { buildReadoutText } from './_vendored/page-foot/page-foot.js';
import { api, qs } from './api.js';
import { mountBoard, renderBoardFilters } from './board.js';
import { createDrawer } from './drawer.js';
import { copyText, relDue } from './format.js';
import { createPalette } from './palette.js';
import { mountQuickAdd } from './quickadd.js';
import { mountSearch } from './search.js';
import {
  DEFAULT_FILTERS, filtersFromSearch, filtersToSearch, isDefaultFilters, renderFilterBar,
  renderTable as renderTableGrid, sortItems,
} from './table.js';
import { toast } from './toast.js';
import { renderToday } from './today.js';
import { renderTree } from './tree.js';

const THEME_KEY = 'task-os.theme';
const TAB_KEY = 'task-os.tab';

const els = {
  themeToggle: document.getElementById('themeToggle'),
  buildReadout: document.getElementById('buildReadout'),
  homeHeadStatus: document.getElementById('homeHeadStatus'),
  settingsSite: document.getElementById('settingsSite'),
  accessClient: document.getElementById('accessClient'),
  accessRows: document.getElementById('accessRows'),
  signOutBtn: document.getElementById('signOutBtn'),
  mirrorCardMeta: document.getElementById('mirrorCardMeta'),
  statusMirror: document.getElementById('statusMirror'),
  statusBackup: document.getElementById('statusBackup'),
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
  issuesSync: document.getElementById('issuesSync'),
  issuesCardMeta: document.getElementById('issuesCardMeta'),
  statusIssues: document.getElementById('statusIssues'),
  statusIssuesSync: document.getElementById('statusIssuesSync'),
  issuesSyncNow: document.getElementById('issuesSyncNow'),
  searchBox: document.getElementById('searchBox'),
  searchHost: document.getElementById('searchHost'),
  searchCard: document.getElementById('searchCard'),
  searchCardMeta: document.getElementById('searchCardMeta'),
  paletteBtn: document.getElementById('paletteBtn'),
  palette: document.getElementById('palette'),
  boardFilters: document.getElementById('boardFilters'),
  boardHost: document.getElementById('boardHost'),
  tableFilters: document.getElementById('tableFilters'),
  tableHost: document.getElementById('tableHost'),
  treeHost: document.getElementById('treeHost'),
  todayHost: document.getElementById('todayHost'),
  drawer: document.getElementById('taskDrawer'),
};

const state = {
  filters: filtersFromSearch(location.search),
  people: [],
  projects: [],     // [{id, title, depth}] — every task with children, tree order
  tree: [],
  items: [],
  board: null,      // /api/board → {today, columns}
  today: null,      // /api/today → {today, due, week, counts}
  total: null,      // null = unknown (not yet read), 0 = truly empty
  tab: 'board',
  issues: null,     // /api/issues/status → {provider, enabled, reason, last_sync, last_result, repos…}
};

let nav = null;
let drawer = null;
let board = null;
let search = null;
let palette = null;
const quickAdds = [];

// ------------------------------------------------------------------ theme
function wireTheme() {
  els.themeToggle.addEventListener('click', function () {
    const dark = document.documentElement.dataset.theme !== 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    try { localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light'); } catch (_) { /* private mode */ }
  });
}

// ------------------------------------------------------------ empty states
function emptyCard(iconName, message, opts) {
  const card = document.createElement('div');
  card.className = 'card empty-card';
  card.appendChild(emptyStateEl(iconName, message, opts));
  return card;
}

function renderNoTasks() {
  document.querySelectorAll('[data-empty="tasks"]').forEach(function (host) {
    host.replaceChildren(emptyCard('list-checks', 'Add your first task', {
      actionLabel: 'Add a task',
      onAction: function () { if (quickAdds.length) quickAdds[0].focus(); },
    }));
  });
  els.tableFilters.hidden = true;
  els.boardFilters.hidden = true;
}

// ------------------------------------------------------------------ data
async function loadPeople() {
  try { state.people = (await api('/api/people')).items || []; } catch (_) { state.people = []; }
}

function flattenProjects(forest) {
  const out = [];
  (function walk(nodes) {
    nodes.forEach(function (n) {
      if (n.children && n.children.length) {
        out.push({ id: n.id, title: n.title, depth: n.depth || 0 });
        walk(n.children);
      }
    });
  })(forest);
  return out;
}

async function loadTree() {
  const res = await api('/api/tasks/tree');
  state.tree = res.items || [];
  state.projects = flattenProjects(state.tree);
}

async function loadTable() {
  const f = state.filters;
  const params = {
    status: f.status.length ? f.status : undefined,
    project: f.project || undefined,
    person: f.person || undefined,
    due: f.due || undefined,
    q: f.q || undefined,
  };
  const res = await api('/api/tasks' + qs(params));
  state.items = res.items || [];
}

async function loadBoard() {
  const f = state.filters;
  state.board = await api('/api/board' + qs({ project: f.project || undefined, person: f.person || undefined, q: f.q || undefined }));
}

async function loadToday() {
  state.today = await api('/api/today');
}

function countOpen(forest) {
  let n = 0;
  (function walk(nodes) {
    nodes.forEach(function (t) {
      if (t.status !== 'done' && t.status !== 'cancelled') n += 1;
      walk(t.children || []);
    });
  })(forest);
  return n;
}

async function refreshAll() {
  try {
    const results = await Promise.all([
      loadTree(), loadTable(), loadBoard(), loadToday(), api('/api/tasks?include_closed=true&limit=1'),
    ]);
    state.total = results[4].count;
    if (state.total === 0) {
      state.items = [];
      state.tree = [];
      state.projects = [];
      renderNoTasks();
      els.homeHeadStatus.textContent = 'No tasks yet';
      return;
    }
    renderBoardPane();
    renderTable();
    renderTreePane();
    renderTodayPane();
    els.homeHeadStatus.textContent = countOpen(state.tree) + ' open';
  } catch (err) {
    els.homeHeadStatus.textContent = 'Server unreachable';
    toast(err.message || 'Could not load tasks', 'error');
  }
}

// ---------------------------------------------------------------- writes
async function patchTask(id, changes) {
  try {
    await api('/api/tasks/' + id, { method: 'PATCH', body: changes });
  } catch (err) {
    toast(err.message || 'Update failed', 'error');
    throw err;
  }
  await refreshAll();
  if (drawer.currentId() === id) drawer.refresh();
}

async function doneTask(id) {
  let t;
  try {
    t = await api('/api/tasks/' + id + '/done', { method: 'POST', body: {} });
  } catch (err) {
    toast(err.message || 'Could not complete the task', 'error');
    throw err;
  }
  if (t.recurrence) toast('Done — next: ' + t.due + ' (' + relDue(t.due).text + ')', 'success');
  else toast('Done: ' + t.title, 'success');
  await refreshAll();
  if (drawer.currentId() === id) drawer.refresh();
}

async function moveTask(id, parentId) {
  try {
    const t = await api('/api/tasks/' + id + '/move', { method: 'POST', body: { parent_id: parentId } });
    toast('Moved "' + t.title + '" ' + (parentId == null ? 'to the top level' : 'under ' + (t.breadcrumb.length ? t.breadcrumb[t.breadcrumb.length - 1].title : '#' + parentId)), 'success');
  } catch (err) {
    toast(err.message || 'Move failed', 'error');
    return;
  }
  await refreshAll();
  if (drawer.currentId() === id) drawer.refresh();
}

// --------------------------------------------------------------- render
function onSharedFilterChange(next) {
  // project · person · q are shared by the Board and the Table; a change on
  // either tab re-fetches both so the URL, the cards and the rows agree.
  state.filters = next;
  syncUrl();
  Promise.all([loadBoard(), loadTable()]).then(function () {
    renderBoardPane();
    renderTable();
  }).catch(function (err) { toast(err.message, 'error'); });
}

function renderBoardPane() {
  if (!board) board = mountBoard({ onOpen: openTask, onStatus: function (id, status) { return patchTask(id, { status: status }); } });
  if (!els.boardHost.contains(board.el)) els.boardHost.replaceChildren(board.el);
  const cols = (state.board && state.board.columns) || {};
  const count = Object.keys(cols).reduce(function (n, k) { return n + cols[k].length; }, 0);
  renderBoardFilters(els.boardFilters, state.filters, {
    projects: state.projects, people: state.people, count: count,
  }, onSharedFilterChange);
  board.render(state.board);
}

function renderTodayPane() {
  renderToday(els.todayHost, state.today || {}, { onOpen: openTask, onDone: doneTask });
}

function renderTable() {
  renderFilterBar(els.tableFilters, state.filters, {
    projects: state.projects, people: state.people, count: state.items.length,
  }, onSharedFilterChange);
  if (!state.items.length) {
    els.tableHost.replaceChildren(emptyCard('list-filter', 'No tasks match these filters', {
      actionLabel: isDefaultFilters(state.filters) ? undefined : 'Clear filters',
      onAction: function () {
        state.filters = Object.assign({}, DEFAULT_FILTERS);
        syncUrl();
        loadTable().then(renderTable);
      },
    }));
    return;
  }
  renderTableGrid(els.tableHost, sortItems(state.items, state.filters.sort), { onOpen: openTask, onPatch: patchTask });
}

function renderTreePane() {
  if (!state.tree.length) {
    els.treeHost.replaceChildren(emptyCard('list-tree', 'No open tasks'));
    return;
  }
  renderTree(els.treeHost, state.tree, { onOpen: openTask, onMove: moveTask });
}

// ---------------------------------------------------------- URL / drawer
function syncUrl() {
  const search = filtersToSearch(state.filters);
  history.replaceState(null, '', location.pathname + search + location.hash);
}

function hashTaskId() {
  const m = /^#task\/(\d+)$/.exec(location.hash || '');
  return m ? Number(m[1]) : null;
}

function openTask(id) {
  if (hashTaskId() !== id) {
    history.pushState(null, '', location.pathname + location.search + '#task/' + id);
  }
  drawer.open(id);
}

function closeTask() {
  drawer.close();
  if (hashTaskId() != null) history.replaceState(null, '', location.pathname + location.search);
}

function onHashChange() {
  const settingsCard = { '#settings/opener': els.folderCard, '#settings/search': els.searchCard }[location.hash];
  if (settingsCard !== undefined) {
    // The folder chip's one-time hint / a "not configured" search row link
    // here: Settings → that card.
    nav.setTab('settings');
    history.replaceState(null, '', location.pathname + location.search);
    if (settingsCard) settingsCard.scrollIntoView({ block: 'start', behavior: 'smooth' });
    return;
  }
  if (location.hash === '#search') {
    // Deep link to the Search tab (?q= carries the query — see boot()).
    nav.setTab('search');
    history.replaceState(null, '', location.pathname + location.search);
    return;
  }
  const id = hashTaskId();
  if (id == null) { if (drawer.currentId() != null) drawer.close(); return; }
  if (drawer.currentId() !== id) drawer.open(id);
}

// ------------------------------------------------------------ quick-add
function focusRow(task) {
  // The new row in whichever surface is showing; the drawer stays closed so
  // the eye lands on the row, not a panel.
  const tab = nav.getTab();
  let target = null;
  if (tab === 'table') target = els.tableHost.querySelector('.task-row[data-id="' + task.id + '"]');
  else if (tab === 'tree') target = els.treeHost.querySelector('.tree-node[data-id="' + task.id + '"]');
  else if (tab === 'board') target = els.boardHost.querySelector('.board-item[data-id="' + task.id + '"] .board-card');
  else if (tab === 'today') target = els.todayHost.querySelector('.today-row[data-id="' + task.id + '"]');  // only if due ≤ today; the toast already confirmed
  else { nav.setTab('table'); target = els.tableHost.querySelector('.task-row[data-id="' + task.id + '"]'); }
  if (target) {
    target.tabIndex = 0;
    target.focus({ preventScroll: false });
    target.classList.add('is-new');
    target.scrollIntoView({ block: 'nearest' });
  }
}

function mountQuickAdds() {
  document.querySelectorAll('.quick-add').forEach(function (host) {
    quickAdds.push(mountQuickAdd(host, {
      onCreated: function (task) { refreshAll().then(function () { focusRow(task); }); },
    }));
  });
}

// ---------------------------------------------------------- build identity
async function fetchVersion() {
  try {
    const res = await fetch('/api/version', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const body = await res.json();
    els.buildReadout.textContent = buildReadoutText(body.git_sha || 'unknown', body.built_at || '');
    if (els.settingsSite && body.schema_version != null) {
      els.settingsSite.textContent = 'schema v' + body.schema_version;
    }
  } catch (err) {
    // An unreachable version endpoint is its own visible state, never blank.
    els.buildReadout.textContent = 'Build: unknown';
    els.homeHeadStatus.textContent = 'Server unreachable';
  }
}

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

// ------------------------------------------------- mirror + backup status
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

function fmtTsShort(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

// ---------------------------------------------- folder opener + index card
function renderOpener(op) {
  const dd = els.statusOpener;
  dd.replaceChildren();
  dd.classList.remove('muted');
  if (!op) { dd.append(statusPart('warn', 'unknown')); return; }
  if (op.installed_here === true) dd.append(statusPart('ok', 'installed on the server PC'));
  else if (op.installed_here === false) dd.append(statusPart('off', 'not installed on the server PC'));
  else dd.append(statusPart('warn', 'unknown on this OS'));
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
    statusPart(f.indexing ? 'warn' : (f.last_error ? 'warn' : 'ok'), f.indexing ? 'indexing…' : (f.last_error ? 'error' : 'ready')),
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
    fetchStatus();
  });
}

// One GET /api/status feeds the Settings pane's Phone access card (https +
// auth, Step 7) and the mirror / backup card (Step 6).
async function fetchStatus() {
  if (!els.statusMirror) return;
  try {
    const body = await api('/api/status');
    renderAccessCard(body);
    renderMirrorRow(els.statusMirror, body.mirror);
    renderBackupRow(els.statusBackup, body.backup);
    const on = [body.mirror && body.mirror.enabled, body.backup && body.backup.enabled].filter(Boolean).length;
    els.mirrorCardMeta.textContent = on === 2 ? 'both on' : on === 1 ? 'one of two on' : 'off';
    if (els.folderCard) {
      renderOpener(body.opener);
      renderIndexRow(els.statusIndex, body.folders);
      els.folderCardMeta.textContent = body.folders && body.folders.enabled
        ? (body.folders.entries || 0) + ' folders indexed' : 'index off';
    }
  } catch (err) {
    // An unreachable status is its own visible state, never a stale "Loading…".
    renderAccessUnknown(err.message);
    els.statusMirror.textContent = 'unknown — ' + err.message;
    els.statusBackup.textContent = 'unknown — ' + err.message;
    els.mirrorCardMeta.textContent = 'unknown';
    if (els.statusOpener) { els.statusOpener.textContent = 'unknown — ' + err.message; els.statusIndex.textContent = 'unknown — ' + err.message; }
  }
}

// ------------------------------------------------------------ issue sync
function renderIssuesStatus() {
  const st = state.issues;
  const configured = !!(st && st.enabled);
  if (els.issuesSync) {
    els.issuesSync.hidden = !configured;
    els.issuesSync.title = configured
      ? 'Sync issues now (' + st.provider + (st.last_sync ? ' · last ' + fmtTsShort(st.last_sync) : '') + ')'
      : 'Issue provider not configured';
  }
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

async function fetchIssuesStatus() {
  try {
    state.issues = await api('/api/issues/status');
  } catch (err) {
    state.issues = null;
  }
  renderIssuesStatus();
}

let syncing = null;
/** One sync pass now; every ↻ in the app funnels here (header, Settings, drawer). */
async function syncIssues() {
  if (syncing) return syncing;
  syncing = (async function () {
    els.issuesSync.classList.add('is-busy');
    try {
      const r = await api('/api/issues/sync', { method: 'POST' });
      const bits = [];
      if (r.created) bits.push(r.created + ' new');
      if (r.retitled) bits.push(r.retitled + ' retitled');
      if (r.reopened) bits.push(r.reopened + ' reopened');
      if (r.closed) bits.push(r.closed + ' closed');
      if (r.errors && r.errors.length) bits.push(r.errors.length + ' error(s)');
      toast('Issues synced: ' + r.listed + ' open' + (bits.length ? ' · ' + bits.join(' · ') : ' · nothing changed'), r.errors && r.errors.length ? 'error' : 'success');
      await refreshAll();
      if (drawer.currentId() != null) drawer.refresh();
      return r;
    } catch (err) {
      toast('Issue sync failed: ' + (err.message || 'unknown'), 'error');
      throw err;
    } finally {
      els.issuesSync.classList.remove('is-busy');
      await fetchIssuesStatus();
      syncing = null;
    }
  })();
  return syncing;
}

function wireIssueSync() {
  if (els.issuesSync) els.issuesSync.addEventListener('click', function () { syncIssues().catch(function () {}); });
  if (els.issuesSyncNow) els.issuesSyncNow.addEventListener('click', function () { syncIssues().catch(function () {}); });
}

// ---------------------------------------------------- search + palette
const SEARCH_KIND_ROWS = { tasks: 'statusSearchTasks', folders: 'statusSearchFolders', emails: 'statusSearchEmails', issues: 'statusSearchIssues' };

/** Settings → Search card: which indexes this install can query (GET /api/search/status). */
async function fetchSearchStatus() {
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
      dd.append(statusPart('ok', 'ready'));
      if (a.note) dd.append(' · ' + a.note);
    } else {
      dd.append(statusPart('off', 'not configured'), ' — ' + ((a && a.reason) || 'unknown'));
    }
  });
  els.searchCardMeta.textContent = adapters ? on + ' of 4 indexes' : 'unknown';
  if (search) search.reloadStatus();
}

/** Write the Search tab's query into ?q= (only while that tab is showing — the
 *  Table's filter bar owns ?q= on the other tabs). */
function syncSearchUrl(q) {
  if (!nav || nav.getTab() !== 'search') return;
  const p = new URLSearchParams(location.search);
  if (q) p.set('q', q); else p.delete('q');
  const s = p.toString();
  history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + location.hash);
}

/** Emit the taskos:// opener link of the task open in the drawer (a click on
 *  the same chip the drawer carries, so the one-time opener hint applies). */
function openFolderOfCurrentTask() {
  const id = drawer.currentId();
  if (id == null) { toast('Open a task first', 'error'); return; }
  const chip = els.drawer.querySelector('.drawer-folder a.chip-folder');
  if (!chip) { toast('The open task has no folder', 'error'); return; }
  chip.click();
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

/** The palette's command list — built per open so hints reflect the moment. */
function paletteCommands() {
  const go = function (tab) { return function () { nav.setTab(tab); if (tab === 'search' && search) search.focus(); }; };
  const cmds = [
    { id: 'new-task', label: 'New task', hint: 'focus the quick-add bar', icon: 'plus', run: function () {
      if (['board', 'table', 'tree', 'today'].indexOf(nav.getTab()) < 0) nav.setTab('board');
      const hosts = Array.prototype.slice.call(document.querySelectorAll('.quick-add'));
      const host = document.querySelector('#pane' + cap(nav.getTab()) + ' .quick-add');
      const qa = quickAdds[hosts.indexOf(host)];
      if (qa) qa.focus();
    } },
    { id: 'go-board', label: 'Go to Board', icon: 'square-kanban', run: go('board') },
    { id: 'go-table', label: 'Go to Table', icon: 'table', run: go('table') },
    { id: 'go-tree', label: 'Go to Tree', icon: 'list-tree', run: go('tree') },
    { id: 'go-today', label: 'Go to Today', icon: 'calendar-days', run: go('today') },
    { id: 'go-search', label: 'Go to Search', icon: 'search', run: go('search') },
    { id: 'go-settings', label: 'Go to Settings', icon: 'settings', run: go('settings') },
  ];
  ['inbox', 'todo', 'doing', 'standby', 'done'].forEach(function (st) {
    cmds.push({ id: 'filter-' + st, label: 'Filter: status ' + st, hint: 'Table view', icon: 'list-filter', run: function () {
      nav.setTab('table');
      onSharedFilterChange(Object.assign({}, state.filters, { status: [st] }));
    } });
  });
  cmds.push({ id: 'filter-clear', label: 'Filter: clear', hint: 'back to open tasks', icon: 'list-filter', run: function () {
    onSharedFilterChange(Object.assign({}, DEFAULT_FILTERS));
  } });
  cmds.push({ id: 'sync-issues', label: 'Sync issues', hint: state.issues && state.issues.enabled ? 'one pass now (' + state.issues.provider + ')' : 'issue provider not configured', icon: 'refresh-cw', run: function () { return syncIssues(); } });
  cmds.push({ id: 'reindex-folders', label: 'Reindex folders', hint: 'rescan search.folder_roots', icon: 'folder', run: async function () {
    try { const r = await api('/api/folders/reindex', { method: 'POST', body: {} }); toast('Folder index: ' + r.entries + ' folder(s) in ' + r.seconds + ' s', 'success'); fetchStatus(); }
    catch (err) { toast(err.message || 'Reindex failed', 'error'); }
  } });
  cmds.push({ id: 'export-mirror', label: 'Export mirror', hint: 'every task to mirror.dir now', icon: 'copy', run: async function () {
    try { const r = await api('/api/mirror/export', { method: 'POST', body: {} }); toast('Mirror: ' + r.written + ' written, ' + r.removed + ' removed', 'success'); }
    catch (err) { toast(err.message || 'Export failed', 'error'); }
  } });
  cmds.push({ id: 'open-folder', label: 'Open folder of current task', hint: drawer.currentId() != null ? 'task #' + drawer.currentId() : 'no task open', icon: 'folder', run: openFolderOfCurrentTask });
  cmds.push({ id: 'toggle-theme', label: 'Toggle theme', hint: document.documentElement.dataset.theme === 'dark' ? 'to light' : 'to dark', icon: 'sun', run: function () { els.themeToggle.click(); } });
  cmds.push({ id: 'sign-out', label: 'Sign out', hint: 'this device (token cookie)', icon: 'x', run: async function () {
    try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { toast(err.message, 'error'); return; }
    location.assign('/login');
  } });
  return cmds;
}

function wirePalette() {
  palette = createPalette(els.palette, { commands: paletteCommands, onOpenTask: openTask });
  els.paletteBtn.addEventListener('click', function () { palette.toggle(); });
  document.addEventListener('keydown', function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      palette.toggle();
    }
  });
}

// ---------------------------------------------------------------- boot
async function boot() {
  wireTheme();
  drawer = createDrawer(els.drawer, {
    onChanged: refreshAll,
    onOpen: openTask,
    onClose: closeTask,
    people: function () { return state.people; },
    projects: function () { return state.projects; },
    onMove: moveTask,
    issues: function () { return state.issues; },
    onSyncIssues: syncIssues,
    onToggle: function () { if (search) search.refreshActions(); },
  });
  // A shared Table view (?status=doing…) lands on the Table, whatever tab was
  // last used; project / person / q are shared with the Board and don't move
  // the tab. First visit: the phone lands on Today, the desktop on the Board.
  const f = state.filters;
  const wantsTable = f.status.length > 0 || f.due !== '' || f.sort !== 'due';
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  // ?q= belongs to the Search tab when the page lands there (#search deep
  // link, or the last tab was Search); otherwise it is the Table's text filter.
  let storedTab = null;
  try { storedTab = localStorage.getItem(TAB_KEY); } catch (_) { /* private mode */ }
  const wantsSearch = location.hash === '#search' || (f.q !== '' && storedTab === 'search' && !wantsTable);
  let searchQ = '';
  if (wantsSearch) { searchQ = f.q; state.filters = Object.assign({}, f, { q: '' }); }
  nav = initNavTabs({
    storageKey: TAB_KEY,
    defaultTab: coarse ? 'today' : 'board',
    onChange: function (tab) {
      state.tab = tab;
      if (tab === 'board' && board) board.show();
      if (tab === 'settings') { fetchStatus(); fetchIssuesStatus(); fetchSearchStatus(); }
      if (tab === 'search' && search) { syncSearchUrl(search.getQuery()); if (!coarse) search.focus(); }
    },
  });
  if (wantsTable) nav.setTab('table');
  if (wantsSearch) { nav.setTab('search'); if (location.hash === '#search') history.replaceState(null, '', location.pathname + location.search); }
  mountQuickAdds();
  search = mountSearch(els.searchBox, els.searchHost, {
    onOpenTask: openTask,
    currentTaskId: function () { return drawer.currentId(); },
    onTaskChanged: function (id) { refreshAll(); if (drawer.currentId() === id) drawer.refresh(); },
    onCreated: function (task) { refreshAll().then(function () { openTask(task.id); }); },
    onQuery: syncSearchUrl,
  });
  if (searchQ) search.setQuery(searchQ);
  wirePalette();
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && drawer.currentId() != null && !ev.target.closest('input, textarea, select')) closeTask();
  });
  window.addEventListener('hashchange', onHashChange);
  window.addEventListener('popstate', onHashChange);
  wireIssueSync();
  fetchVersion();
  fetchStatus();
  wireSignOut();
  wireReindex();
  await loadPeople();
  await Promise.all([refreshAll(), fetchIssuesStatus()]);
  onHashChange();
}

boot();
