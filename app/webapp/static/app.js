/* task-os — app bootstrap and the one place state lives.
 *
 * Nav + theme (Step 1); the views — Today and Board — are
 * renderings of ONE shared list (`state.items`, /api/tasks under the shared
 * filter state) drawn with the ONE task row (rows.js) and edited through the
 * ONE filter state (filters.js) that every tab mounts — the
 * strip's text field and filter button, the sheet it opens: status ·
 * project · person · due · modified · text · sort, all in the URL query so a
 * view is shareable and the same on every tab. The task drawer (↔ #task/<id>)
 * and the quick-add bars; the issue sync (the Settings card's "Sync now",
 * `syncIssues()` → POST /api/issues/sync → refreshAll); the Search tab
 * (search.js — one box over tasks · folders · emails · issues, `?q=` in the
 * URL while that tab is active, the shared filters applied to task hits) and
 * the command palette (palette.js — Ctrl+K / ⌘K anywhere; commands in
 * js/app/commands.js). Every write funnels through `patchTask` /
 * `moveTask` / the drawer, then `refreshAll()` re-fetches and re-renders, so
 * the views never drift.
 *
 * Every tab is its own module and this file is the wiring: board.js ·
 * today.js · time.js (the time tracker — loads nothing until its tab
 * is first shown) · search.js · settings.js (the Settings cards: inset
 * groups and their sheets) · archive.js (the batch-archiving run and its
 * report, shown in the Settings → Email archiving sheet) · journal.js (the done journal —
 * `#journal`, a pane without a tab: reached from the palette and the Board's
 * Done column, left by pressing any tab). What stays is what more than one
 * tab needs: routing (nav, the URL, #task/<id>, #journal, #settings and its
 * #settings/<sheet> links), `state`, and the shared calls the drawer and the
 * palette also make — `syncIssues()` among them.
 *
 * This file is the composer: it builds the `app` its parts share (the
 * state, the elements, the mounted handles) and binds each part's exports
 * onto it. Each part lives in js/app/<part>.js and takes `app` as its first
 * argument: writes · journal · head · settings (the pane, not its cards) ·
 * issues · commands.
 *
 * ES module; the vendored components are imported by their static paths so
 * the server's fleet-hash stamping rewrites them (`?v=<hash>`) at serve time.
 */

'use strict';

import { initNavTabs } from './_vendored/nav/nav-tabs.js';
import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { initUsageLog } from './_vendored/usage-log/usage-log.js';
import { createActions } from './actions.js';
import { api, qs } from './api.js';
import { mountArchive } from './archive.js';
import { mountBoard } from './board.js';
import { mountBulkBar } from './bulkbar.js';
import { createDrawer } from './drawer.js';
import {
  WHOSE_KEY, filtersFromSearch, filtersToSearch, listParams, matchesScope, mountFilters,
  ownerOf, storedWhose,
} from './filters.js';
import { todayISO } from './format.js';
import { mountKeys } from './keys.js';
import { flattenOpen, parentTargets } from './parentpick.js';
import { createPalette } from './palette.js';
import { createQuickAdd } from './quickadd.js';
import { createTaskMenu } from './rowmenu.js';
import { CLOSED } from './rows.js';
import { mountScope, mountWhose } from './scope.js';
import { mountSearch } from './search.js';
import * as selection from './selection.js';
import { mountSettings } from './settings.js';
import { mountTime } from './time.js';
import { loadPhraseDates } from './snooze.js';
import { toast } from './toast.js';
import { renderToday } from './today.js';
import * as commands from './js/app/commands.js';
import * as head from './js/app/head.js';
import * as issues from './js/app/issues.js';
import * as journal from './js/app/journal.js';
import { JOURNAL_HASH } from './js/app/journal.js';
import * as settingsPane from './js/app/settings.js';
import { SETTINGS_HASH, SETTINGS_SHEET_HASH } from './js/app/settings.js';
import * as writes from './js/app/writes.js';

const THEME_KEY = 'task-os.theme';
const TAB_KEY = 'task-os.tab';
// What the Table tab (grid and Tree) remembered once. A
// stored `table` / `tree` tab needs nothing: the nav falls back to Today.
const RETIRED_KEYS = ['task-os.tableView', 'task-os.tree.collapsed'];
const JOURNAL_HIDES = ['status', 'due', 'updated', 'sort'];

