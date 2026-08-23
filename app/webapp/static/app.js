/* task-os — app bootstrap and the one place state lives.
 *
 * Nav + theme (Step 1); the views — Board, Table, Tree, Today — are
 * renderings of ONE shared list (`state.items`, /api/tasks under the shared
 * filter state) drawn with the ONE task row (rows.js) and edited through the
 * ONE filter card (filters.js) that every tab mounts (issue #46): status ·
 * project · person · due · modified · text · sort, all in the URL query so a
 * view is shareable and the same on every tab. The task drawer (↔ #task/<id>)
 * and the quick-add bars; the issue sync (↻ in the header + Settings card,
 * `syncIssues()` → POST /api/issues/sync → refreshAll); the Search tab
 * (search.js — one box over tasks · folders · emails · issues, `?q=` in the
 * URL while that tab is active, the shared filters applied to task hits) and
 * the command palette (palette.js — Ctrl+K / ⌘K anywhere; commands in
 * `paletteCommands()` below). Every write funnels through `patchTask` /
 * `moveTask` / the drawer, then `refreshAll()` re-fetches and re-renders, so
 * the views never drift.
 *
 * Every tab is its own module and this file is the wiring: board.js ·
 * table.js · tree.js · today.js · search.js · settings.js (issue #37 — the
 * Settings cards used to live here). What stays is what more than one tab
 * needs: routing (nav, the URL, #task/<id> and the two #settings/… deep
 * links), `state`, and the shared calls the drawer and the palette also make
 * — `syncIssues()` and the header ↻ among them.
 *
 * ES module; the vendored components are imported by their static paths so
 * the server's fleet-hash stamping rewrites them (`?v=<hash>`) at serve time.
 */

'use strict';

import { initNavTabs } from './_vendored/nav/nav-tabs.js';
import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { buildReadoutText } from './_vendored/page-foot/page-foot.js';
import { api, qs } from './api.js';
import { mountBoard } from './board.js';
import { createDrawer } from './drawer.js';
import {
  DEFAULT_FILTERS, filtersFromSearch, filtersToSearch, isDefaultFilters, listParams, mountFilters,
} from './filters.js';
import { fmtTsShort, relDue, todayISO } from './format.js';
import { createPalette } from './palette.js';
import { mountQuickAdd } from './quickadd.js';
import { CLOSED, sortItems } from './rows.js';
import { mountSearch } from './search.js';
import { mountSettings } from './settings.js';
import { renderTable as renderTableGrid } from './table.js';
import { toast } from './toast.js';
import { renderToday } from './today.js';
import { renderTree } from './tree.js';

const THEME_KEY = 'task-os.theme';
const TAB_KEY = 'task-os.tab';
const PHONE_TABLE_MQ = '(max-width: 767px)';
// Deep links into the Settings pane: hash → the card settings.js opens.
const SETTINGS_HASH_CARDS = { '#settings/opener': 'opener', '#settings/search': 'search' };

const els = {
  themeToggle: document.getElementById('themeToggle'),
  buildReadout: document.getElementById('buildReadout'),
  homeHeadStatus: document.getElementById('homeHeadStatus'),
  settingsSite: document.getElementById('settingsSite'),
  issuesSync: document.getElementById('issuesSync'),
  searchBox: document.getElementById('searchBox'),
  searchHost: document.getElementById('searchHost'),
  paletteBtn: document.getElementById('paletteBtn'),
  palette: document.getElementById('palette'),
  boardFilters: document.getElementById('boardFilters'),
  boardHost: document.getElementById('boardHost'),
  tableFilters: document.getElementById('tableFilters'),
  tableHost: document.getElementById('tableHost'),
  treeFilters: document.getElementById('treeFilters'),
  treeHost: document.getElementById('treeHost'),
  todayFilters: document.getElementById('todayFilters'),
  todayHost: document.getElementById('todayHost'),
  searchFilters: document.getElementById('searchFilters'),
  drawer: document.getElementById('taskDrawer'),
};

