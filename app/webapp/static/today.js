/* task-os — the Today tab: what is due, from the shared list.
 *
 * Tasks due ≤ today (overdue first, then today), grouped by root project
 * with recurring tasks first inside each group; "Later this week"
 * (tomorrow … +7 days) sits collapsed below as a flat disclosure. Rows are
 * the ONE task row (rows.js, issue #46) — title + status select (the Board
 * control; the old checkbox is gone), the meta line (project hidden — the
 * group already names it). Flat hairline rows, no card wrapper, group
 * titles in the app's normal title font. This is the phone's landing tab.
 *
 * Everything is derived in the browser from the shared filtered list, so the
 * filter card (status · project · person · sort …) applies here like on
 * every other tab.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { relDue, todayISO } from './format.js';
import { compareItems, rowList } from './rows.js';

/** Split the list into {due, week, counts} — exported for tests. */
export function bucketToday(items, today, sort) {
  const t = today || todayISO();
  const end = new Date(t + 'T00:00:00');
  end.setDate(end.getDate() + 7);
  const weekEnd = todayISO(end);
  const due = [];
  const week = [];
  (items || []).forEach(function (it) {
    if (!it.due) return;
    if (it.due <= t) due.push(it);
    else if (it.due <= weekEnd) week.push(it);
  });
  return {
    today: t,
    due: groupByRoot(due, sort),
    week: groupByRoot(week, sort),
    counts: {
      overdue: due.filter(function (it) { return it.due < t; }).length,
      today: due.filter(function (it) { return it.due === t; }).length,
      week: week.length,
    },
  };
}

/** [{root, items}] — by top ancestor (null = no project); groups ordered by
 *  earliest due then title; inside a group recurring tasks first, then the
 *  shared sort. */
function groupByRoot(items, sort) {
  const cmp = compareItems(sort || 'due');
  const groups = new Map();
  items.forEach(function (it) {
    const key = it.root ? it.root.id : null;
    if (!groups.has(key)) groups.set(key, { root: it.root || null, items: [] });
    groups.get(key).items.push(it);
  });
  const out = Array.from(groups.values());
  out.forEach(function (g) {
    g.items.sort(function (a, b) { return ((a.recurrence ? 0 : 1) - (b.recurrence ? 0 : 1)) || cmp(a, b); });
  });
  out.sort(function (a, b) {
    const ad = a.items.reduce(function (m, it) { return m == null || it.due < m ? it.due : m; }, null) || '';
    const bd = b.items.reduce(function (m, it) { return m == null || it.due < m ? it.due : m; }, null) || '';
    return ad.localeCompare(bd) || ((a.root ? a.root.title : '').localeCompare(b.root ? b.root.title : ''));
  });
  return out;
}

/**
 * @param {HTMLElement} host
 * @param {Array<object>} items  the shared filtered list
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>}} handlers
 * @param {{sort?: string, today?: string}} [opts]
 */
export function renderToday(host, items, handlers, opts) {
  const o = opts || {};
  const data = bucketToday(items, o.today, o.sort);
  host.innerHTML = '';
  const counts = data.counts;

  const section = document.createElement('section');
  section.className = 'today';
  const head = document.createElement('div');
  head.className = 'today-head';
  const h = document.createElement('h2');
  h.className = 'today-title';
  h.innerHTML = icon('calendar-days');
  h.appendChild(document.createTextNode('Today'));
  head.appendChild(h);
  const meta = document.createElement('span');
  meta.className = 'today-counts';
  const bits = [];
  if (counts.overdue) bits.push(counts.overdue + ' overdue');
  if (counts.today) bits.push(counts.today + ' due today');
  meta.textContent = bits.length ? bits.join(' · ') : 'nothing due';
  if (counts.overdue) meta.classList.add('has-overdue');
  head.appendChild(meta);
  section.appendChild(head);

  if (!data.due.length) {
    section.appendChild(emptyStateEl('circle-check', 'Nothing due today — all clear'));
  } else {
    data.due.forEach(function (g) { section.appendChild(buildGroup(g, handlers)); });
  }
  host.appendChild(section);

  // Later this week — a flat disclosure (vendored markup, hairline instead of a card box).
  const later = document.createElement('details');
  later.className = 'card card--collapsible disclosure-flat today-later';
  const summary = document.createElement('summary');
  summary.className = 'collapse-summary';
  const main = document.createElement('span');
  main.className = 'collapse-main';
  main.innerHTML = icon('calendar-days');
  const st = document.createElement('h3');
  st.className = 'collapse-title';
  st.textContent = 'Later this week';
  main.appendChild(st);
  const sc = document.createElement('span');
  sc.className = 'collapse-count';
  sc.textContent = counts.week + (counts.week === 1 ? ' task' : ' tasks');
  main.appendChild(sc);
  summary.appendChild(main);
  const chev = document.createElement('span');
  chev.className = 'collapse-chevron';
  chev.setAttribute('aria-hidden', 'true');
  chev.textContent = '›';
  summary.appendChild(chev);
  later.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'collapse-body';
  if (!data.week.length) {
    body.appendChild(emptyStateEl('calendar-days', 'Nothing due in the next seven days'));
  } else {
    data.week.forEach(function (g) { body.appendChild(buildGroup(g, handlers)); });
  }
  later.appendChild(body);
  host.appendChild(later);
}

function buildGroup(group, handlers) {
  const wrap = document.createElement('section');
  wrap.className = 'today-group';
  const rootId = group.root ? group.root.id : null;
  wrap.dataset.root = rootId == null ? '' : String(rootId);
  const title = document.createElement('h3');
  title.className = 'today-group-title';
  if (group.root) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'today-group-link';
    btn.textContent = group.root.title;
    btn.addEventListener('click', function () { handlers.onOpen(group.root.id); });
    title.appendChild(btn);
  } else {
    title.textContent = 'No project';
    title.classList.add('is-loose');
  }
  const n = document.createElement('span');
  n.className = 'today-group-count';
  n.textContent = String(group.items.length);
  title.appendChild(n);
  wrap.appendChild(title);
  const list = rowList(group.items, handlers, { hideProject: true });
  list.classList.add('today-list');
  list.querySelectorAll('.trow').forEach(function (row) {
    const rel = relDue(row.querySelector('.trow-due') ? row.querySelector('.trow-due').title : '');
    if (rel.tone) row.classList.add('is-' + rel.tone);
  });
  wrap.appendChild(list);
  return wrap;
}
