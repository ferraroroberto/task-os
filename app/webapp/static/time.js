/* task-os — the Time tab: a time tracker with household shares.
 *
 * Three views in one segmented control, all over `/api/time/*`
 * (`src/time_repo.py` owns every rule; this file only draws and asks):
 *
 *   Log      today per person (the glance card), this device's running
 *            timer (Stop and save · Discard; past `long_timer_minutes` a
 *            "minutes to save" correction), the start list (Recent first,
 *            then by area — a tap starts, or offers Switch while one runs)
 *            and Add time already spent
 *   Totals   Today · 7 days · 30 days · All, an area filter and, outside the
 *            compare area, Me · Everyone; on the compare area with two or
 *            more people, the household comparison: head-to-head, the split
 *            bar, coverage, the guess card, the per-category bars. With two
 *            or more people it opens there, at 30 days (the prototype's
 *            Totals), and the comparison and the guess card stay up
 *            with nothing logged: only the bars give way to the empty state
 *   History  date-grouped rows, a filter above 12, "Show older entries";
 *            the row (and its menu's Edit) opens the editor, Start again,
 *            Delete last behind the confirm
 *
 * Nothing loads until the tab is first shown (`show()`), so Today's first
 * paint makes no `/api/time` call. While the tab is up the timers and today's
 * totals are re-read every POLL_MS, so a timer the other device started
 * appears without a reload. "Today" is always the server's.
 *
 * The tab logs as whoever is signed in: `/api/time/meta` says who
 * (`you`), so there is no per-device picker and nothing is stored. Only a
 * request that is no member (a team sign-in whose name matches nobody) is
 * asked once per visit, in memory. People are told apart by their initial and,
 * in the bars, by solid vs hatched fill — never a second hue.
 *
 * This file is the composer: it builds the `ctx` its parts share (the caller's
 * `opts`, the looked-up elements, the state, the row menu and the settings
 * sheets) and hands back the bootstrap's handle. Each part lives in
 * js/time/<part>.js and takes `ctx` as its first argument; a call that would
 * make two parts import each other goes through a `ctx` slot.
 */

'use strict';

import { createRowMenu } from './_vendored/row-menu/row-menu.js';
import { loadMeta } from './js/time/data.js';
import { headText, hide, rerender, show, showView, wireViews } from './js/time/frame.js';
import { addEntry, discardTimer, startTimer, stopTimer } from './js/time/timer.js';
import { loadTotals } from './js/time/totals.js';
import { mountTimeSettings } from './time-settings.js';

/**
 * @param {{onHead: () => void}} opts
 * @returns {{show: () => void, hide: () => void, headText: () => string,
 *            settingsShown: () => void, openSheet: (key: string) => void}}
 */
export function mountTime(opts) {
  const ctx = {
    opts: opts,
    els: {
      pane: document.getElementById('paneTime'),
      views: document.getElementById('timeViews'),
      picker: document.getElementById('timePicker'),
      log: document.getElementById('timeLog'),
      totals: document.getElementById('timeTotals'),
      history: document.getElementById('timeHistory'),
    },
    st: {
      meta: null,
      metaLoad: null,
      skew: 0,                 // server clock − this device's, from the last read
      today: null,             // the server's day
      now: null,               // the server's ISO time at the last read
      person: null,
      view: 'log',
      timers: [],
      todaySummary: null,      // everyone, today: the glance card and the header line
      recent: [],
      totals: { period: null, area: null, who: 'me' },   // null until the meta picks the defaults
      history: { items: [], total: 0, q: '' },
      shown: false,
      poll: null,
      tick: null,
      busy: false,
    },
    log: { glance: null, timer: null, start: null },
    historyMenu: createRowMenu({ className: 'time-menu' }),
    filterTimer: null,
    settings: null,
    // the calls two parts would otherwise import from each other
    rerender: function () { return rerender(ctx); },
    showView: function (view) { showView(ctx, view); },
    loadTotals: function () { return loadTotals(ctx); },
    startTimer: function (c) { return startTimer(ctx, c); },
    stopTimer: function () { return stopTimer(ctx); },
    discardTimer: function () { return discardTimer(ctx); },
    addEntry: function () { return addEntry(ctx); },
  };
  ctx.settings = mountTimeSettings({
    meta: function () { return ctx.st.meta; },
    onMetaChanged: function () { return loadMeta(ctx, true).then(function () { return rerender(ctx); }); },
  });
  wireViews(ctx);

  return {
    show: function () { show(ctx); },
    hide: function () { hide(ctx); },
    headText: function () { return headText(ctx); },
    /** Settings is up: its two Time rows read the meta, loaded on demand. */
    settingsShown: function () { loadMeta(ctx).then(function () { ctx.settings.render(); }).catch(function () {}); },
    openSheet: function (key) {
      loadMeta(ctx).then(function () { ctx.settings.openSheet(key); }).catch(function () {});
    },
  };
}