const els = {
  themeToggle: document.getElementById('themeToggle'),
  settingsBtn: document.getElementById('settingsBtn'),
  paneSettings: document.getElementById('paneSettings'),
  buildReadout: document.getElementById('buildReadout'),
  homeHeadStatus: document.getElementById('homeHeadStatus'),
  homeTitleText: document.getElementById('homeTitleText'),
  homeTitleIcon: document.getElementById('homeTitleIcon'),
  settingsSite: document.getElementById('settingsSite'),
  searchBox: document.getElementById('searchBox'),
  searchHost: document.getElementById('searchHost'),
  palette: document.getElementById('palette'),
  quickAdd: document.getElementById('quickAdd'),
  boardFilterText: document.getElementById('boardFilterText'),
  boardBulk: document.getElementById('boardBulk'),
  todayBulk: document.getElementById('todayBulk'),
  boardHost: document.getElementById('boardHost'),
  boardBar: document.getElementById('boardBar'),
  boardScope: document.getElementById('boardScope'),
  boardWhose: document.getElementById('boardWhose'),
  todayFilterText: document.getElementById('todayFilterText'),
  todayScope: document.getElementById('todayScope'),
  todayWhose: document.getElementById('todayWhose'),
  todayHost: document.getElementById('todayHost'),
  searchScope: document.getElementById('searchScope'),
  paneJournal: document.getElementById('paneJournal'),
  journalFilterText: document.getElementById('journalFilterText'),
  journalHost: document.getElementById('journalHost'),
  drawer: document.getElementById('taskDrawer'),
  keysHelp: document.getElementById('keysHelp'),
};

const state = {
  filters: filtersFromSearch(location.search, storedWhose(safeStorage())),
  people: [],
  members: [],      // [{id, name}] — /api/me's people: the install's members, the owner first
  viewer: null,     // /api/me's id — who this request is; null = not established
  projects: [],     // [{id, title, depth, status}] — /api/projects: every task with children, closed ones too, tree order
  taskIndex: [],    // [{id, title, depth}] — every OPEN task, tree order (the blocker picker; a closed blocker gates nothing)
  tree: [],         // /api/tasks/tree?descriptions=false — the open forest (closed leaves pruned): the blocker picker
  items: [],        // /api/tasks under the shared filters (+ done today when no status is picked)
  calendar: null,   // /api/today's calendar group — the lane beside Today; null = not loaded
  total: null,      // null = unknown (not yet read), 0 = truly empty
  tab: 'today',
  todayCounts: null,  // Today's horizon counts as last drawn (today.js): the header's exceptions line
  boardCounts: null,  // …and the Board's (board.js): Inbox arrivals, overdue, due today
  headNote: null,     // a state that overrides every view's header line: 'No tasks yet' / 'Server unreachable'
  issues: null,     // /api/issues/status → {provider, enabled, reason, last_sync, last_result, repos…}
  ai: { enabled: false, reason: 'Checking local AI…' },
  // /api/status's `archive` block — the Email archiving sheet renders it
  // in full; the Settings header and the palette read the last run's "needs
  // you" count off it.
  // `null` = not established yet (or the status call failed), never "off".
  archive: null,
  aiSuggestions: {},  // task id → one pending staged suggestion
  triaging: false,
  // The done journal: its own list (closed tasks in a window of whole
  // weeks ending today, newest closing first), never merged into `items`.
  // `older` is null until the probe answered — unknown, not "no".
  journal: { open: false, weeks: 1, items: [], older: null, cancelled: true },
  settingsOpen: false,  // the Settings pane is up over the nav's tab
};

let nav = null;
let drawer = null;
// The drawer's own desktop breakpoint (styles/drawer.css): at and above it the drawer
// is a panel beside the list (Today's right half), below it a full-screen sheet.
const drawerBeside = window.matchMedia('(min-width: 1024px)');
// The task desktop Today opened by itself, until the user picks one.
let preselectedId = null;
let board = null;
let search = null;
let time = null;          // the Time tab: show() on its first press, hide() off it
let settings = null;
let archive = null;       // the Email archiving sheet — the batch run + its report
let palette = null;
let keys = null;          // the row keymap + undo; also feeds the palette
let actions = null;       // the one row-action runner + its undo (actions.js)
let menus = null;         // one ⋯ row menu per rendered list (rowmenu.js)
let quickAdd = null;      // the one quick-add dialog, opened by every pane's +
// The local usage log (vendored usage-log): which views and [data-track]
// controls are used, on which device class — posted to this app's own
// /api/usage/events, never anywhere else. Views: the three tabs, `settings`,
// `settings.<sheet>` and `journal`.
const usage = initUsageLog();
const scopes = {};        // tab → its Tasks · Issues · All switch (scope.js)
const whoses = {};        // tab → its Mine · Everyone switch (Today · Board only, two or more members)
const filterCards = {};   // tab → mountFilters() handle (the strip's filter button + the sheet)
const bulkBars = [];      // one per pane strip (Board · Today), all over one selection

