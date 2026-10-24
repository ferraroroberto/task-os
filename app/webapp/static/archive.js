/* task-os — Settings → Email archiving: run the batch, read the report, fix what is wrong (#159).
 *
 * Step 3/3 of batch email archiving. One button files the whole Outlook Inbox
 * through email-archiver (#157) with the local model picking the folder (#158);
 * this module is the screen that starts that run and then lets a human review
 * every mail it touched. It is **read-mostly over the Step 1 API** — no domain
 * rule lives here:
 *
 *   POST /api/archive/run {limit?}       start one run (202, then it polls)
 *   GET  /api/archive/runs?limit=        the run picker
 *   GET  /api/archive/runs/{id}          the run + its rows — the whole report
 *   POST /api/archive/items/{id}/accept  {hint?}          "I have seen this"
 *   POST /api/archive/items/{id}/move    {folder, hint?}  file it where I say
 *   POST /api/archive/items/{id}/revert                   undo this one mail
 *   POST /api/archive/items/{id}/retry                    finish a refused move
 *
 * The five review levels the report offers per row are exactly the API's, and
 * which of them a row gets is decided by that row's own state, never by taste:
 * *accept* only reaches a row that asks for a human (`needs_review`, `failed` —
 * an `archived` row is finished, not reviewed, and the API answers 409 there),
 * *revert* only reaches a row with files on disk, and *move* reaches both those
 * and a `needs_review` mail still sitting in the Inbox — filing it for the
 * first time is the commonest thing anyone does on this screen. *Retry* (#174)
 * reaches exactly one shape: a `failed` mail whose files were written before
 * Outlook refused the move, which is the only row where re-sending the same
 * decision finishes something instead of filing it twice. A control that
 * would 409 is not rendered; a row that genuinely offers nothing says so.
 *
 * The discarded candidates come straight off the row (`candidates`, kept
 * verbatim by the run), so offering them costs no re-plan. The optional
 * one-line **hint** rides the accept/move body into `archive_corrections` and
 * becomes a few-shot line in every later prompt (#158) — explained once, not
 * repeated.
 *
 * Two renderings of one report, like every other view here: the grid on a
 * wide screen (in the detail pane beside the Settings list since #397),
 * stacked cards with the actions behind a per-row disclosure under 768 px.
 * Both are built from the same row objects.
 *
 * This file is the composer: it builds the `ctx` its parts share (the caller's
 * `opts`, the looked-up elements, the state, the row menu, the two width
 * queries) and hands back the bootstrap's handle. Each part lives in
 * js/archive/<part>.js and takes `ctx` as its first argument; a call that would
 * make two parts import each other goes through a `ctx` slot.
 */

'use strict';

import { createRowMenu } from './_vendored/row-menu/row-menu.js';
import { refresh, refreshStatus, reload } from './js/archive/load.js';
import { startPolling } from './js/archive/run.js';
import { wireArchive } from './js/archive/wire.js';

const PHONE_MQ = '(max-width: 767px)';
//: Narrower than the grid→cards switch: the width at which the head's label
//: column, the long status wording and a full absolute path stop fitting on a
//: line (#168). The CSS phone block keys on the same 600px.
const NARROW_MQ = '(max-width: 600px)';

/**
 * Wire the Email archiving sheet once and hand back the bootstrap's handle.
 * @param {{onStatus: (archive: object|null) => void, onChanged: () => void}} opts
 *        `onStatus` publishes `GET /api/status`'s `archive` block so the Board's
 *        Inbox header can show what still needs a human; `onChanged` fires when
 *        a run or a review action has changed something outside this pane.
 * @returns {{refresh: () => Promise<void>, refreshStatus: () => Promise<void>}}
 */
export function mountArchive(opts) {
  const narrowMq = window.matchMedia(NARROW_MQ);
  const ctx = {
    opts: opts,
    els: {
      run: document.getElementById('archiveRun'),
      runLabel: document.getElementById('archiveRunLabel'),
      limit: document.getElementById('archiveLimit'),
      progress: document.getElementById('archiveProgress'),
      status: document.getElementById('statusArchive'),
      lastRun: document.getElementById('statusArchiveRun'),
      recent: document.getElementById('statusArchiveRecent'),
      recentLabel: document.getElementById('archiveRecentLabel'),
      pick: document.getElementById('archiveRunPick'),
      acceptAll: document.getElementById('archiveAcceptAll'),
      host: document.getElementById('archiveHost'),
    },
    narrowMq: narrowMq,
    phoneMq: window.matchMedia(PHONE_MQ),
    /** One line per reading, one word per label: this width has no room for the
     *  head's full sentences, and a wrapped status row costs three lines. */
    narrow: function () { return narrowMq.matches; },
    st: {
      status: null,    // GET /api/status → archive; null = the call itself failed
      runs: [],        // the picker's list, latest first
      run: null,       // the selected run WITH its items
      runId: null,
      poll: 0,         // setTimeout handle between two polls of a live run
      // Whether this pane is following a run *at all* — true across the gap where
      // `poll` is 0 because a tick is in flight. Re-opening the sheet mid-run must
      // not start a second chain that double-polls and double-toasts.
      polling: false,
      busy: false,     // a run or a review action is in flight
    },
    // The desktop rows' ⋮ menus (#350): one controller, at most one menu open.
    rowMenu: createRowMenu({ className: 'archive-row-menu' }),
    // the calls two parts would otherwise import from each other
    reload: function () { return reload(ctx); },
    startPolling: function () { startPolling(ctx); },
  };
  wireArchive(ctx);

  return {
    refresh: function () { return refresh(ctx); },
    refreshStatus: function () { return refreshStatus(ctx); },
  };
}
