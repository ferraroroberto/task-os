/* task-os — the Today tab: every open task, by when it is due.
 *
 * Four horizons, nearest first (#350 — with the Table gone, Today is where
 * any open task is found, by scrolling or by the filter card's text): Today
 * (due ≤ today, overdue first), Soon (tomorrow … +7 days), Later (further
 * out) and No date. Each horizon is headed by an `overline` section header
 * with its count (#391); the three after Today sit open below as flat
 * disclosures, each collapsible via its own chevron (#253). Inside a horizon
 * the tasks are grouped by root project with the shared due-first sort inside
 * each group (#116 — a task's date always decides its position, recurring or
 * not), and the project sub-headers are drawn only when there are two or more
 * groups to tell apart (#391, decision 6 of #390): a lone "No project" header
 * separated nothing. Rows are the ONE task row (rows.js, issue #46) — the
 * completion circle, the title over its meta line (the project hidden only
 * where a sub-header already names it) and the ⋯ menu, where Snooze… and
 * Change date… live since #311. Flat hairline rows, no card wrapper. The list
 * arrives already narrowed to the scope switch's Mine · Issues · All (app.js,
 * scope.js). This is the phone's landing tab.
 *
 * The calendar lane (#96, calendar.js) sits beside all of it on the desktop:
 * today's events from the private ICS address (opts.calendar — the
 * /api/today calendar group), so the day is read against real free time. It
 * is read-only and never filtered.
 *
 * Everything else is derived in the browser from the shared filtered list,
 * so the filter card (status · project · person · sort …) applies here like
 * on every other tab.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { calendarLane } from './calendar.js';
import { collapsibleCard } from './collapsible.js';
import { relDue, todayISO } from './format.js';
import { compareItems, rowList } from './rows.js';

/** Split the list into the four horizons {due, week, later, nodate, counts}
 *  — exported for tests. Every task lands in exactly one. */
export function bucketToday(items, today, sort) {
  const t = today || todayISO();
  const end = new Date(t + 'T00:00:00');
  end.setDate(end.getDate() + 7);
  const weekEnd = todayISO(end);
  const due = [];
  const week = [];
  const later = [];
  const nodate = [];
  (items || []).forEach(function (it) {
    if (!it.due) nodate.push(it);
    else if (it.due <= t) due.push(it);
    else if (it.due <= weekEnd) week.push(it);
    else later.push(it);
  });
  return {
    today: t,
    due: groupByRoot(due, sort),
    week: groupByRoot(week, sort),
    later: groupByRoot(later, sort),
    nodate: groupByRoot(nodate, sort),
    counts: {
      overdue: due.filter(function (it) { return it.due < t; }).length,
      today: due.filter(function (it) { return it.due === t; }).length,
      week: week.length,
      later: later.length,
      nodate: nodate.length,
    },
  };
}

/** [{root, items}] — by top ancestor (null = no project); groups ordered by
 *  earliest due then title; inside a group, the shared sort — same as every
 *  other view, so editing a task's due date always reorders it correctly
 *  relative to its group-mates, recurring or not (#116). */
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
    g.items.sort(cmp);
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
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onToggleSelect?: (id:number)=>void}} handlers
 * @param {{sort?: string, today?: string, query?: string,
 *          calendar?: object|null,
 *          selectable?: boolean, isSelected?: (id:number)=>boolean}} [opts]
 */
