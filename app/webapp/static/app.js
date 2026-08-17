/* task-os — app bootstrap and the one place state lives.
 *
 * Nav + theme (Step 1), the Step 4 surfaces: Table (filters ↔ URL query),
 * Tree, the task drawer (↔ #task/<id>) and the quick-add bars; Step 5 adds
 * the Board (five status columns, the project/person/text filters shared
 * with the Table) and Today (due ≤ today grouped by project — the phone's
 * landing tab). Every write funnels through `patchTask` / `moveTask` /
 * `doneTask` / the drawer, then `refreshAll()` re-fetches and re-renders, so
 * the views never drift.
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
import { mountQuickAdd } from './quickadd.js';
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
};

let nav = null;
let drawer = null;
let board = null;
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

function renderLaterSteps() {
  // Panes whose views arrive with later steps show what they are, never a
  // misleading "add your first task" once tasks exist.
  const later = { paneSearch: ['search', 'Federated search arrives with a later step'] };
  Object.keys(later).forEach(function (id) {
    const host = document.querySelector('#' + id + ' [data-empty="tasks"]');
    if (host) host.replaceChildren(emptyCard(later[id][0], later[id][1]));
  });
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
    renderLaterSteps();
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
  if (location.hash === '#settings/opener') {
    // The folder chip's one-time hint links here: Settings → the Folder opener card.
    nav.setTab('settings');
    history.replaceState(null, '', location.pathname + location.search);
    if (els.folderCard) els.folderCard.scrollIntoView({ block: 'start', behavior: 'smooth' });
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

// ---------------------------------------------------------------- boot
async function boot() {
  wireTheme();
  drawer = createDrawer(els.drawer, {
    onChanged: refreshAll,
    onOpen: openTask,
    onClose: closeTask,
    people: function () { return state.people; },
  });
  // A shared Table view (?status=doing…) lands on the Table, whatever tab was
  // last used; project / person / q are shared with the Board and don't move
  // the tab. First visit: the phone lands on Today, the desktop on the Board.
  const f = state.filters;
  const wantsTable = f.status.length > 0 || f.due !== '' || f.sort !== 'due';
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  nav = initNavTabs({
    storageKey: TAB_KEY,
    defaultTab: coarse ? 'today' : 'board',
    onChange: function (tab) {
      state.tab = tab;
      if (tab === 'board' && board) board.show();
      if (tab === 'settings') fetchStatus();
    },
  });
  if (wantsTable) nav.setTab('table');
  mountQuickAdds();
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && drawer.currentId() != null && !ev.target.closest('input, textarea, select')) closeTask();
  });
  window.addEventListener('hashchange', onHashChange);
  window.addEventListener('popstate', onHashChange);
  fetchVersion();
  fetchStatus();
  wireSignOut();
  wireReindex();
  await loadPeople();
  await refreshAll();
  onHashChange();
}

boot();
