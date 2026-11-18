/* task-os — the one sheet section per row (`data-sheet`), all inside the one
 * #settingsSheet dialog. One is up at a time; the bootstrap opens and closes it
 * (`#settings/<key>`) and this module only asks (`opts.onOpenSheet` /
 * `opts.onCloseSheet`). */

'use strict';

import { featureOn } from '../features.js';

/** Look up the sheet sections, wire the rows and the close buttons, and hand
 *  back the show / hide the bootstrap calls. */
export function createSheets(ctx) {
  const bodies = {};
  const dialog = ctx.els.sheet;
  ctx.els.sheet.querySelectorAll('.settings-sheet-section[data-sheet]').forEach(function (s) { bodies[s.dataset.sheet] = s; });
  let openKey = null;

  function rowFor(key) {
    return ctx.els.pane.querySelector('[data-settings-sheet="' + key + '"]');
  }

  /** Show `key`'s sheet (the bootstrap calls it for `#settings/<key>`): its
   *  section alone, titled by its row's label, as a modal over the Settings
   *  page. False for an unknown key or a block switched off here. */
  function showSheet(key) {
    if (!bodies[key]) return false;
    const owner = rowFor(key) && rowFor(key).dataset.feature;
    if (owner && !featureOn(owner)) return false;   // its block is switched off here
    if (openKey === key && dialog.open) return true;
    // Another row's sheet is up (a link inside a sheet): close it first, so the
    // usage log records the new one as its own view when it opens.
    if (dialog.open) dialog.close();
    Object.keys(bodies).forEach(function (k) { bodies[k].hidden = k !== key; });
    const row = rowFor(key);
    ctx.els.sheetTitle.textContent = row ? row.querySelector('.settings-row-label').textContent : '';
    // dynamic-id-exempt: key is one of the settings sheet names, a fixed set
    dialog.dataset.trackView = 'settings.' + key;
    dialog.dataset.sheet = key;
    openKey = key;
    dialog.showModal();
    dialog.querySelector('.settings-sheet-body').scrollTop = 0;
    return true;
  }

  /** Close the sheet; the dialog hands focus back to the row that opened it. */
  function hideSheet() {
    if (openKey == null) return;
    openKey = null;
    if (dialog.open) dialog.close();
  }

  function wireSheets() {
    ctx.els.pane.querySelectorAll('[data-settings-sheet]').forEach(function (row) {
      row.addEventListener('click', function () { ctx.opts.onOpenSheet(row.dataset.settingsSheet); });
    });
    // Instant model: every control applies as it changes, so Done only closes.
    dialog.querySelector('.detail-close').addEventListener('click', function () { ctx.opts.onCloseSheet(); });
    dialog.querySelector('.settings-sheet-done').addEventListener('click', function () { ctx.opts.onCloseSheet(); });
    // Escape closes the modal natively: the URL follows it back to the list.
    // (The event is queued: a sheet reopened in the meantime is open again, and stays.)
    dialog.addEventListener('close', function () { if (openKey != null && !dialog.open) ctx.opts.onCloseSheet(); });
  }

  wireSheets();

  return { showSheet: showSheet, hideSheet: hideSheet, currentSheet: function () { return openKey; } };
}
