/* task-os — the one sheet body per row (`data-sheet`), all inside the one
 * #settingsSheet. One is up at a time; the bootstrap opens and closes it
 * (`#settings/<key>`) and this module only asks (`opts.onOpenSheet` /
 * `opts.onCloseSheet`). */

'use strict';

/** Look up the sheet bodies, wire the rows and the close buttons, and hand
 *  back the show / hide the bootstrap calls. */
export function createSheets(ctx) {
  const bodies = {};
  ctx.els.sheet.querySelectorAll('.settings-sheet[data-sheet]').forEach(function (s) { bodies[s.dataset.sheet] = s; });
  let openKey = null;

  function rowFor(key) {
    return ctx.els.pane.querySelector('[data-settings-sheet="' + key + '"]');
  }

  /** Show `key`'s sheet (the bootstrap calls it for `#settings/<key>`): its
   *  body alone, titled by its row's label, the row marked as the selected
   *  one (beside the detail pane on a wide screen). False for an unknown key. */
  function showSheet(key) {
    if (!bodies[key]) return false;
    const fresh = openKey !== key;
    Object.keys(bodies).forEach(function (k) { bodies[k].hidden = k !== key; });
    const row = rowFor(key);
    ctx.els.sheetTitle.textContent = row ? row.querySelector('.action-row-title').textContent : '';
    ctx.els.pane.querySelectorAll('[data-settings-sheet]').forEach(function (r) {
      if (r === row) r.setAttribute('aria-current', 'true');
      else r.removeAttribute('aria-current');
    });
    ctx.els.sheet.hidden = false;
    document.body.dataset.settingsSheet = key;
    openKey = key;
    if (fresh) {
      ctx.els.sheet.querySelector('.settings-sheet-scroll').scrollTop = 0;
      ctx.els.sheet.querySelector('.settings-sheet-close').focus({ preventScroll: true });
    }
    return true;
  }

  /** Close the sheet; focus goes back to its row while that is on screen. */
  function hideSheet() {
    if (openKey == null) return;
    const row = rowFor(openKey);
    openKey = null;
    ctx.els.sheet.hidden = true;
    delete document.body.dataset.settingsSheet;
    if (row) row.removeAttribute('aria-current');
    if (row && !ctx.els.pane.hidden && ctx.els.sheet.contains(document.activeElement)) row.focus({ preventScroll: true });
  }

  function wireSheets() {
    ctx.els.pane.querySelectorAll('[data-settings-sheet]').forEach(function (row) {
      row.addEventListener('click', function () { ctx.opts.onOpenSheet(row.dataset.settingsSheet); });
    });
    // Instant model: every control applies as it changes, so Done only closes.
    ctx.els.sheet.querySelector('.settings-sheet-close').addEventListener('click', function () { ctx.opts.onCloseSheet(); });
    ctx.els.sheet.querySelector('.settings-sheet-done').addEventListener('click', function () { ctx.opts.onCloseSheet(); });
  }

  wireSheets();

  return { showSheet: showSheet, hideSheet: hideSheet, currentSheet: function () { return openKey; } };
}