// What the js/app/ parts share: the state, the looked-up elements, the
// handles boot() mounts (read through getters, so a part sees the live one)
// and the calls they make back into this file. Every function a part exports
// is bound onto it below, so `app.openJournal()` is the one way to reach it.
const app = {
  state: state,
  els: els,
  usage: usage,
  filterCards: filterCards,
  get nav() { return nav; },
  get drawer() { return drawer; },
  get search() { return search; },
  get time() { return time; },
  get settings() { return settings; },
  get archive() { return archive; },
  get keys() { return keys; },
  get actions() { return actions; },
  get menus() { return menus; },
  get quickAdd() { return quickAdd; },
  refreshAll: refreshAll,
  renderBoardPane: renderBoardPane,
  indexSuggestions: indexSuggestions,
  openTask: openTask,
  closeTask: closeTask,
  whoseOwner: whoseOwner,
  dropPreselected: dropPreselected,
  onFilterChange: onFilterChange,
};
[commands, head, issues, journal, settingsPane, writes].forEach(function (part) {
  Object.keys(part).forEach(function (name) {
    if (typeof part[name] === 'function') app[name] = part[name].bind(null, app);
  });
});

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
      onAction: function () { if (quickAdd) quickAdd.open(); },
    }));
  });
  ['boardFilterText', 'boardBar', 'todayFilterText', 'todayScope', 'todayWhose', 'journalFilterText'].forEach(function (k) { if (els[k]) els[k].hidden = true; });
  // nothing to select either — the toggle would open an empty Select mode
  selection.setActive(false);
  document.querySelectorAll('[data-select-toggle]').forEach(function (btn) { btn.hidden = true; });
}

// ------------------------------------------------------------------ data
async function loadPeople() {
  try { state.people = (await api('/api/people')).items || []; } catch (_) { state.people = []; }
}

/** Who a task can belong to and who is asking. Unknown (the call
 *  failed) reads as one member and no viewer, so no owner control offers a
 *  choice it cannot make and no list is narrowed to someone it cannot name. */
async function loadMembers() {
  try {
    const me = await api('/api/me');
    state.members = me.people || [];
    state.viewer = me.id || null;
  } catch (_) { state.members = []; state.viewer = null; }
}

/** The device's storage, or null where reading it throws (private mode). */
function safeStorage() {
  try { return window.localStorage; } catch (_) { return null; }
}

/** The member the lists narrow to — `ownerOf`'s answer for the live state. */
function whoseOwner() {
  return ownerOf(state.filters, state.viewer, state.members.length);
}

function indexSuggestions(items) {
  const indexed = {};
  (items || []).forEach(function (item) { indexed[item.task_id] = item; });
  state.aiSuggestions = indexed;
}

/** The one `GET /api/status` the Board needs at boot: the local AI's state
 *  (the Triage button) and the archiver's (the "needs you" count). The
 *  Email archiving sheet re-reads the same block for itself and publishes it
 *  back here, so both paths tell one story. */
async function loadStatus() {
  try {
    const results = await Promise.all([api('/api/status'), api('/api/ai/suggestions')]);
    state.ai = results[0].ai || { enabled: false, reason: 'AI status unavailable' };
    state.archive = results[0].archive || null;
    indexSuggestions(results[1].items);
  } catch (err) {
    state.ai = { enabled: false, reason: 'AI status unavailable' };
    state.archive = null;
    indexSuggestions([]);
  }
}

/** Latest-wins guard for the reads that replace shared state.
 *
 *  Two loads can be in flight at once — every edit's `refreshAll()` follows the
 *  last one's, and a filter change reloads the list on its own. The network
 *  does not answer in the order it was asked: a slow read issued *before* an
 *  edit landed could resolve *after* the read issued once it had, and the older
 *  snapshot then overwrote the newer, leaving the visible row on the previous
 *  value until a reload. Each read takes a ticket when it starts and is
 *  discarded on arrival if a newer one has started since. Per resource, so a
 *  filter change that only reloads the list never throws away an in-flight
 *  write's tree or Today read. */
const loadSeq = { tree: 0, items: 0, today: 0 };
function beginLoad(resource) { return ++loadSeq[resource]; }
function isLatest(resource, seq) { return loadSeq[resource] === seq; }

/** The boot reads the open forest plus the project list (closed projects
 *  included, so the project filter loses nothing). */
async function loadTree(seq) {
  const res = await Promise.all([api('/api/tasks/tree?descriptions=false'), api('/api/projects')]);
  if (!isLatest('tree', seq)) return;
  state.tree = res[0].items || [];
  state.projects = res[1].items || [];
  state.taskIndex = flattenOpen(state.tree);
}

/** The shared list: the filters as sent to /api/tasks; when no status is
 *  picked, today's done tasks ride along (the Board's Done-today column).
 *
 *  Deferred and blocked tasks are in it only while their pill is
 *  pressed — the server leaves them out otherwise, so a sleeping or locked
 *  task never lands back on the Board by itself. */
async function loadItems(seq) {
  const f = state.filters;
  const params = listParams(f, whoseOwner());
  // No view reads a description off the list (the drawer fetches its own task).
  const slim = { descriptions: false };
  const calls = [api('/api/tasks' + qs(Object.assign({}, params, slim)))];
  if (!f.status.length) {
    calls.push(api('/api/tasks' + qs(Object.assign({}, params, slim, { status: ['done'], done_on: todayISO() }))));
  }
  const results = await Promise.all(calls);
  if (!isLatest('items', seq)) return false;
  const seen = new Set();
  const items = [];
  results.forEach(function (r) {
    (r.items || []).forEach(function (t) { if (!seen.has(t.id)) { seen.add(t.id); items.push(t); } });
  });
  state.items = items;
  return true;
}

