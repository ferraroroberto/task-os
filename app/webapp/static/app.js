/* task-os — app bootstrap and the one place state lives.
 *
 * Nav + theme (Step 1), then the Step 4 surfaces: Table (filters ↔ URL
 * query), Tree, the task drawer (↔ #task/<id>) and the quick-add bars.
 * Every write funnels through `patchTask` / `moveTask` / the drawer, then
 * `refreshAll()` re-fetches and re-renders, so the three views never drift.
 *
 * ES module; the vendored components are imported by their static paths so
 * the server's fleet-hash stamping rewrites them (`?v=<hash>`) at serve time.
 */

'use strict';

import { initNavTabs } from './_vendored/nav/nav-tabs.js';
import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { buildReadoutText } from './_vendored/page-foot/page-foot.js';
import { api, qs } from './api.js';
import { createDrawer } from './drawer.js';
import { mountQuickAdd } from './quickadd.js';
import {
  DEFAULT_FILTERS, filtersFromSearch, filtersToSearch, isDefaultFilters, renderFilterBar,
  renderTable as renderTableGrid, sortItems,
} from './table.js';
import { toast } from './toast.js';
import { renderTree } from './tree.js';

const THEME_KEY = 'task-os.theme';
const TAB_KEY = 'task-os.tab';

const els = {
  themeToggle: document.getElementById('themeToggle'),
  buildReadout: document.getElementById('buildReadout'),
  homeHeadStatus: document.getElementById('homeHeadStatus'),
  settingsSite: document.getElementById('settingsSite'),
  mirrorCardMeta: document.getElementById('mirrorCardMeta'),
  statusMirror: document.getElementById('statusMirror'),
  statusBackup: document.getElementById('statusBackup'),
  tableFilters: document.getElementById('tableFilters'),
  tableHost: document.getElementById('tableHost'),
  treeHost: document.getElementById('treeHost'),
  drawer: document.getElementById('taskDrawer'),
};

const state = {
  filters: filtersFromSearch(location.search),
  people: [],
  projects: [],     // [{id, title, depth}] — every task with children, tree order
  tree: [],
  items: [],
  total: null,      // null = unknown (not yet read), 0 = truly empty
  tab: 'board',
};

let nav = null;
let drawer = null;
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
}

function renderLaterSteps() {
  // Panes whose views arrive with later steps show what they are, never a
  // misleading "add your first task" once tasks exist.
  const later = { paneBoard: ['square-kanban', 'Board view arrives with the next step — use Table or Tree'],
    paneToday: ['calendar-days', 'Today view arrives with the next step'],
    paneSearch: ['search', 'Federated search arrives with a later step'] };
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
    const results = await Promise.all([loadTree(), loadTable(), api('/api/tasks?include_closed=true&limit=1')]);
    state.total = results[2].count;
    if (state.total === 0) {
      state.items = [];
      state.tree = [];
      state.projects = [];
      renderNoTasks();
      els.homeHeadStatus.textContent = 'No tasks yet';
      return;
    }
    renderTable();
    renderTreePane();
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
function renderTable() {
  renderFilterBar(els.tableFilters, state.filters, {
    projects: state.projects, people: state.people, count: state.items.length,
  }, function (next) {
    state.filters = next;
    syncUrl();
    loadTable().then(renderTable).catch(function (err) { toast(err.message, 'error'); });
  });
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

async function fetchStatus() {
  if (!els.statusMirror) return;
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const body = await res.json();
    renderMirrorRow(els.statusMirror, body.mirror);
    renderBackupRow(els.statusBackup, body.backup);
    const on = [body.mirror && body.mirror.enabled, body.backup && body.backup.enabled].filter(Boolean).length;
    els.mirrorCardMeta.textContent = on === 2 ? 'both on' : on === 1 ? 'one of two on' : 'off';
  } catch (err) {
    // An unreachable status is its own visible state, never a stale "Loading…".
    els.statusMirror.textContent = 'unknown — ' + err.message;
    els.statusBackup.textContent = 'unknown — ' + err.message;
    els.mirrorCardMeta.textContent = 'unknown';
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
  // A shared Table view (?status=doing…) lands on the Table, whatever tab was last used.
  const wantsTable = !isDefaultFilters(state.filters);
  nav = initNavTabs({ storageKey: TAB_KEY, onChange: function (tab) {
    state.tab = tab;
    if (tab === 'settings') fetchStatus();
  } });
  if (wantsTable) nav.setTab('table');
  mountQuickAdds();
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && drawer.currentId() != null && !ev.target.closest('input, textarea, select')) closeTask();
  });
  window.addEventListener('hashchange', onHashChange);
  window.addEventListener('popstate', onHashChange);
  fetchVersion();
  await loadPeople();
  await refreshAll();
  onHashChange();
}

boot();