const state = {
  filters: filtersFromSearch(location.search),
  people: [],
  projects: [],     // [{id, title, depth}] — every task with children, tree order
  tree: [],         // /api/tasks/tree?include_closed=true — the full forest
  items: [],        // /api/tasks under the shared filters (+ done today when no status is picked)
  total: null,      // null = unknown (not yet read), 0 = truly empty
  tab: 'board',
  issues: null,     // /api/issues/status → {provider, enabled, reason, last_sync, last_result, repos…}
};

let nav = null;
let drawer = null;
let board = null;
let search = null;
let settings = null;
let palette = null;
const quickAdds = [];
const filterCards = {};   // tab → mountFilters() handle

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
  ['boardFilters', 'tableFilters', 'treeFilters', 'todayFilters'].forEach(function (k) { if (els[k]) els[k].hidden = true; });
}

function noMatchCard(iconName, message) {
  return emptyCard(iconName, message, {
    actionLabel: isDefaultFilters(state.filters) ? undefined : 'Clear filters',
    onAction: function () { onFilterChange(Object.assign({}, DEFAULT_FILTERS)); },
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
  const res = await api('/api/tasks/tree?include_closed=true');
  state.tree = res.items || [];
  state.projects = flattenProjects(state.tree);
}

/** The shared list: the filters as sent to /api/tasks; when no status is
 *  picked, today's done tasks ride along (the Board's Done-today column). */
async function loadItems() {
  const f = state.filters;
  const params = listParams(f);
  const calls = [api('/api/tasks' + qs(params))];
  if (!f.status.length) {
    calls.push(api('/api/tasks' + qs(Object.assign({}, params, { status: ['done'], done_on: todayISO() }))));
  }
  const results = await Promise.all(calls);
  const seen = new Set();
  const items = [];
  results.forEach(function (r) {
    (r.items || []).forEach(function (t) { if (!seen.has(t.id)) { seen.add(t.id); items.push(t); } });
  });
  state.items = items;
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
      loadTree(), loadItems(), api('/api/tasks?include_closed=true&limit=1'),
    ]);
    state.total = results[2].count;
    if (state.total === 0) {
      state.items = [];
      state.tree = [];
      state.projects = [];
      renderNoTasks();
      els.homeHeadStatus.textContent = 'No tasks yet';
      return;
    }
    renderAll();
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

/** The row's status select. "complete" (recurring tasks only — see
 *  rows.js::statusOptions) goes through POST /tasks/{id}/done so the task
 *  rolls its due one cadence forward instead of closing; "done" (and every
 *  other status) is a plain PATCH — closed for good, recurring or not
 *  (issue #54). */
async function setStatus(id, status) {
  if (status !== 'complete') return patchTask(id, { status: status });
  let t;
  try {
    t = await api('/api/tasks/' + id + '/done', { method: 'POST', body: {} });
  } catch (err) {
    toast(err.message || 'Could not complete the task', 'error');
    throw err;
  }
  toast('Done — next: ' + t.due + ' (' + relDue(t.due).text + ')', 'success');
  await refreshAll();
  if (drawer.currentId() === id) drawer.refresh();
  return t;
}

/** What the list views show: the filtered list — minus the closed tasks that
 *  ride along for the Board's "Done today" column when no status pill is
 *  pressed (Table / Tree / Today default to open tasks, as the filter card says). */
function viewItems() {
  if (state.filters.status.length) return state.items;
  return state.items.filter(function (t) { return !CLOSED[t.status]; });
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
/** The one filter state changed (any tab's card, the palette, a "Clear"). */
function onFilterChange(next) {
  state.filters = next;
  syncUrl();
  loadItems().then(function () {
    renderAll();
  }).catch(function (err) { toast(err.message, 'error'); });
}

function renderFilters() {
  const options = { projects: state.projects, people: state.people, count: viewItems().length };
  [['board', els.boardFilters], ['table', els.tableFilters], ['tree', els.treeFilters], ['today', els.todayFilters], ['search', els.searchFilters]]
    .forEach(function (pair) {
      const host = pair[1];
      if (!host) return;
      if (!filterCards[pair[0]]) {
        filterCards[pair[0]] = mountFilters(host, { onChange: onFilterChange, hideText: pair[0] === 'search' });
      }
      filterCards[pair[0]].render(state.filters, pair[0] === 'search' ? { projects: state.projects, people: state.people } : options);
    });
}

function renderAll() {
  renderFilters();
  renderBoardPane();
  renderTable();
  renderTreePane();
  renderTodayPane();
  if (search) search.refilter();
}

function renderBoardPane() {
  if (!board) board = mountBoard({ onOpen: openTask, onStatus: setStatus });
  if (!els.boardHost.contains(board.el)) els.boardHost.replaceChildren(board.el);
  board.render(state.items, state.filters);
}

function renderTodayPane() {
  renderToday(els.todayHost, viewItems(), { onOpen: openTask, onStatus: setStatus }, { sort: state.filters.sort });
}

function renderTable() {
  const items = viewItems();
  if (!items.length) {
    els.tableHost.replaceChildren(noMatchCard('list-filter', 'No tasks match these filters'));
    return;
  }
  const phone = window.matchMedia(PHONE_TABLE_MQ).matches;
  renderTableGrid(els.tableHost, sortItems(items, state.filters.sort), { onOpen: openTask, onPatch: patchTask, onStatus: setStatus }, { phone: phone });
}

function renderTreePane() {
  const items = viewItems();
  const keep = new Set(items.map(function (t) { return t.id; }));
  const byId = {};
  items.forEach(function (t) { byId[t.id] = t; });
  const n = renderTree(els.treeHost, state.tree, { onOpen: openTask, onMove: moveTask, onStatus: setStatus },
    { keep: keep, byId: byId, sort: state.filters.sort });
  if (!n) els.treeHost.replaceChildren(noMatchCard('list-tree', 'No tasks match these filters'));
}

// ---------------------------------------------------------- URL / drawer
function syncUrl() {
  if (nav && nav.getTab() === 'search') return;    // the Search box owns ?q= there
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
  const settingsCard = SETTINGS_HASH_CARDS[location.hash];
  if (settingsCard) {
    // The folder chip's one-time hint / a "not configured" search row link
    // here: Settings → that card, opened (settings.js owns the pane's DOM).
    nav.setTab('settings');
    history.replaceState(null, '', location.pathname + location.search);
    settings.revealCard(settingsCard);
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
  const hosts = { table: els.tableHost, tree: els.treeHost, board: els.boardHost, today: els.todayHost };
  let host = hosts[tab];
  if (!host) { nav.setTab('table'); host = els.tableHost; }
  const target = host.querySelector('.trow[data-id="' + task.id + '"] .trow-main, .task-row[data-id="' + task.id + '"]');
  if (target) {
    target.tabIndex = 0;
    target.focus({ preventScroll: false });
    (target.closest('.trow') || target).classList.add('is-new');
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

// ------------------------------------------------------------ issue sync
// The provider status is shared state: the header ↻ lives here, the Settings
// card renders it (settings.js), the drawer and the palette read `state.issues`.
function renderIssuesSync() {
  const st = state.issues;
  const configured = !!(st && st.enabled);
  if (els.issuesSync) {
    els.issuesSync.hidden = !configured;
    els.issuesSync.title = configured
      ? 'Sync issues now (' + st.provider + (st.last_sync ? ' · last ' + fmtTsShort(st.last_sync) : '') + ')'
      : 'Issue provider not configured';
  }
}

async function fetchIssuesStatus() {
  try {
    state.issues = await api('/api/issues/status');
  } catch (err) {
    state.issues = null;
  }
  renderIssuesSync();
  settings.renderIssues(state.issues);
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
}

// ---------------------------------------------------- search + palette
/** Write the Search tab's query into ?q= (only while that tab is showing — the
 *  filter card's text owns ?q= on the other tabs). */
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
  ['inbox', 'todo', 'doing', 'standby', 'done', 'cancelled'].forEach(function (st) {
    cmds.push({ id: 'filter-' + st, label: 'Filter: status ' + st, hint: 'every view', icon: 'list-filter', run: function () {
      onFilterChange(Object.assign({}, state.filters, { status: [st] }));
    } });
  });
  cmds.push({ id: 'filter-clear', label: 'Filter: clear', hint: 'back to open tasks', icon: 'list-filter', run: function () {
    onFilterChange(Object.assign({}, DEFAULT_FILTERS));
  } });
  cmds.push({ id: 'sync-issues', label: 'Sync issues', hint: state.issues && state.issues.enabled ? 'one pass now (' + state.issues.provider + ')' : 'issue provider not configured', icon: 'refresh-cw', run: function () { return syncIssues(); } });
  cmds.push({ id: 'reindex-folders', label: 'Reindex folders', hint: 'rescan search.folder_roots', icon: 'folder', run: async function () {
    try { const r = await api('/api/folders/reindex', { method: 'POST', body: {} }); toast('Folder index: ' + r.entries + ' folder(s) in ' + r.seconds + ' s', 'success'); settings.refreshStatus(); }
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
    onStatus: setStatus,
    issues: function () { return state.issues; },
    onSyncIssues: syncIssues,
    onToggle: function () { if (search) search.refreshActions(); },
  });
  // The Settings pane owns its own cards (settings.js); mounted before the nav
  // because restoring the stored tab can fire onChange straight into it.
  settings = mountSettings({
    onSyncIssues: syncIssues,
    onSearchStatus: function () { if (search) search.reloadStatus(); },
  });
  // The filters are shared by every tab, so a shared URL never moves the tab
  // by itself. First visit: the phone lands on Today, the desktop on the Board.
  const f = state.filters;
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  // ?q= belongs to the Search tab when the page lands there (#search deep
  // link, or the last tab was Search); otherwise it is the filter card's text.
  let storedTab = null;
  try { storedTab = localStorage.getItem(TAB_KEY); } catch (_) { /* private mode */ }
  const wantsSearch = location.hash === '#search' || (f.q !== '' && storedTab === 'search');
  let searchQ = '';
  if (wantsSearch) { searchQ = f.q; state.filters = Object.assign({}, f, { q: '' }); }
  nav = initNavTabs({
    storageKey: TAB_KEY,
    defaultTab: coarse ? 'today' : 'board',
    onChange: function (tab) {
      state.tab = tab;
      if (tab === 'board' && board) board.show();
      if (tab === 'settings') { settings.refreshStatus(); fetchIssuesStatus(); settings.refreshSearchStatus(); }
      if (tab === 'search' && search) { syncSearchUrl(search.getQuery()); if (!coarse) search.focus(); }
      else syncUrl();
    },
  });
  if (wantsSearch) { nav.setTab('search'); if (location.hash === '#search') history.replaceState(null, '', location.pathname + location.search); }
  mountQuickAdds();
  search = mountSearch(els.searchBox, els.searchHost, {
    onOpenTask: openTask,
    currentTaskId: function () { return drawer.currentId(); },
    onTaskChanged: function (id) { refreshAll(); if (drawer.currentId() === id) drawer.refresh(); },
    onCreated: function (task) { refreshAll().then(function () { openTask(task.id); }); },
    onQuery: syncSearchUrl,
    filters: function () { return state.filters; },
    onStatus: setStatus,
  });
  if (searchQ) search.setQuery(searchQ);
  wirePalette();
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && drawer.currentId() != null && !ev.target.closest('input, textarea, select')) closeTask();
  });
  window.addEventListener('hashchange', onHashChange);
  window.addEventListener('popstate', onHashChange);
  // The Table flips between the grid and the shared rows at the phone breakpoint.
  const phoneMq = window.matchMedia(PHONE_TABLE_MQ);
  if (phoneMq.addEventListener) phoneMq.addEventListener('change', function () { if (state.total) renderTable(); });
  wireIssueSync();
  fetchVersion();
  settings.refreshStatus();
  await loadPeople();
  await Promise.all([refreshAll(), fetchIssuesStatus()]);
  onHashChange();
}

boot();