/** Drop ticked ids the list no longer holds — deleted elsewhere, or filtered
 *  out — so a bulk POST never carries an id the user cannot see. */
function pruneSelection() {
  if (!selection.isActive()) return;
  selection.keepOnly(new Set(state.items.map(function (t) { return t.id; })));
}

async function refreshAll() {
  const todaySeq = beginLoad('today');
  try {
    const results = await Promise.all([
      loadTree(beginLoad('tree')), loadItems(beginLoad('items')),
      api('/api/tasks?include_closed=true&limit=1&descriptions=false'), api('/api/today'),
    ]);
    if (isLatest('today', todaySeq)) {
      state.total = results[2].count;
      state.calendar = results[3].calendar || null;
    }
    pruneSelection();
    if (state.total === 0) {
      state.items = [];
      state.tree = [];
      state.projects = [];
      renderNoTasks();
      state.headNote = 'No tasks yet';
      app.renderHeadStatus();
      return;
    }
    state.headNote = null;
    renderAll();
    // The date sheet's dates for today — a no-op once read today, so
    // the sheet opens already filled in, and a refresh past midnight re-reads.
    loadPhraseDates();
    // Search rows are drawn from the answer it cached, not from `state.items`:
    // re-read the query so a completed / re-dated hit does not snap back.
    if (search) search.rerun();
    if (state.journal.open) app.refreshJournal();
  } catch (err) {
    state.headNote = 'Server unreachable';
    app.renderHeadStatus();
    toast(err.message || 'Could not load tasks', 'error');
  }
}

/** What the list views show: the filtered list — minus the closed tasks that
 *  ride along for the Board's "Done today" column when no status pill is
 *  ticked (Today defaults to open tasks, as the filter sheet says). */
function viewItems() {
  if (state.filters.status.length) return state.items;
  return state.items.filter(function (t) { return !CLOSED[t.status]; });
}

/** Today's list: the view's items in the scope switch's scope. */
function todayItems() {
  return viewItems().filter(function (t) { return matchesScope(t, state.filters.scope); });
}

/** The Board's list: the shared list (today's done tasks included, for the
 *  Status mode's Done column) in the same scope. */
function boardItems() {
  return state.items.filter(function (t) { return matchesScope(t, state.filters.scope); });
}

/** The scope switch moved: the scope is applied in the browser, so the list
 *  the server sent stays; only the URL key and the views that read it change. */
function onScopeChange(scope) {
  state.filters = Object.assign({}, state.filters, { scope: scope });
  syncUrl();
  renderFilters();
  renderBoardPane();
  renderTodayPane();
  renderSearchScope();
  if (search) search.refilter();
}

/** One tab's scope switch, mounted on first use and kept in step with the
 *  shared state (the switches are the same key, so moving one moves all). */
function renderScope(tab, host) {
  if (!host) return;
  if (!scopes[tab]) scopes[tab] = mountScope(host, onScopeChange);
  scopes[tab].render(state.filters.scope);
  host.hidden = false;
}

function renderSearchScope() { renderScope('search', els.searchScope); }

/** Whose switch moved: the choice is kept per device and mirrored in
 *  the URL, and — unlike the scope — it narrows the server's list, so the
 *  lists and the journal are read again under it. Search never follows. */
function onWhoseChange(whose) {
  try { localStorage.setItem(WHOSE_KEY, whose); } catch (_) { /* private mode: this page only */ }
  onFilterChange(Object.assign({}, state.filters, { whose: whose }));
}

/** One tab's Mine · Everyone switch, only with two or more members (one
 *  member has nothing to switch between). Mounted on first use like the scope's. */
function renderWhose(tab, host) {
  if (!host) return;
  const show = state.members.length >= 2;
  host.hidden = !show;
  if (!show) return;
  if (!whoses[tab]) whoses[tab] = mountWhose(host, onWhoseChange);
  whoses[tab].render(state.filters.whose);
}

// --------------------------------------------------------------- render
/** The one filter state changed (any tab's card, the palette, a "Clear"). */
function onFilterChange(next) {
  state.filters = next;
  syncUrl();
  loadItems(beginLoad('items')).then(function (applied) {
    if (!applied) return;   // a newer read owns the list now and will render it
    renderAll();
    if (state.journal.open) app.refreshJournal();
  }).catch(function (err) { toast(err.message, 'error'); });
}

