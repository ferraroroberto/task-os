/* task-os — the done journal's window, its two reads and its pane: a pane
 * without a tab, reached from the palette and the Board's Done column.
 * journal.js draws it; each function takes the app composer's `app` first.
 */

'use strict';

import { api, qs } from '../../api.js';
import { addDays, todayISO } from '../../format.js';
import { renderJournal } from '../../journal.js';
import { toast } from '../../toast.js';

// The journal's hash — `#journal`, or `#journal/task/<id>` with the drawer open on it.
export const JOURNAL_HASH = /^#journal(\/|$)/;

// ---------------------------------------------------------------- journal
/** The done journal — journal.js draws it; this owns its window and
 *  its two reads: the page (closed tasks in the window, the API's done window
 *  orders them newest closing first) and the older-probe (one row before the
 *  window, if any). `older` stays null while the probe is unanswered — an
 *  unknown keeps the "week before" button; the end of the journal is only
 *  ever stated when the server said so. */
export function journalWindow(app) {
  const to = todayISO();
  return { from: addDays(to, -(7 * app.state.journal.weeks - 1)), to: to };
}

export function journalParams(app) {
  const f = app.state.filters;
  return {
    status: app.state.journal.cancelled ? ['done', 'cancelled'] : ['done'],
    owner: app.whoseOwner() || undefined,
    project: f.project || undefined,
    person: f.person.length ? f.person : undefined,
    q: f.q || undefined,
  };
}

export async function loadJournal(app) {
  const w = app.journalWindow();
  const base = app.journalParams();
  const before = addDays(w.from, -1);
  const [page, probe] = await Promise.all([
    api('/api/tasks' + qs(Object.assign({}, base, { done_from: w.from, done_to: w.to }))),
    api('/api/tasks' + qs(Object.assign({}, base, { done_to: before, limit: 1 })))
      .catch(function () { return null; }),
  ]);
  app.state.journal.items = page.items || [];
  app.state.journal.older = probe ? probe.count > 0 : null;
}

export function renderJournalPane(app) {
  const w = app.journalWindow();
  renderJournal(app.els.journalHost, app.state.journal.items,
    { onOpen: app.openTask, onStatus: app.setStatus, menu: app.menus.journal },
    {
      from: w.from, weeks: app.state.journal.weeks, hasOlder: app.state.journal.older, cancelled: app.state.journal.cancelled,
      onOlder: function () { app.state.journal.weeks += 1; app.refreshJournal(); },
      onCancelled: function (on) { app.state.journal.cancelled = on; app.refreshJournal(); },
    });
  app.menus.journal.endRender();
  if (app.filterCards.journal) {
    app.filterCards.journal.render(app.state.filters, { projects: app.state.projects, people: app.state.people, count: app.state.journal.items.length });
  }
}

export function refreshJournal(app) {
  return app.loadJournal().then(app.renderJournalPane)
    .catch(function (err) { toast(err.message || 'Could not load the journal', 'error'); });
}

/** Show the journal over whichever pane the nav has up. The pill itself is
 *  untouched (vendored contract); only its lit state comes off the tab whose
 *  pane is now covered, so no tab claims to be showing. Any tab press leaves
 *  (the nav re-shows its pane on its own — see boot()). */
export function openJournal(app) {
  app.hideSettings();
  if (app.time) app.time.hide();
  if (!app.state.journal.open) {
    app.state.journal.open = true;
    const navEl = document.querySelector('nav.tabs');
    navEl.querySelectorAll('.tab').forEach(function (b) { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
    navEl.dataset.activeTab = 'journal';
    document.querySelectorAll('main.app > .pane').forEach(function (p) { p.hidden = p !== app.els.paneJournal; });
    window.scrollTo(0, 0);
    app.setHeadTitle('Done journal', 'i-book-open');
    app.usage.trackView('journal');
    app.dropPreselected();
    app.renderHeadStatus();
  }
  if (!JOURNAL_HASH.test(location.hash)) history.replaceState(null, '', location.pathname + location.search + '#journal');
  return app.refreshJournal();
}

export function hideJournal(app) {
  if (!app.state.journal.open) return;
  app.state.journal.open = false;
  app.els.paneJournal.hidden = true;
  if (JOURNAL_HASH.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);
}