export function renderToday(host, items, handlers, opts) {
  const o = opts || {};
  const t = o.today || todayISO();
  const data = bucketToday(items, t, o.sort);
  host.innerHTML = '';
  const counts = data.counts;
  // Tasks on the left, the calendar lane on the right (hidden < 1024 px) — and
  // no lane at all, the tasks full width, while no calendar is configured (#320).
  const layout = document.createElement('div');
  layout.className = 'today-layout';
  const main = document.createElement('div');
  main.className = 'today-main';
  layout.appendChild(main);
  const lane = calendarLane(o.calendar || null);
  if (lane) {
    layout.classList.add('has-cal');
    layout.appendChild(lane);
  }
  host.appendChild(layout);

  const section = document.createElement('section');
  section.className = 'today';
  const head = document.createElement('div');
  head.className = 'today-head';
  const h = document.createElement('h2');
  h.className = 'today-title overline';
  h.textContent = 'Today';
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

  // Under a text filter an empty section says the filter hid it, never "all
  // clear": the day may be full (#339). The way forward is the box it names.
  const q = (o.query || '').trim();
  const noMatch = function (what) {
    return 'No task ' + what + ' matches “' + q + '” — change the filter text above';
  };
  if (!data.due.length) {
    // …with its way forward (#339): a task due today
    section.appendChild(q ? emptyStateEl('search', noMatch('due today'))
      : emptyStateEl('circle-check', 'Nothing due today — all clear', handlers.onAdd ? {
        actionLabel: 'Add a task for today', onAction: function () { handlers.onAdd({ due: t }); },
      } : undefined));
  } else {
    appendGroups(section, data.due, handlers, o);
  }
  main.appendChild(section);

  // Soon always shows, with its way forward when it is empty; Later and No
  // date only when they hold something — an empty far horizon says nothing.
  main.appendChild(horizon('today-soon', 'Soon', data.week, counts.week, handlers, o,
    q ? emptyStateEl('search', noMatch('due in the next seven days'))
      : emptyStateEl('calendar-days', 'Nothing due in the next seven days', handlers.onAdd ? {
        actionLabel: 'Add a task', onAction: function () { handlers.onAdd(); },
      } : undefined)));
  if (counts.later) main.appendChild(horizon('today-far', 'Later', data.later, counts.later, handlers, o));
  if (counts.nodate) main.appendChild(horizon('today-nodate', 'No date', data.nodate, counts.nodate, handlers, o));
}

/** One horizon after Today — a flat disclosure (vendored markup, hairline
 *  instead of a card box). Open by default (#253): renderToday rebuilds the
 *  host from scratch every call, so there is no user-toggle state to keep,
 *  and every open task stays reachable by scrolling (#350). */
function horizon(cls, title, groups, n, handlers, o, empty) {
  const card = collapsibleCard({
    className: 'disclosure-flat today-horizon ' + cls, title: title, titleClass: 'overline',
    count: String(n), countClass: 'section-count',
  });
  card.count.setAttribute('aria-label', n + (n === 1 ? ' task' : ' tasks'));
  card.card.open = true;
  if (!groups.length && empty) card.body.appendChild(empty);
  appendGroups(card.body, groups, handlers, o);
  return card.card;
}

/** One horizon's project groups. A sub-header only separates, so it is drawn
 *  only when there are two or more groups; with one, the rows name their own
 *  project on the meta line instead (#391). */
function appendGroups(host, groups, handlers, o) {
  const headed = groups.length >= 2;
  groups.forEach(function (g) { host.appendChild(buildGroup(g, handlers, o, headed)); });
}

function buildGroup(group, handlers, o, headed) {
  const wrap = document.createElement('section');
  wrap.className = 'today-group' + (headed ? '' : ' is-unheaded');
  const rootId = group.root ? group.root.id : null;
  wrap.dataset.root = rootId == null ? '' : String(rootId);
  if (headed) wrap.appendChild(groupTitle(group, handlers));
  const list = rowList(group.items, handlers, {
    hideProject: headed,
    selectable: !!(o && o.selectable), isSelected: o && o.isSelected,
  });
  list.classList.add('today-list');
  // The overdue / due-today tint on the whole row. The date comes off the
  // chip's `data-due` (rows.js) — the ISO value, stated as a value; reading it
  // out of the chip's tooltip is what this used to do, and it broke the moment
  // the tooltip gained a word (#107).
  list.querySelectorAll('.trow').forEach(function (row) {
    const chip = row.querySelector('.trow-due');
    const rel = relDue(chip ? chip.dataset.due : '');
    if (rel.tone) row.classList.add('is-' + rel.tone);
  });
  wrap.appendChild(list);
  return wrap;
}

/** A project sub-header: the root's name (it opens the project) and its count. */
function groupTitle(group, handlers) {
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
  return title;
}