function renderFilters() {
  const options = { projects: state.projects, people: state.people, count: viewItems().length };
  // Today and the Board count what they show: their lists are narrowed by the scope switch.
  const todayOptions = Object.assign({}, options, { count: todayItems().length });
  const boardOptions = Object.assign({}, options, {
    count: boardItems().filter(function (t) { return state.filters.status.length || !CLOSED[t.status]; }).length,
  });
  // [tab, the top strip that holds the text input and the filter button
  // Search has no text strip: its own box owns the text and holds
  // the button]
  [['board', els.boardFilterText], ['today', els.todayFilterText],
    ['search', null], ['journal', els.journalFilterText]]
    .forEach(function (pair) {
      if (!filterCards[pair[0]]) {
        if (pair[0] === 'search' && !els.searchBox) return;
        if (pair[0] !== 'search' && !pair[1]) return;
        filterCards[pair[0]] = mountFilters(pair[0] === 'journal'
          // the journal's status is implicit (done + cancelled), its order the
          // closing time, and a due / modified window says nothing about a
          // closed task — only project · person · text apply
          ? { onChange: onFilterChange, textHost: pair[1], hide: JOURNAL_HIDES, countLabel: 'closed' }
          : pair[0] === 'search' ? { onChange: onFilterChange, buttonHost: els.searchBox }
            : { onChange: onFilterChange, textHost: pair[1] });
      }
      const opts = pair[0] === 'search' ? { projects: state.projects, people: state.people }
        : pair[0] === 'journal' ? { projects: state.projects, people: state.people, count: state.journal.items.length }
          : pair[0] === 'today' ? todayOptions : pair[0] === 'board' ? boardOptions : options;
      filterCards[pair[0]].render(state.filters, opts);
    });
}

function renderAll() {
  renderFilters();
  renderSelectMode();
  renderBoardPane();
  renderTodayPane();
  renderSearchScope();
  if (search) search.refilter();
}

// ------------------------------------------------------------- selection
/** Select mode's chrome: the toggles' pressed state, the bulk bars, and
 *  which half of the top strip is showing — the strip's filter text and `+`
 *  step aside for the bar rather than stacking a third row above the board. */
function renderSelectMode() {
  const active = selection.isActive();
  const busy = active && selection.size() > 0;
  document.querySelectorAll('[data-select-toggle]').forEach(function (btn) {
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    btn.classList.toggle('is-on', active);
    btn.hidden = busy;
  });
  document.querySelectorAll('[data-quick-add]').forEach(function (btn) { btn.hidden = busy; });
  [els.boardFilterText, els.todayFilterText].forEach(function (host) {
    if (host) host.classList.toggle('is-superseded', busy);
  });
  bulkBars.forEach(function (bar) { bar.render(); });
}

/** Reflect a membership change on the rows already on screen, in place.
 *
 *  Ticking a row must not rebuild two views: a full re-render would also
 *  destroy the checkbox the keyboard is on, so Space-Space-Space down a column
 *  would lose focus after the first tick. Mode changes still rebuild — there
 *  the rows genuinely change shape. */
function syncSelectionMarks() {
  [els.boardHost, els.todayHost].forEach(function (host) {
    if (!host) return;
    host.querySelectorAll('.trow[data-id]').forEach(function (row) {
      const on = selection.has(row.dataset.id);
      row.classList.toggle('is-selected', on);
      const box = row.querySelector('.trow-check');
      if (box) box.checked = on;
    });
  });
}

const selectHandlers = {
  onToggleSelect: function (id) { selection.toggle(id); },
};

function selectOpts() {
  return { selectable: selection.isActive(), isSelected: selection.has };
}

function renderBoardPane() {
  if (!board) {
    board = mountBoard({
      onOpen: openTask, onStatus: app.setStatus, onDue: app.setDue,
      onToggleSelect: selectHandlers.onToggleSelect, menu: menus.board,
      onTriage: app.triageInbox,
      onAcceptSuggestion: app.acceptAISuggestion,
      onRejectSuggestion: app.rejectAISuggestion,
      onAdd: addTask,
      // Week · Status changes what the lanes hold, so the header line follows.
      onModeChange: function () { menus.board.endRender(); app.renderHeadStatus(); },
    }, els.boardBar);
  }
  els.boardBar.hidden = false;
  renderWhose('board', els.boardWhose);
  renderScope('board', els.boardScope);
  if (!els.boardHost.contains(board.el)) els.boardHost.replaceChildren(board.el);
  state.boardCounts = board.render(boardItems(), state.filters, Object.assign({
    ai: state.ai, suggestions: state.aiSuggestions, triaging: state.triaging,
  }, selectOpts()));
  menus.board.endRender();
  app.renderHeadStatus();
}

function renderTodayPane() {
  renderWhose('today', els.todayWhose);
  renderScope('today', els.todayScope);
  state.todayCounts = renderToday(els.todayHost, todayItems(), {
    onOpen: openTask, onStatus: app.setStatus,
    onToggleSelect: selectHandlers.onToggleSelect, menu: menus.today, onAdd: addTask,
  }, Object.assign({
    sort: state.filters.sort, query: state.filters.q,
    calendar: state.calendar,
  }, selectOpts()));
  menus.today.endRender();
  app.renderHeadStatus();
}

