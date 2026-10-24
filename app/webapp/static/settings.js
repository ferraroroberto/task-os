/* task-os — the Settings pane: what this install is and what it can reach.
 *
 * One module per view, like Board · Today · Search:
 * `mountSettings(opts)` looks up the pane's rows and sheets once, wires their
 * controls and returns the handle the bootstrap calls when something it owns
 * changes. The pane is five inset groups (#397, design.md `settings group`):
 * each row carries its state word — on · synced · indexed · off, in its tone
 * when it is an exception — and a chevron to its sheet (#settingsSheet), which
 * holds the card the row replaced, under the same ids. One sheet is up at a
 * time and the URL says which (`#settings/<key>`), so the bootstrap opens and
 * closes it (`showSheet` / `hideSheet`) and this module only asks
 * (`opts.onOpenSheet` / `opts.onCloseSheet`). Text size is changed in place.
 *
 *   Row actions    what each touch swipe on a task row runs and what the
 *                  row's ⋯ menu lists, in order (#311) — per device, from the
 *                  one action table; `opts.onRowActions` redraws the rows.
 *   Phone access   https + auth (Step 7) — how this connection came in and
 *                  what the install accepts; "Sign out on this device".
 *   Mirror/backup  the markdown mirror and the dated .db copies (Step 6).
 *   Issues         the issue provider's status (Step 8) + "Sync now". The
 *                  sync itself belongs to the bootstrap (the header ↻, the
 *                  drawer and the palette funnel through the same call), so
 *                  it arrives as `opts.onSyncIssues` and the status arrives
 *                  through `renderIssues(status)`.
 *   Capture        the flagged-email poller (#98) + "Check now". Unlike the
 *                  issue sync this card owns its own call, because nothing
 *                  else in the app triggers a capture pass.
 *   Archive        the batch archiver (#157–#159): where it lives and its
 *                  threshold. The rest of its sheet — the run, the report and
 *                  every review action — is archive.js's (a tab until #397).
 *   Calendar       the Today lane's private ICS feed (#96): its state (off ·
 *                  ok · address refused · unreachable · timed out · not a
 *                  calendar), the host it reads from — never the address —
 *                  and "Refresh now". The refresh answers the fresh group,
 *                  which the bootstrap pushes into Today (`opts.onCalendar`).
 *   Voice          whether a transcription endpoint is answering, and which
 *                  one (#92, #144: the hub — so parakeet — or the local
 *                  whisper fallback). The same status the quick-add mic
 *                  reads. No button: there is nothing to run on demand, only
 *                  somewhere to be up.
 *   AI             whether the local hub used by staged Inbox triage is
 *                  enabled and reachable, plus the configured model (#95).
 *   Search         which of the four indexes this install can query (Step 10);
 *                  the Search tab's own idle view is refreshed through
 *                  `opts.onSearchStatus`.
 *   Folder opener  the per-PC opener install command + the folder index
 *                  (Step 9), with "Reindex folders now".
 *
 * ONE `GET /api/status` feeds the access, mirror/backup, opener, capture, archive, calendar, voice and AI cards
 * (`refreshStatus()`); the search card has its own `GET /api/search/status`
 * (`refreshSearchStatus()`). An unreachable endpoint is its own visible
 * state — "unknown — <reason>" — never a stale "Loading…".
 *
 * The rows' words are the Settings header's line too (`headParts()`, #397):
 * the exceptions among them, else how many services are on.
 *
 * This file is the composer: it builds the `ctx` its parts share (the caller's
 * `opts`, the looked-up elements, the state words) and wires them. Each card
 * lives in js/settings/<part>.js and takes `ctx` as its first argument.
 */

'use strict';

import { wireSignOut } from './js/settings/access.js';
import { renderArchive } from './js/settings/archive.js';
import { wireCalendarRefresh } from './js/settings/calendar.js';
import { wireCaptureRunNow } from './js/settings/capture.js';
import { wirePaletteOpen, wireTextSize } from './js/settings/device.js';
import { lookupEls } from './js/settings/elements.js';
import { wireReindex } from './js/settings/folders.js';
import { renderIssues, wireIssueSyncNow } from './js/settings/issues.js';
import { wireMirrorEventsClear } from './js/settings/mirror.js';
import { wireRowActions } from './js/settings/rowactions.js';
import { refreshSearchStatus } from './js/settings/search.js';
import { createSheets } from './js/settings/sheets.js';
import { refreshStatus } from './js/settings/status.js';
import { headParts } from './js/settings/words.js';

/**
 * Wire the Settings pane once and hand back the bootstrap's handle.
 * @param {{onSyncIssues: () => Promise<any>, onSearchStatus: () => void,
 *          onOpenPalette: () => void, onRowActions?: () => void,
 *          onCaptured: () => void, onArchiveRun: () => void,
 *          onCalendar: (group: object) => void, onHead: () => void,
 *          onOpenSheet: (key: string) => void, onCloseSheet: () => void}} opts
 * @returns {{refreshStatus: () => Promise<void>, refreshSearchStatus: () => Promise<void>,
 *            renderArchive: (st: object|null) => void,
 *            renderIssues: (status: object|null) => void,
 *            showSheet: (key: string) => boolean, hideSheet: () => void,
 *            currentSheet: () => (string|null),
 *            headParts: () => Array<{text: string, tone: string}>}}
 */
export function mountSettings(opts) {
  const ctx = {
    opts: opts,
    els: lookupEls(),
    words: {},                 // the state word of each service row, by its value element's id
    statusFailed: false,       // the last GET /api/status failed: one "unknown", not nine
    refreshStatus: function () { return refreshStatus(ctx); },
  };

  wireSignOut(ctx);
  wireReindex(ctx);
  wireMirrorEventsClear(ctx);
  wireIssueSyncNow(ctx);
  wirePaletteOpen(ctx);
  wireTextSize(ctx);
  wireRowActions(ctx);
  wireCaptureRunNow(ctx);
  wireCalendarRefresh(ctx);
  const sheets = createSheets(ctx);

  return {
    refreshStatus: ctx.refreshStatus,
    renderArchive: function (st) { renderArchive(ctx, st); },
    refreshSearchStatus: function () { return refreshSearchStatus(ctx); },
    renderIssues: function (st) { renderIssues(ctx, st); },
    showSheet: sheets.showSheet,
    hideSheet: sheets.hideSheet,
    currentSheet: sheets.currentSheet,
    headParts: function () { return headParts(ctx); },
  };
}
