/* task-os — the Settings page over the nav's tab, and the one row's sheet
 * `#settings/<sheet>` keeps open over it. settings.js owns the page's rows;
 * each function here takes the app composer's `app` first.
 */

'use strict';

import { featureOn } from '../features.js';
import { JOURNAL_HASH } from './journal.js';

// Settings is no tab: the header gear opens it, `#settings` keeps it across a
// reload, and `#settings/<sheet>` has one row's sheet open over it — a row
// press pushes it, so Back closes the sheet.
export const SETTINGS_HASH = '#settings';
export const SETTINGS_SHEET_HASH = /^#settings\/([a-z]+)$/;

function isSettingsHash(h) {
  return h === SETTINGS_HASH || SETTINGS_SHEET_HASH.test(h);
}

// ------------------------------------------------------------- settings
/** Open the Settings page (a modal dialog) over whichever tab the nav has up.
 *  Settings is no tab — five destinations is the pill's ceiling (design.md) —
 *  but the header gear: the tab, its lit pill button and any open task stay
 *  as they are under it, and closing the page returns to them. The usage log
 *  records the page as its view when the dialog opens. */
export function openSettings(app) {
  app.hideJournal();
  const page = app.els.paneSettings;
  if (!app.state.settingsOpen) {
    app.state.settingsOpen = true;
    // The URL under the page, put back when it closes (an open task's hash).
    app.state.settingsReturnHash = isSettingsHash(location.hash) ? '' : location.hash;
    app.els.settingsBtn.setAttribute('aria-current', 'page');
    // Its poll stops under Settings, and its two Settings rows read its meta.
    if (app.time) { app.time.hide(); if (featureOn('time')) app.time.settingsShown(); }
    if (!page.open) page.showModal();
    page.scrollTop = 0;
    app.renderHeadStatus();
  }
  if (!isSettingsHash(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search + SETTINGS_HASH);
  }
  app.settings.refreshStatus();
  app.fetchIssuesStatus();
  app.settings.refreshSearchStatus();
  app.settings.refreshFeatures();
}

/** A `#settings` (or Settings card) / `#journal` hash with its pane not open
 *  yet: boot opens it at its end, unless a tab press came first. */
export function dropPendingPaneHash(app) {
  const h = location.hash;
  if (isSettingsHash(h) || JOURNAL_HASH.test(h)) {
    history.replaceState(null, '', location.pathname + location.search);
  }
}

/** Close the Settings page (its ×, Escape, a tab the palette switched to):
 *  back to the tab under it, its poll and its URL. */
export function hideSettings(app) {
  if (!app.state.settingsOpen) return;
  app.state.settingsOpen = false;
  app.settings.hideSheet();
  if (app.els.paneSettings.open) app.els.paneSettings.close();
  app.els.settingsBtn.removeAttribute('aria-current');
  if (isSettingsHash(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search + (app.state.settingsReturnHash || ''));
  }
  app.state.settingsReturnHash = '';
  // Under the page the Time tab may have been switched off: leave it now.
  if (app.state.tab === 'time' && app.nav) {
    if (featureOn('time')) app.time.show();
    else app.nav.setTab('today');
  }
  app.renderHeadStatus();
}

/** The page's close button, and Escape (a modal closes itself natively). */
export function wireSettingsPage(app) {
  const page = app.els.paneSettings;
  page.querySelector('.settings-page-close').addEventListener('click', function () { app.hideSettings(); });
  page.addEventListener('close', function () { if (app.state.settingsOpen && !page.open) app.hideSettings(); });
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
  if (fresh && key === 'archive') app.archive.refresh();
  if (fresh && key === 'timecats') app.time.openSheet(key);
}

/** The sheet's × / Done / Escape: back to the Settings list. */
export function closeSettingsSheet(app) {
  app.settings.hideSheet();
  if (SETTINGS_SHEET_HASH.test(location.hash)) {
    history.replaceState(null, '', location.pathname + location.search + SETTINGS_HASH);
  }
}

/** A feature block was switched (Settings → Available features): leave a tab that
 *  just went away, then re-read everything its UI and the Settings rows were built from. */
export function featuresChanged(app, key, on) {
  // Under the open Settings page the tab stays until the page closes (hideSettings).
  if (key === 'time' && !on && !app.state.settingsOpen && app.nav && app.nav.getTab() === 'time') app.nav.setTab('today');
  app.settings.refreshStatus();
  app.settings.refreshSearchStatus();
  if (app.search) app.search.reloadStatus();
  app.fetchIssuesStatus();
  app.loadStatus().then(function () { if (app.state.total) app.renderBoardPane(); });
  app.refreshAll();
}