// ---------------------------------------------------------- URL / drawer
function syncUrl() {
  if (nav && nav.getTab() === 'search') return;    // the Search box owns ?q= there
  const search = filtersToSearch(state.filters);
  history.replaceState(null, '', location.pathname + search + location.hash);
}

function hashTaskId() {
  const m = /^#(?:journal\/)?task\/(\d+)$/.exec(location.hash || '');
  return m ? Number(m[1]) : null;
}

function openTask(id) {
  // The task panel takes the sheet's place beside the Settings list.
  if (settings.currentSheet()) app.closeSettingsSheet();
  if (hashTaskId() !== id) {
    // inside the journal the hash keeps saying so, or a reload would land on a tab
    const prefix = state.journal.open ? '#journal/task/' : '#task/';
    history.pushState(null, '', location.pathname + location.search + prefix + id);
  }
  preselectedId = null;   // the user picked: it stays open wherever they go
  drawer.open(id);
}

/** Desktop Today never opens on an empty detail half while a task is due:
 *  on entering the tab with nothing open, the
 *  first due row (the first row on screen) fills the right half. No hash is
 *  written: it is the view's default, not a navigation, so a reload picks
 *  the first due task again and Back does not step through it. The phone's
 *  drawer is a full-screen sheet, so there it never opens by itself. */
function preselectToday() {
  if (!drawerBeside.matches || state.tab !== 'today' || state.settingsOpen || state.journal.open) return;
  if (drawer.currentId() != null || hashTaskId() != null) return;
  const first = els.todayHost.querySelector('section.today .trow[data-id]');
  if (!first) return;
  preselectedId = Number(first.dataset.id);
  drawer.open(preselectedId);
}

/** Leaving Today closes the task it opened by itself: on another tab it
 *  would be a panel nobody asked for. A task the user opened stays. */
function dropPreselected() {
  if (preselectedId != null && hashTaskId() == null) drawer.close();
  preselectedId = null;
}

function closeTask() {
  preselectedId = null;
  drawer.close();
  if (hashTaskId() != null) {
    history.replaceState(null, '', location.pathname + location.search + (state.journal.open ? '#journal' : ''));
  }
}

function onHashChange() {
  const sheet = SETTINGS_SHEET_HASH.exec(location.hash);
  if (sheet) {
    // A row press, Forward, or a link from elsewhere (the folder chip's
    // one-time hint, a "not configured" search row, the team sign-in):
    // Settings with that sheet up (settings.js owns the pane's DOM).
    app.showSettingsSheet(sheet[1]);
    return;
  }
  if (location.hash === SETTINGS_HASH) { app.openSettings(); settings.hideSheet(); return; }
  if (location.hash === '#search') {
    // Deep link to the Search tab (?q= carries the query — see boot()).
    nav.setTab('search');
    history.replaceState(null, '', location.pathname + location.search);
    return;
  }
  const id = hashTaskId();
  // #journal: open it, or — Back to a hashless URL — leave it and let
  // the nav re-show the tab it still holds.
  const wantsJournal = JOURNAL_HASH.test(location.hash);
  if (wantsJournal && !state.journal.open) app.openJournal();
  else if (!wantsJournal && state.journal.open && id == null) { app.hideJournal(); nav.setTab(nav.getTab()); }
  if (id == null) { if (drawer.currentId() != null) drawer.close(); return; }
  if (drawer.currentId() !== id) drawer.open(id);
}

// ------------------------------------------------------------ quick-add
function focusRow(task) {
  // The new row in whichever surface is showing; the drawer stays closed so
  // the eye lands on the row, not a panel.
  const tab = nav.getTab();
  const hosts = { board: els.boardHost, today: els.todayHost };
  // Settings covers the nav's tab: land on the Board, as a non-list tab
  // does — a new task opens in Inbox, which is a Board column.
  let host = state.settingsOpen ? null : hosts[tab];
  if (!host) { nav.setTab('board'); host = els.boardHost; }
  const target = host.querySelector('.trow[data-id="' + task.id + '"] .trow-main');
  if (target) {
    target.tabIndex = 0;
    target.focus({ preventScroll: false });
    target.closest('.trow').classList.add('is-new');
    target.scrollIntoView({ block: 'nearest' });
  }
}

// ------------------------------------------------------------ select mode
function wireSelectMode() {
  document.querySelectorAll('[data-select-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () { selection.setActive(!selection.isActive()); });
  });
  [els.boardBulk, els.todayBulk].forEach(function (host) {
    if (!host) return;
    bulkBars.push(mountBulkBar(host, {
      onApply: app.bulkApply,
      onDelete: app.bulkDelete,
      onExit: function () { selection.setActive(false); },
      members: function () { return state.members; },
    }));
  });
  // One store, two views. Entering/leaving Select mode changes the rows'
  // shape, so it rebuilds; a tick only changes which rows are marked, so it
  // is reflected in place (and Today, rebuilt on its next render, reads the
  // same store — which is what carries a Board selection across the tab).
  selection.subscribe(function (kind) {
    if (kind === 'mode' && state.total) renderAll();
    else syncSelectionMarks();
    renderSelectMode();
  });
}

