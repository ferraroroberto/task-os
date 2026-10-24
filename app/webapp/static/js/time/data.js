/* task-os — the Time tab's reads: the meta, the live timers and today's totals,
 * and the lookups over what they returned. */

'use strict';

import { api, qs } from '../../api.js';

//: The per-device person key the first Time tab stored; ignored since sign-in names the person, and removed on the first read.
const STALE_PERSON_KEY = 'task-os.time.person';
//: The Totals periods, in order (an object would list 7 and 30 first).
export const PERIODS = [['today', 'Today'], ['7', '7 days'], ['30', '30 days'], ['all', 'All']];
export const PERIOD_LABELS = Object.fromEntries(PERIODS);

function dropStalePerson() {
  try { localStorage.removeItem(STALE_PERSON_KEY); } catch (_) { /* private mode */ }
}

export function loadMeta(ctx, force) {
  const st = ctx.st;
  if (st.metaLoad && !force) return st.metaLoad;
  st.metaLoad = api('/api/time/meta').then(function (meta) {
    st.meta = meta;
    st.today = meta.today;
    st.now = meta.now;
    st.skew = Date.parse(meta.now) - Date.now();
    const ids = meta.people.map(function (p) { return p.id; });
    dropStalePerson();
    st.person = ids.length === 1 ? ids[0] : (ids.indexOf(meta.you) >= 0 ? meta.you : st.person);
    if (st.totals.area === null) {
      // first read: the household comparison at 30 days when there is one, else everything at 7
      const compare = ids.length > 1 && meta.areas.some(function (a) { return a.slug === meta.compare_area; });
      st.totals.area = compare ? meta.compare_area : '';
      st.totals.period = compare ? '30' : '7';
    }
    if (st.totals.area && !meta.areas.some(function (a) { return a.slug === st.totals.area; })) st.totals.area = '';
    ctx.settings.render();
    return meta;
  }).catch(function (err) {
    st.metaLoad = null;
    throw err;
  });
  return st.metaLoad;
}

/** A person's name in a list that holds both people: the viewer's is marked. */
export function nameYou(ctx, id) {
  return id === ctx.st.person && !solo(ctx) ? nameOf(ctx, id) + ' (you)' : nameOf(ctx, id);
}

export function solo(ctx) { return !ctx.st.meta || ctx.st.meta.people.length < 2; }

export function nameOf(ctx, id) {
  const p = ctx.st.meta && ctx.st.meta.people.find(function (x) { return x.id === id; });
  return p ? p.name : id;
}

export function serverNow(ctx) { return Date.now() + ctx.st.skew; }

export function timerOf(ctx, person) {
  return ctx.st.timers.find(function (t) { return t.person === person; }) || null;
}

export function categoryById(ctx, id) {
  for (const a of ctx.st.meta.areas) {
    const c = a.categories.find(function (x) { return x.id === id; });
    if (c) return { area: a, category: c };
  }
  return null;
}

/** Re-read the running timers and today's totals (the poll's whole job). */
export async function refreshLive(ctx) {
  const st = ctx.st;
  const [timers, today] = await Promise.all([
    api('/api/time/timers'),
    api('/api/time/summary' + qs({ period: 'today' })),
  ]);
  st.timers = timers.items;
  st.now = timers.now;
  st.skew = Date.parse(timers.now) - Date.now();
  st.today = today.today;
  st.todaySummary = today;
  ctx.opts.onHead();
}

export async function refreshRecent(ctx) {
  const st = ctx.st;
  if (!st.person) { st.recent = []; return; }
  st.recent = (await api('/api/time/recent' + qs({ person: st.person }))).category_ids;
}
