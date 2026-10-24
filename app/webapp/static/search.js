/* task-os — the Search tab: one box over four indexes (Step 10).
 *
 * `mountSearch(box, host, opts)` wires the box (`#searchInput` + `#searchMeta`)
 * and renders `GET /api/search?q=` into `host` (#395, the full-app review's
 * Search plan):
 *   before a query   one hint line naming what the box searches, and the
 *                    kinds this install has not set up folded into one line
 *                    with a link to Settings — no group shells waiting empty
 *   with a query     one group per kind that has hits, Tasks · Folders ·
 *                    Emails · Issues in that order, each a flat section headed
 *                    by an `overline` with its count (the shared section
 *                    header, #391), open; every kind without hits — none
 *                    matched, all hidden by the filters or the scope, not set
 *                    up — folds into ONE line under them, so nothing goes
 *                    silent and nothing takes a card to say "nothing". A
 *                    kind that failed says so on its own line, in the danger
 *                    tone: that is a fault, not an empty result.
 *
 * Every hit is the ONE task row shape (rows.js, #48): a title line and one
 * muted meta line, no glyphs, no buttons.
 *   tasks    the shared row itself (status select, meta line) + the matched
 *            snippet, narrowed by the shared filter state and the scope
 *            switch (Mine · Issues · All) and sorted by it
 *   folders  name · full path — the title is a taskos:// link the per-PC
 *            opener opens on a PC; on the phone it shows the path to copy
 *   emails   subject · sender · date · folder — same link, the .msg opens
 *   issues   title · repo#N · state — the title opens the linked task when
 *            there is one, else the issue page
 * Keyboard: ↓ from the box focuses the first row; on rows ↑↓ move, Enter
 * opens, Esc / `/` go back to the box.
 *
 * Debounce 200 ms; a stale answer (an older query resolving late) is dropped.
 * The URL (?q=) is the caller's job (`opts.onQuery`).
 *
 * This file is the composer: it builds the `ctx` its parts share (the box, the
 * host, the fetch state) and hands back the tab's handle. Each part lives in
 * js/search/<part>.js and takes `ctx` as its first argument: text (the
 * wording), hits (one hit as a row), render (the idle view and the results),
 * load (debounce + fetch), keys (the keyboard).
 */

'use strict';

import { wireKeys } from './js/search/keys.js';
import { loadStatus, run } from './js/search/load.js';
import { render, renderIdle } from './js/search/render.js';

export { foldParts, markHtml } from './js/search/text.js';

/**
 * @param {HTMLElement} box   the search card (holds #searchInput + #searchMeta)
 * @param {HTMLElement} host  where the results render
 * @param {{onOpenTask: (id:number) => void, onQuery: (q:string) => void,
 *          filters: () => object, onStatus: (id:number, status:string) => Promise<any>,
 *          menu?: object}} opts   (menu: the Search tab's row menu, rowmenu.js — #311)
 */
export function mountSearch(box, host, opts) {
  const ctx = {
    box: box,
    host: host,
    opts: opts,
    input: box.querySelector('#searchInput'),
    meta: box.querySelector('#searchMeta'),
    timer: null,
    seq: 0,
    last: null,        // the last rendered result
    status: null,      // /api/search/status → adapters (idle view)
    hitByIdx: new Map(),
  };

  wireKeys(ctx);
  loadStatus(ctx);
  renderIdle(ctx);

  return {
    /** Set the box and run (used by the ?q= deep link and the palette). */
    setQuery(q) { ctx.input.value = q || ''; clearTimeout(ctx.timer); run(ctx, ctx.input.value); },
    getQuery() { return ctx.input.value.trim(); },
    focus() { ctx.input.focus(); ctx.input.select(); },
    /** The shared filters changed: re-apply them to the task hits. */
    refilter() { if (ctx.last) render(ctx, ctx.last); },
    /** Re-run the query on screen against the server (after a write), quietly. */
    rerun() { if (ctx.last) return run(ctx, ctx.input.value, true); return Promise.resolve(); },
    reloadStatus() { return loadStatus(ctx); },
  };
}
