/* task-os — the Settings pane over the nav's tab, and the one row's sheet
 * `#settings/<sheet>` keeps open over it. settings.js owns the pane's DOM;
 * each function here takes the app composer's `app` first.
 */

'use strict';

import { JOURNAL_HASH } from './journal.js';

// Settings is a pane with no tab: the header gear opens it, `#settings`
// keeps it across a reload, and `#settings/<sheet>` has one row's sheet open
// over it — a row press pushes it, so Back closes the sheet.
export const SETTINGS_HASH = '#settings';
export const SETTINGS_SHEET_HASH = /^#settings\/([a-z]+)$/;

// ------------------------------------------------------------- settings
/** Show the Settings pane over whichever pane the nav has up. Settings
 *  is no tab — five destinations is the pill's ceiling (design.md) — but the
 *  header gear, in the journal's shape: the pill's lit tab comes off, any tab
 *  press leaves (the nav re-shows its own pane, onChange hides this one), and
 *  `#settings` keeps it across a reload. */
export function openSettings(app) {
  app.hideJournal();
  // One detail beside the list at a time: Settings has its own.
  if (app.drawer.currentId() != null) app.closeTask();
  if (!app.state.settingsOpen) {
    app.state.settingsOpen = true;
    const navEl = document.querySelector('nav.tabs');
    navEl.querySelectorAll('.tab').forEach(function (b) { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
    navEl.dataset.activeTab = 'settings';
    document.querySelectorAll('main.app > .pane').forEach(function (p) { p.hidden = p !== app.els.paneSettings; });
    app.els.settingsBtn.setAttribute('aria-current', 'page');
    app.setHeadTitle('Settings', 'i-settings');
    app.usage.trackView('settings');
    app.dropPreselected();
    // Its poll stops under Settings, and its two Settings rows read its meta.
    if (app.time) { app.time.hide(); app.time.settingsShown(); }
    app.renderHeadStatus();
    const scroller = document.querySelector('.app');
    if (scroller) scroller.scrollTop = 0;
    window.scrollTo(0, 0);
  }
  if (location.hash !== SETTINGS_HASH && !SETTINGS_SHEET_HASH.test(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search + SETTINGS_HASH);
  }
  app.settings.refreshStatus();
  app.fetchIssuesStatus();
  app.settings.refreshSearchStatus();
}

/** A `#settings` (or Settings card) / `#journal` hash with its pane not open
 *  yet: boot opens it at its end, unless a tab press came first. */
export function dropPendingPaneHash(app) {
  const h = location.hash;
  if (h === SETTINGS_HASH || SETTINGS_SHEET_HASH.test(h) || JOURNAL_HASH.test(h)) {
    history.replaceState(null, '', location.pathname + location.search);
  }
}

export function hideSettings(app) {
  if (!app.state.settingsOpen) return;
  app.state.settingsOpen = false;
  app.settings.hideSheet();
  app.els.paneSettings.hidden = true;
  app.els.settingsBtn.removeAttribute('aria-current');
  if (location.hash === SETTINGS_HASH || SETTINGS_SHEET_HASH.test(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search);
  }
}

/** A Settings row was pressed (or the palette asked): Settings with that
 *  row's sheet up, as `#settings/<key>` — pushed, so Back closes the sheet. */
export function openSettingsSheet(app, key) {
  const hash = '#settings/' + key;
  if (location.hash !== hash) history.pushState(null, '', location.pathname + location.search + hash);
  app.showSettingsSheet(key);
}

/** …and what `#settings/<key>` shows, however it arrived. The Email
 *  archiving sheet reads its runs as it opens, as the Archive tab did. */
export function showSettingsSheet(app, key) {
  app.openSettings();
  const fresh = app.settings.currentSheet() !== key;
  if (!app.settings.showSheet(key)) return;
  if (fresh) app.usage.trackView('settings.' + key);
  if (fresh && key === 'archive') app.archive.refresh();
  if (fresh && key === 'timecats') app.time.openSheet(key);
}

/** The sheet's × / Done / Escape: back to the Settings list. */
export function closeSettingsSheet(app) {
  if (app.settings.currentSheet()) app.usage.trackView('settings');
  app.settings.hideSheet();
  if (SETTINGS_SHEET_HASH.test(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search + SETTINGS_HASH);
  }
}
