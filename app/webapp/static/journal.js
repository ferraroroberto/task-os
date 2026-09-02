/* task-os — the done journal (#102): everything closed, grouped by day.
 *
 * A reading surface, not a working view: reverse-chronological, one flat
 * heading per local calendar day (`Fri 28 Aug · 5 done`), the shared task
 * row under it (rows.js — project, issue chip, breadcrumb tooltip, the status
 * select that reopens a task in place), newest day first. Friday afternoon it
 * answers "what actually happened this week"; the weekly review quotes it.
 *
 * Reached from the palette (*Journal*) and the Board's Done column head —
 * deliberately not a seventh tab: the bottom pill is the vendored nav
 * contract and the journal is read, not lived in. `#journal` deep-links it;
 * the shared filter card applies (project · person · text) with the status,
 * due, modified and sort controls hidden — the status is implicitly
 * done + cancelled (cancelled rows muted, the switch in the head drops
 * them), the order is the closing time.
 *
 * The page is a window of whole weeks ending today (`weeks` × 7 days);
 * "Show the week before" widens it. Whether anything older exists is a
 * separate probe (app.js) — `hasOlder` null means "not known", and an
 * unknown keeps the button: the end of the journal is only ever stated when
 * the server said so.
 *
 * Day grouping reads the first ten characters of `done_at` — a local
 * timestamp, the same rule as the Board's Done today — never UTC arithmetic.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { switchEl } from './_vendored/switch/switch.js';
import { fmtDay, todayISO } from './format.js';
import { rowList } from './rows.js';

/** [{day, items, done, cancelled}] by the local day of `done_at`, newest
 *  first. The list arrives ordered newest closing first (the API's done
 *  window flips the order), so one pass keeps the days in order; a row with
 *  no `done_at` (never expected — the window is over that column) lands in
 *  a trailing "(no date)" group rather than vanishing. */
export function groupByDay(items) {
  const groups = [];
  let last = null;
  (items || []).forEach(function (t) {
    const day = (t.done_at || '').slice(0, 10);
    if (!last || last.day !== day) {
      last = { day: day, items: [], done: 0, cancelled: 0 };
      groups.push(last);
    }
    last.items.push(t);
    if (t.status === 'cancelled') last.cancelled += 1; else last.done += 1;
  });
  return groups;
}

/** "Today · Tue 2 Sep" / "Yesterday · Mon 1 Sep" / "Fri 28 Aug". */
export function dayLabel(day, today) {
  const t = today || todayISO();
  if (!day) return 'No date';
  const y = new Date(t + 'T00:00:00');
  y.setDate(y.getDate() - 1);
  if (day === t) return 'Today · ' + fmtDay(day);
  if (day === todayISO(y)) return 'Yesterday · ' + fmtDay(day);
  return fmtDay(day);
}

function countText(done, cancelled) {
  const bits = [];
  if (done || !cancelled) bits.push(done + ' done');
  if (cancelled) bits.push(cancelled + ' cancelled');
  return bits.join(' · ');
}

/**
 * @param {HTMLElement} host
 * @param {Array<object>} items  the window's closed tasks, newest closing first
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onPatch?: (id:number, patch:object)=>Promise<any>}} handlers
 * @param {{today?: string, from: string, weeks: number, hasOlder: boolean|null,
 *          cancelled: boolean, onOlder: () => void, onCancelled: (on:boolean) => void}} opts
 */
export function renderJournal(host, items, handlers, opts) {
  const o = opts || {};
  const t = o.today || todayISO();
  const groups = groupByDay(items);
  host.innerHTML = '';

  const section = document.createElement('section');
  section.className = 'today journal';
  const head = document.createElement('div');
  head.className = 'today-head';
  const h = document.createElement('h2');
  h.className = 'today-title';
  h.innerHTML = icon('book-open');
  h.appendChild(document.createTextNode('Done journal'));
  head.appendChild(h);
  const meta = document.createElement('span');
  meta.className = 'today-counts';
  const done = groups.reduce(function (n, g) { return n + g.done; }, 0);
  const cancelled = groups.reduce(function (n, g) { return n + g.cancelled; }, 0);
  meta.textContent = countText(done, cancelled) + ' since ' + fmtDay(o.from);
  head.appendChild(meta);
  // cancelled: shown muted by default, one switch drops them (local, not URL)
  const toggle = document.createElement('label');
  toggle.className = 'journal-toggle';
  toggle.appendChild(document.createTextNode('cancelled'));
  toggle.appendChild(switchEl(!!o.cancelled, {
    label: 'Show cancelled tasks',
    onToggle: function (next) { if (o.onCancelled) o.onCancelled(next); },
  }));
  head.appendChild(toggle);
  section.appendChild(head);

  if (!groups.length) {
    section.appendChild(emptyStateEl('circle-check', 'Nothing closed since ' + fmtDay(o.from)));
  }
  groups.forEach(function (g) {
    const wrap = document.createElement('section');
    wrap.className = 'today-group journal-day';
    wrap.dataset.day = g.day;
    const title = document.createElement('h3');
    title.className = 'today-group-title';
    title.appendChild(document.createTextNode(dayLabel(g.day, t)));
    const n = document.createElement('span');
    n.className = 'today-group-count';
    n.textContent = countText(g.done, g.cancelled);
    title.appendChild(n);
    wrap.appendChild(title);
    const list = rowList(g.items, handlers, {});
    list.classList.add('today-list');
    wrap.appendChild(list);
    section.appendChild(wrap);
  });
  host.appendChild(section);

  const foot = document.createElement('div');
  foot.className = 'journal-foot';
  if (o.hasOlder === false) {
    const end = document.createElement('span');
    end.className = 'journal-end';
    end.textContent = 'That is everything — nothing closed before ' + fmtDay(o.from);
    foot.appendChild(end);
  } else {
    const older = document.createElement('button');
    older.type = 'button';
    older.className = 'button-surface journal-older';
    older.textContent = 'Show the week before';
    older.addEventListener('click', function () {
      older.disabled = true;
      if (o.onOlder) o.onOlder();
    });
    foot.appendChild(older);
  }
  host.appendChild(foot);
}
