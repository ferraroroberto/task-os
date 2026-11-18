/* task-os — the Today tab: every open task, by when it is due.
 *
 * Four horizons, nearest first (with the Table gone, Today is where
 * any open task is found, from the strip's text filter or one tap on a
 * horizon): what is due (≤ today, overdue first), Soon (tomorrow … +7 days),
 * Later (further out) and No date. The tab opens on what is due: those
 * rows come first with no header of their own, because the page header above
 * already names them ("2 overdue · 1 due today") — one header, one count. The
 * three after it are plain sections under the Board's own group header (an
 * `overline` name with its count): all open, always, nothing to fold, so the
 * whole list reads without a tap. Inside a horizon
 * the tasks are ONE flat list in the Board's order (rows.js `sortBoardItems`:
 * due day, then no project, then project A–Z, then title), so an earlier date
 * always sits above a later one whatever its project, recurring or not. The
 * project is the row's leading pill, and the assignee pill joins it in the
 * Everyone view, exactly as on the Board. Rows are the ONE task row (rows.js) — the
 * completion circle, the title over its meta line and the ⋯ menu, where Move… (every phrase, a date) lives. Flat hairline rows, no card wrapper. The list
 * arrives already narrowed to the scope switch's Mine · Issues · All (app.js,
 * scope.js). This is the phone's landing tab.
 *
 * The calendar lane (calendar.js) sits beside all of it on the desktop:
 * today's events from the private ICS address (opts.calendar — the
 * /api/today calendar group), so the day is read against real free time. It
 * is read-only and never filtered.
 *
 * Everything else is derived in the browser from the shared filtered list,
 * so the filter sheet (status · project · person · sort …) applies here like
 * on every other tab.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { calendarLane } from './calendar.js';
import { addDays, relDue, todayISO } from './format.js';
import { CLOSED, rowList, sortBoardItems } from './rows.js';

/** Split the list into the four horizons {due, week, later, nodate, counts}
 *  — exported for tests. Every task lands in exactly one. */
export function bucketToday(items, today, sort) {
  const t = today || todayISO();
  const weekEnd = addDays(t, 7);
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
    due: sortBoardItems(due, sort),
    week: sortBoardItems(week, sort),
    later: sortBoardItems(later, sort),
    nodate: sortBoardItems(nodate, sort),
    counts: {
      // A finished task a query brings in is never overdue or due today.
      overdue: due.filter(function (it) { return it.due < t && !CLOSED[it.status]; }).length,
      today: due.filter(function (it) { return it.due === t && !CLOSED[it.status]; }).length,
      week: week.length,
      later: later.length,
      nodate: nodate.length,
    },
  };
}

/** The page header's line on Today: the exceptions, named from the
 *  counts the horizons were drawn from, so the header and the list never
 *  disagree. Overdue and due today are the attention tone (the row's own due
 *  tone); with neither, the plain fact. One text node, not per-part spans
 *  unlike Board's and Settings' own tone-mapped exceptions, this
 *  line is always one sentence in one tone, and splitting it across spans
 *  measurably reflows the browser's text shaping at the word boundary
 *  (a sub-pixel kerning drift the gallery catches). Exported for tests.
 *  @param {{overdue: number, today: number}} counts  `bucketToday(...).counts`
 *  @returns {{text: string, attention: boolean}} */
export function headLine(counts) {
  const bits = [];
  if (counts.overdue) bits.push(counts.overdue + ' overdue');
  if (counts.today) bits.push(counts.today + ' due today');
  return bits.length ? { text: bits.join(' · '), attention: true } : { text: 'Nothing due today', attention: false };
}

/**
 * @param {HTMLElement} host
 * @param {Array<object>} items  the shared filtered list
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onToggleSelect?: (id:number)=>void}} handlers
 * @param {{sort?: string, today?: string, query?: string,
 *          calendar?: object|null, assignees?: Object<string,string>,
 *          selectable?: boolean, isSelected?: (id:number)=>boolean}} [opts]
 * @returns {{overdue: number, today: number, week: number, later: number, nodate: number}}
 *          the horizon counts drawn — the page header's exceptions line reads
 *          these, so the header and the list never disagree
 */
export function renderToday(host, items, handlers, opts) {
  const o = opts || {};
  const t = o.today || todayISO();
  const data = bucketToday(items, t, o.sort);
  const counts = data.counts;
  // The list scrolls inside its own box on a wide window (styles/today.css), and a re-render
  // replaces that box, so the position it was at is put back after the rows are drawn.
  const prevMain = host.querySelector('.today-main');
  const scrolled = prevMain ? prevMain.scrollTop : 0;
  host.innerHTML = '';
  // Tasks on the left, the calendar lane on the right (hidden < 1024 px) — and
  // no lane at all, the tasks full width, while no calendar is configured.
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
  section.setAttribute('aria-label', 'Due');

  // Under a text filter an empty section says the filter hid it, never "all
  // clear": the day may be full. The way forward is the box it names.
  const q = (o.query || '').trim();
  const noMatch = function (what) {
    return 'No task ' + what + ' matches “' + q + '” — change the filter text above';
  };
  if (!data.due.length) {
    // …with its way forward: a task due today
    section.appendChild(q ? emptyStateEl('search', noMatch('due today'))
      : emptyStateEl('circle-check', 'All clear', handlers.onAdd ? {
        actionLabel: 'Add a task for today', onAction: function () { handlers.onAdd({ due: t }); },
      } : undefined));
  } else {
    appendRows(section, data.due, handlers, o);
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
  if (scrolled) main.scrollTop = scrolled;
  return counts;
}

/** One horizon after the due rows: a section under the Board's group header
 *  (an `overline` name and its count, no rule, no chevron), always open. */
function horizon(cls, title, items, n, handlers, o, empty) {
  const section = document.createElement('section');
  section.className = 'today-horizon ' + cls;
  section.setAttribute('aria-label', title);
  const head = document.createElement('h3');
  head.className = 'today-horizon-head';
  const label = document.createElement('span');
  label.className = 'overline';
  label.textContent = title;
  const count = document.createElement('span');
  count.className = 'section-count';
  count.textContent = String(n);
  count.setAttribute('aria-label', n + (n === 1 ? ' task' : ' tasks'));
  head.append(label, count);
  section.appendChild(head);
  if (!items.length && empty) section.appendChild(empty);
  appendRows(section, items, handlers, o);
  return section;
}

/** One horizon's rows as one flat list. The project and (Everyone view) the
 *  assignee are the row's leading pills, the Board's own row options. */
function appendRows(host, items, handlers, o) {
  if (!items.length) return;
  const list = rowList(items, handlers, {
    pills: true, assignees: o.assignees,
    selectable: !!o.selectable, isSelected: o.isSelected,
  });
  list.classList.add('today-list');
  // The overdue / due-today tint on the whole row. The date comes off the
  // chip's `data-due` (rows.js) — the ISO value, stated as a value; reading it
  // out of the chip's tooltip is what this used to do, and it broke the moment
  // the tooltip gained a word.
  list.querySelectorAll('.trow').forEach(function (row) {
    const chip = row.querySelector('.trow-due');
    const rel = relDue(chip ? chip.dataset.due : '');
    if (rel.tone) row.classList.add('is-' + rel.tone);
  });
  host.appendChild(list);
}
