/* task-os — Search: the fetch side. Debounce the box, ask `GET /api/search?q=`,
 * drop a stale answer (an older query resolving late), and read the per-index
 * status the idle view names the unset kinds from. Takes the composer's `ctx`
 * first (`input`, `meta`, `host`, `opts`, and the `timer` / `seq` / `last` /
 * `status` state it keeps). */

'use strict';

import { api } from '../../api.js';
import { note, render, renderIdle } from './render.js';

const DEBOUNCE_MS = 200;
const LIMIT = 20;

export function schedule(ctx) {
  clearTimeout(ctx.timer);
  ctx.timer = setTimeout(function () { run(ctx, ctx.input.value); }, DEBOUNCE_MS);
}

// `quiet` = a re-read of the query already on screen after a write: no
// "searching…" flash, and a failure keeps the rows that are showing.
export async function run(ctx, raw, quiet) {
  const q = String(raw || '').trim();
  if (!quiet) ctx.opts.onQuery(q);
  const my = ++ctx.seq;
  if (!q) { ctx.last = null; renderIdle(ctx); return; }
  if (!quiet) ctx.meta.textContent = 'searching…';
  let res;
  try {
    res = await api('/api/search?q=' + encodeURIComponent(q) + '&limit=' + LIMIT);
  } catch (err) {
    if (my !== ctx.seq || quiet) return;
    ctx.meta.textContent = 'search failed';
    ctx.host.replaceChildren(note('search-err', err.message || 'Search failed'));
    return;
  }
  if (my !== ctx.seq) return;               // a newer query is in flight / rendered
  ctx.last = res;
  render(ctx, res);
}

export async function loadStatus(ctx) {
  try { ctx.status = (await api('/api/search/status')).adapters || []; } catch (_) { ctx.status = null; }
  if (!ctx.input.value.trim()) renderIdle(ctx);
}