function wireQuickAdd() {
  quickAdd = createQuickAdd(els.quickAdd, {
    onCreated: function (task) { refreshAll().then(function () { focusRow(task); }); },
  });
  document.querySelectorAll('[data-quick-add]').forEach(function (btn) {
    btn.addEventListener('click', function () { quickAdd.open(); });
  });
}

/** An empty list's way forward: the quick-add, preset to the list. */
function addTask(preset) {
  quickAdd.open(preset);
}

// ---------------------------------------------------- search + palette
/** Write the Search tab's query into ?q= (only while that tab is showing — the
 *  strip's text field owns ?q= on the other tabs). */
function syncSearchUrl(q) {
  if (!nav || nav.getTab() !== 'search') return;
  const p = new URLSearchParams(location.search);
  if (q) p.set('q', q); else p.delete('q');
  const s = p.toString();
  history.replaceState(null, '', location.pathname + (s ? '?' + s : '') + location.hash);
}

/** The one row-action runner: the keymap, the status select and the
 *  row's own controls all commit through it. Every write is one POST
 *  /api/tasks/bulk — one id or the whole ticked set — so an action means the
 *  same thing either way and each task still goes through the repo layer's
 *  single-task path. */
function wireActions() {
  actions = createActions({
    write: function (ids, changes) {
      return api('/api/tasks/bulk', { method: 'POST', body: Object.assign({ ids: ids }, changes) });
    },
    refresh: async function () {
      await refreshAll();
      if (drawer.currentId() != null) drawer.refresh();
    },
  });
  // Each rendered list owns its menu, so one view's rebuild never closes a
  // menu that is open on another's row.
  const ctx = { actions: actions, onOpen: openTask };
  menus = {};
  ['board', 'today', 'journal', 'search'].forEach(function (view) {
    menus[view] = createTaskMenu(ctx);
  });
}

/** The row keymap, reading the same actions. */
function wireKeys() {
  keys = mountKeys(els.keysHelp, {
    actions: actions,
    resolveTask: app.resolveTask,
    // A task you opened owns the keys. The one desktop Today opened by
    // itself does not, unless the focus is in it: else the keymap would be off
    // on the landing tab from the first paint.
    isBlocked: function () {
      const id = drawer.currentId();
      return id != null && (id !== preselectedId || els.drawer.contains(document.activeElement));
    },
  });
}

function wirePalette() {
  palette = createPalette(els.palette, { commands: app.paletteCommands, onOpenTask: openTask });
  document.addEventListener('keydown', function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      palette.toggle();
    }
  });
}

// ---------------------------------------------------------------- boot
function wireDrawer() {
  drawer = createDrawer(els.drawer, {
    onChanged: refreshAll,
    onOpen: openTask,
    onClose: closeTask,
    people: function () { return state.people; },
    members: function () { return state.members; },
    parentTargets: function (id) { return parentTargets(state.tree, id); },
    allTasks: function () { return state.taskIndex; },
    onMove: app.moveTask,
    onStatus: app.setStatus,
    issues: function () { return state.issues; },
    onSyncIssues: app.syncIssues,
  });
}

/** The Settings pane owns its own cards (settings.js) and the Email archiving
 *  sheet its run and report. */
function wireSettings() {
  settings = mountSettings({
    onSyncIssues: app.syncIssues,
    // The phone's way into the palette: Ctrl+K needs a hardware keyboard.
    onOpenPalette: function () { palette.open(''); },
    // Row actions: a row's menu reads its list when the row is drawn,
    // so a new choice redraws the lists that are up.
    onRowActions: function () {
      if (state.total) renderAll();
      if (state.journal.open) app.renderJournalPane();
    },
    onSearchStatus: function () { if (search) search.reloadStatus(); },
    // New captured tasks land in Inbox, so the views behind Settings are stale
    // until they reload — same follow-up an issue sync does after it creates.
    onCaptured: function () { refreshAll(); },
    // Refresh now on the Calendar card answers the fresh lane: Today
    // shows it without a second round trip.
    onCalendar: function (group) { state.calendar = group; renderTodayPane(); },
    // A run this page did not start (another device): hand it to the Email
    // archiving sheet, which re-reads the service, picks the live run up and
    // resumes polling it.
    onArchiveRun: function () { if (archive) archive.refresh(); },
    // A row's word changed: the Settings header line is read off them.
    onHead: app.renderHeadStatus,
    onOpenSheet: app.openSettingsSheet,
    onCloseSheet: app.closeSettingsSheet,
  });
  // The Email archiving sheet's run and report.
  archive = mountArchive({
    // Settings' rows render the same block rather than polling it.
    // (the palette's Go to Archive hint and the Settings header read
    // `state.archive`)
    onStatus: function (st) {
      state.archive = st;
      settings.renderArchive(st);
    },
    // A run files mail and a review action re-files one — neither touches a
    // task, and nothing outside the pane shows the run's count.
    onChanged: function () {},
  });
}

