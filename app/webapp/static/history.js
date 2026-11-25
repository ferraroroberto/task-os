/* task-os — the History tab: what I changed, newest first.
 *
 * A reading view over `GET /api/history` (src/tasks/history.py owns the
 * feed: whose changes, the day of each, the kind of each, the grouping). One
 * overline per local day, a card of rows under it; a row is one task and the
 * run of consecutive changes made to it, its newest change on the meta line.
 * A row with more than one change expands (the trailing chevron) to list them
 * all; the row itself opens the task's drawer.
 *
 * The kind chips (All · Date moved · Closed/reopened · Status · Priority ·
 * Moved · Comments) re-read the feed with `kind=`, so the grouping is always
 * the server's over what is shown; the choice is remembered on this device.
 * The page is a window of days ending today; "Show the day before" widens it
 * up to the server's cap. Whether anything older exists is the server's
 * `older`, so the end of the history is only stated when it said so.
 *
 * Nothing loads until the tab is first shown, and nothing polls: the feed is
 * re-read when the tab is shown again and after any write (app.js).
 * A read that fails is its own state — the reason and Try again — never an
 * empty day.
 *
 * This file is the composer: it builds the `ctx` its parts share and owns the
 * one read; js/history/render.js draws, js/history/text.js words a change.
 */

'use strict';

import { api, qs } from './api.js';
import { addDays, todayISO } from './format.js';
import { render, renderKinds } from './js/history/render.js';
import { KINDS } from './js/history/text.js';

const KIND_KEY = 'task-os.history.kind';

function storedKind() {
  let k = null;
  try { k = localStorage.getItem(KIND_KEY); } catch (_) { /* private mode */ }
  return KINDS.some(function (x) { return x.key === k; }) ? k : 'all';
}

/** Read the feed for the window and kind; a newer read wins over a slower older one. */
async function load(ctx, opts) {
  const st = ctx.st;
  const seq = ++st.seq;
  const to = todayISO();
  try {
    const feed = await api('/api/history' + qs({ from: addDays(to, -(st.days - 1)), to: to, kind: st.kind }));
    if (seq !== st.seq) return;
    st.feed = feed;
    st.error = null;
  } catch (err) {
    if (seq !== st.seq) return;
    st.error = (err && err.message) || 'the server did not answer';
  }
  renderKinds(ctx);
  render(ctx);
  opts.onHead();
}

function headText(st) {
  if (st.error) return 'History unreadable';
  if (!st.feed) return '';
  const n = st.feed.counts.all;
  return n + (n === 1 ? ' change' : ' changes') + (st.days === 1 ? ' today' : ' in ' + st.days + ' days');
}

/**
 * @param {{onOpen: (id: number) => void, onHead: () => void}} opts
 * @returns {{show: () => void, hide: () => void, refresh: () => Promise<void>, headText: () => string}}
 */
export function mountHistory(opts) {
  const ctx = {
    els: { kinds: document.getElementById('historyKinds'), host: document.getElementById('historyHost') },
    st: { shown: false, kind: storedKind(), days: 1, feed: null, error: null, open: new Set(), seq: 0 },
    onOpen: opts.onOpen,
    load: function () { return load(ctx, opts); },
    pickKind: function (key) {
      if (ctx.st.kind === key) return;
      ctx.st.kind = key;
      try { localStorage.setItem(KIND_KEY, key); } catch (_) { /* private mode */ }
      ctx.st.open.clear();
      renderKinds(ctx);
      ctx.load();
    },
  };
  renderKinds(ctx);
  return {
    show: function () { ctx.st.shown = true; ctx.load(); },
    hide: function () { ctx.st.shown = false; },
    refresh: function () { return ctx.st.shown ? ctx.load() : Promise.resolve(); },
    headText: function () { return headText(ctx.st); },
  };
}
