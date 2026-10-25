/* task-os — the command palette's list (palette.js draws it) and the
 * archive hints it and the Settings header read. Each takes the app
 * composer's `app` first.
 */

'use strict';

import { api } from '../../api.js';
import { DEFAULT_FILTERS } from '../../filters.js';
import { STATUSES } from '../../format.js';
import { toast } from '../../toast.js';

/** Emit the taskos:// opener link of the task open in the drawer (a click on
 *  the same chip the drawer carries, so the one-time opener hint applies). */
export function openFolderOfCurrentTask(app) {
  const id = app.drawer.currentId();
  if (id == null) { toast('Open a task first', 'error'); return; }
  const chip = app.els.drawer.querySelector('.drawer-folder a.chip-folder');
  if (!chip) { toast('The open task has no folder', 'error'); return; }
  chip.click();
}

/** How many mails the last archiving run left for a human, or why the
 *  tab has nothing to show. `null` state = not established, never "off". */
export function archiveNeedsYou(app) {
  const last = app.state.archive && app.state.archive.last_run;
  return last ? Number(last.needs_review || 0) : 0;
}

export function archiveHint(app) {
  if (!app.state.archive) return 'archiver state unknown';
  if (!app.state.archive.configured) return app.state.archive.reason || 'not configured';
  if (app.state.archive.running) return 'a run is in progress';
  const needs = app.archiveNeedsYou();
  return needs ? needs + ' mail(s) from the last run need you' : 'file the Outlook Inbox in one run';
}

/** The palette's command list — built per open so hints reflect the moment. */
export function paletteCommands(app) {
  const go = function (tab) { return function () { app.nav.setTab(tab); if (tab === 'search' && app.search) app.search.focus(); }; };
  const cmds = [
    { id: 'new-task', label: 'New task', hint: 'the quick-add dialog', icon: 'plus', run: function () {
      if (app.quickAdd) app.quickAdd.open();
    } },
    // The row keys, each showing its key — the palette is where a
    // shortcut is discovered. Top of the list while a row is focused or
    // ticked, because acting on it is then the likeliest intent; otherwise
    // they are still listed (that is the discovery), just under the places
    // you can actually go right now.
    ...(app.keys && app.keys.hasTarget() ? app.keys.commands() : []),
    { id: 'go-today', label: 'Go to Today', icon: 'calendar-days', run: go('today') },
    { id: 'go-board', label: 'Go to Board', icon: 'square-kanban', run: go('board') },
    { id: 'go-time', label: 'Go to Time', icon: 'timer', run: go('time') },
    // The Archive tab: Settings → Email archiving now, one command away still.
    { id: 'go-archive', label: 'Go to Archive', hint: app.archiveHint(), icon: 'archive', run: function () { app.openSettingsSheet('archive'); } },
    { id: 'go-search', label: 'Go to Search', icon: 'search', run: go('search') },
    { id: 'go-settings', label: 'Go to Settings', icon: 'settings', run: app.openSettings },
    { id: 'go-journal', label: 'Journal', hint: 'what got done, by day', icon: 'book-open', run: app.openJournal },
    ...(app.keys && !app.keys.hasTarget() ? app.keys.commands() : []),
  ];
  STATUSES.forEach(function (st) {
    cmds.push({ id: 'filter-' + st, label: 'Filter: status ' + st, hint: 'every view', icon: 'list-filter', run: function () {
      app.onFilterChange(Object.assign({}, app.state.filters, { status: [st] }));
    } });
  });
  cmds.push({ id: 'filter-clear', label: 'Filter: clear', hint: 'back to open tasks', icon: 'list-filter', run: function () {
    app.onFilterChange(Object.assign({}, DEFAULT_FILTERS, { scope: app.state.filters.scope, whose: app.state.filters.whose }));
  } });
  cmds.push({ id: 'sync-issues', label: 'Sync issues', hint: app.state.issues && app.state.issues.enabled ? 'one pass now (' + app.state.issues.provider + ')' : 'issue provider not configured', icon: 'refresh-cw', run: function () { return app.syncIssues(); } });
  cmds.push({ id: 'reindex-folders', label: 'Rescan folders', hint: 'refresh the folder index now', icon: 'folder', run: async function () {
    try { const r = await api('/api/folders/reindex', { method: 'POST', body: {} }); toast('Folder index: ' + r.entries + ' folder(s) in ' + r.seconds + ' s', 'success'); app.settings.refreshStatus(); }
    catch (err) { toast(err.message || 'Reindex failed', 'error'); }
  } });
  cmds.push({ id: 'export-mirror', label: 'Export mirror', hint: 'every task to mirror.dir now', icon: 'copy', run: async function () {
    try { const r = await api('/api/mirror/export', { method: 'POST', body: {} }); toast('Mirror: ' + r.written + ' written, ' + r.removed + ' removed', 'success'); }
    catch (err) { toast(err.message || 'Export failed', 'error'); }
  } });
  cmds.push({ id: 'open-folder', label: 'Open folder of current task', hint: app.drawer.currentId() != null ? 'task #' + app.drawer.currentId() : 'no task open', icon: 'folder', run: app.openFolderOfCurrentTask });
  cmds.push({ id: 'toggle-theme', label: 'Toggle theme', hint: document.documentElement.dataset.theme === 'dark' ? 'to light' : 'to dark', icon: 'sun', run: function () { app.els.themeToggle.click(); } });
  cmds.push({ id: 'sign-out', label: 'Sign out', hint: 'this device (token cookie)', icon: 'x', run: async function () {
    try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { toast(err.message, 'error'); return; }
    location.assign('/login');
  } });
  return cmds;
}