/** Escape closes what is on top: a Settings sheet or the drawer, then Select mode. */
function wireEscape() {
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    // A field where you are typing owns Escape (revert / clear its own value).
    // A checkbox does not: after ticking a row the focus sits on one, and
    // Escape there has to leave Select mode or the key looks broken.
    if (ev.target.closest('textarea, select, input:not([type="checkbox"])')) return;
    // an open dialog (palette, quick-add, the keys card, a confirmation) owns
    // Escape natively — it must not also close the drawer underneath
    if (document.querySelector('dialog[open]')) return;
    if (settings.currentSheet()) app.closeSettingsSheet();
    else if (drawer.currentId() != null) closeTask();
    else if (selection.isActive()) selection.setActive(false);
  });
}

async function boot() {
  wireTheme();
  wireActions();
  wireDrawer();
  // Before the nav: restoring the stored tab can fire onChange straight into Settings.
  wireSettings();
  // The filters are shared by every tab, so a shared URL never moves the tab
  // by itself. First visit: Today, on every pointer — the first tab in the nav.
  const f = state.filters;
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  // ?q= belongs to the Search tab when the page lands there (#search deep
  // link, or the last tab was Search); otherwise it is the strip's text filter.
  let storedTab = null;
  try {
    storedTab = localStorage.getItem(TAB_KEY);
    RETIRED_KEYS.forEach(function (k) { localStorage.removeItem(k); });
  } catch (_) { /* private mode */ }
  const wantsSearch = location.hash === '#search' || (f.q !== '' && storedTab === 'search');
  let searchQ = '';
  if (wantsSearch) { searchQ = f.q; state.filters = Object.assign({}, f, { q: '' }); }
  // Before the nav: its first onChange restores a stored tab, Time among them.
  time = mountTime({ onHead: app.renderHeadStatus });
  nav = initNavTabs({
    storageKey: TAB_KEY,
    defaultTab: 'today',
    onChange: function (tab) {
      state.tab = tab;
      usage.trackView(tab);
      app.setHeadTitleFromTab(tab);
      app.hideJournal();   // a tab press is how the journal is left; the nav re-showed its pane
      app.hideSettings();  // …and Settings, the same way
      // …even before they have opened: boot only opens them at its end,
      // so a tab pressed while it loads would otherwise be covered again by the
      // `#settings` / `#journal` hash it left behind. `nav` is still null for
      // the init call that restores the stored tab, which must keep the hash.
      if (nav) app.dropPendingPaneHash();
      if (tab === 'board' && board) board.show();
      if (tab === 'time') time.show();
      else time.hide();
      if (tab === 'search' && search) { syncSearchUrl(search.getQuery()); if (!coarse) search.focus(); }
      else syncUrl();
      app.renderHeadStatus();
      if (!nav) return;   // the init call restoring the stored tab: boot preselects at its end
      if (tab === 'today') preselectToday();
      else dropPreselected();
    },
  });
  if (wantsSearch) { nav.setTab('search'); if (location.hash === '#search') history.replaceState(null, '', location.pathname + location.search); }
  // A PWA last left on the retired Settings tab reopens on Settings once;
  // the nav has already stored its default tab in that key's place.
  if (storedTab === 'settings' && !location.hash) history.replaceState(null, '', location.pathname + location.search + SETTINGS_HASH);
  // …and one last left on the retired Archive tab on its sheet.
  if (storedTab === 'archive' && !location.hash) history.replaceState(null, '', location.pathname + location.search + '#settings/archive');
  // Pressed while Settings is up, it re-reads the cards — what tapping the
  // Settings tab used to do.
  els.settingsBtn.addEventListener('click', app.openSettings);
  wireQuickAdd();
  wireSelectMode();
  search = mountSearch(els.searchBox, els.searchHost, {
    onOpenTask: openTask,
    onQuery: syncSearchUrl,
    filters: function () { return state.filters; },
    onStatus: app.setStatus,
    menu: menus.search,
  });
  if (searchQ) search.setQuery(searchQ);
  // Before the palette and before Escape below: the keymap's own listener has
  // to be the first document keydown so it can stop Escape from also leaving
  // Select mode when all it should do is close its popover (keys.js).
  wireKeys();
  wirePalette();
  wireEscape();
  window.addEventListener('hashchange', onHashChange);
  window.addEventListener('popstate', onHashChange);
  app.fetchVersion();
  settings.refreshStatus();
  await Promise.all([loadPeople(), loadMembers()]);
  await Promise.all([refreshAll(), app.fetchIssuesStatus(), loadStatus()]);
  if (state.total) renderBoardPane();
  onHashChange();
  preselectToday();
}

boot();
