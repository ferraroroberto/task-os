/* task-os — the Board tab: a week planner, with the status columns behind a segment.
 *
 * Two modes over the one shared list, picked by the Week · Status segment
 * (the vendored segmented control) and remembered on this device (#396,
 * decision 2 of #390):
 *
 *   Week    the default. Lanes by due date — Today (overdue included, as on
 *           the Today tab) · Tomorrow · This week · This weekend · Next week ·
 *           Later · No date (`weekLanes`). A week runs Monday to Sunday, and
 *           on a Sunday "this week" is the one tomorrow starts. This week is
 *           there only while days sit between tomorrow and Saturday, This
 *           weekend only while a weekend day comes after tomorrow, so every
 *           date has exactly one lane. Dropping a row on a lane re-dates it to
 *           the lane's first day (No date clears it) through the one row
 *           action runner — the same write, toast and Undo as the date sheet's
 *           Move — and changes nothing else.
 *   Status  Inbox · Todo · Standby · Done — the first three are the open
 *           statuses; Done shows the tasks completed on the current local day
 *           (older done tasks never show unless the filter sheet's "done"
 *           status is ticked, which turns the column into plain Done).
 *           Dropping a row on a column changes its status.
 *
 * In both modes an empty lane collapses: on the desktop to its header alone
 * (still a drop target), on the phone out of the way entirely. On a wide
 * screen the lanes sit side by side as flat regions split by a vertical
 * hairline (ported from the fleet launcher's board). On the phone Week mode
 * is one scrolling list of lane sections — no drag there, the row's swipe and
 * menu move a task — and Status mode is a scroll-snap carousel (one column
 * per swipe) under a strip that doubles as column switcher + counts. The
 * lane skeleton of each mode is built once and every refresh only swaps the
 * rows, so the carousel position survives.
 *
 * Rows are the ONE task row (rows.js, issue #46) — the same row Today and
 * Search render. The list arrives already narrowed to the scope switch's
 * Mine · Issues · All (app.js, scope.js).
 *
 * The AI triage action (#95) works on the Inbox column, so it sits on the
 * mode line in Status mode while the Inbox has tasks, never in a lane head.
 * The pointer at the Archive tab that used to sit there is gone: the tab and
 * the palette's Go to Archive hint already carry the last run's count.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { fmtDay, todayISO } from './format.js';
import { CLOSED, sortItems, taskRow } from './rows.js';

export const BOARD_COLUMNS = [
  { key: 'inbox', label: 'Inbox', short: 'Inbox' },
  { key: 'todo', label: 'Todo', short: 'Todo' },
  { key: 'standby', label: 'Standby', short: 'Standby' },
  { key: 'done', label: 'Done today', short: 'Done' },
];
/** [mode, the segment's label]; the first is the default. */
export const BOARD_MODES = [['week', 'Week'], ['status', 'Status']];
const MODE_KEY = 'task-os.board.mode';
const PHONE_MQ = '(max-width: 1023px)';
// Every lane key Week mode can draw, in order: the skeleton holds all seven
// and `weekLanes` says which of them today's calendar has.
const WEEK_KEYS = ['today', 'tomorrow', 'week', 'weekend', 'next', 'later', 'nodate'];

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + n);
  return todayISO(d);
}

/**
 * Week mode's lanes on `today`, nearest first — exported for tests.
 * Each lane holds the due dates `from`…`to` (inclusive ISO; null = open
 * ended) and `drop` is what a row dropped on it is re-dated to: the lane's
 * first day, Today's for the Today lane, null (no date) for No date. A lane
 * whose range is empty on this weekday is left out, so a date always has
 * exactly one lane.
 * @param {string} [today]  ISO day; the browser's today by default
 * @returns {Array<{key: string, label: string, from: ?string, to: ?string, drop: ?string}>}
 */
export function weekLanes(today) {
  const t = today || todayISO();
  const tomorrow = addDays(t, 1);
  // the week tomorrow belongs to ends on its Sunday (0 = Sunday)
  const sunday = addDays(tomorrow, (7 - new Date(tomorrow + 'T00:00:00').getDay()) % 7);
  const saturday = addDays(sunday, -1);
  const afterTomorrow = addDays(t, 2);
  const lanes = [
    { key: 'today', label: 'Today', from: null, to: t, drop: t },
    { key: 'tomorrow', label: 'Tomorrow', from: tomorrow, to: tomorrow },
    { key: 'week', label: 'This week', from: afterTomorrow, to: addDays(saturday, -1) },
    { key: 'weekend', label: 'This weekend', from: afterTomorrow > saturday ? afterTomorrow : saturday, to: sunday },
    { key: 'next', label: 'Next week', from: addDays(sunday, 1), to: addDays(sunday, 7) },
    { key: 'later', label: 'Later', from: addDays(sunday, 8), to: null },
    { key: 'nodate', label: 'No date', from: null, to: null, drop: null },
  ];
  return lanes.filter(function (l) { return !l.from || !l.to || l.from <= l.to; }).map(function (l) {
    return Object.assign({}, l, { drop: 'drop' in l ? l.drop : l.from });
  });
}

/** The lane key a due date falls in, against `weekLanes(today)`'s answer. */
export function laneOf(due, lanes) {
  if (!due) return 'nodate';
  const lane = lanes.find(function (l) {
    return l.key !== 'nodate' && (!l.from || due >= l.from) && (!l.to || due <= l.to);
  });
  return lane ? lane.key : 'nodate';
}

/** A lane's dates in words, for its header's tooltip. */
function laneSpan(lane) {
  if (lane.key === 'nodate') return 'Tasks without a due date';
  if (lane.key === 'today') return 'Due today or overdue';
  if (!lane.to) return 'From ' + fmtDay(lane.from);
  return lane.from === lane.to ? fmtDay(lane.from) : fmtDay(lane.from) + ' – ' + fmtDay(lane.to);
}

/**
 * The page header's line on the Board (#396, design.md `page-header`): Inbox
 * arrivals in the accent, then what is overdue or due today in the attention
 * tone — at most two parts, from the very counts the lanes were drawn from.
 * With neither, the plain fact. Exported for tests.
 * @param {{inbox: number, overdue: number, today: number}} counts
 * @returns {Array<{text: string, tone: string}>}  tone: accent | attention | muted
 */
export function boardHeadParts(counts) {
  const parts = [];
  if (counts.inbox) parts.push({ text: counts.inbox + ' in Inbox', tone: 'accent' });
  if (counts.overdue) parts.push({ text: counts.overdue + ' overdue', tone: 'attention' });
  if (counts.today) parts.push({ text: counts.today + ' due today', tone: 'attention' });
  return parts.length ? parts.slice(0, 2) : [{ text: 'Nothing due today', tone: 'muted' }];
}

function readMode() {
  let stored = null;
  try { stored = localStorage.getItem(MODE_KEY); } catch (_) { /* private mode */ }
  return BOARD_MODES.some(function (m) { return m[0] === stored; }) ? stored : BOARD_MODES[0][0];
}

/**
 * Build both modes' skeletons once; `render(items, filters)` swaps the rows.
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>,
 *          onDue: (id:number, due:?string)=>Promise<any>, onTriage: ()=>Promise<any>,
 *          onAdd?: ()=>void, onModeChange?: ()=>void}} handlers
 * @param {HTMLElement} barHost  the pane line under the strip, beside the
 *          scope switch: the Week · Status segment and Triage go there
 * @returns {{el: HTMLElement, render: (items: Array<object>, filters: object, opts?: object) =>
 *           {inbox: number, overdue: number, today: number}, show: () => void}}
 */
export function mountBoard(handlers, barHost) {
  const el = document.createElement('div');
  el.className = 'board';
  let mode = readMode();
  let last = null;   // the last render's arguments, to redraw on a mode switch

  // The mode line: Week · Status, then (Status mode, Inbox not empty) Triage.
  const modes = document.createElement('div');
  modes.className = 'segmented board-modes';
  modes.setAttribute('role', 'group');
  modes.setAttribute('aria-label', 'Board layout');
  BOARD_MODES.forEach(function (m) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'segmented-item';
    b.dataset.mode = m[0];
    b.textContent = m[1];
    modes.appendChild(b);
  });
  modes.addEventListener('click', function (ev) {
    const seg = ev.target.closest('.segmented-item');
    if (!seg || seg.dataset.mode === mode) return;
    mode = seg.dataset.mode;
    try { localStorage.setItem(MODE_KEY, mode); } catch (_) { /* private mode */ }
    if (last) render(last[0], last[1], last[2]);
    if (handlers.onModeChange) handlers.onModeChange();
    requestAnimationFrame(function () { status.place(false); });
  });
  const triage = triageButton(handlers);
  barHost.append(modes, triage);

  const week = mountLanes('week', WEEK_KEYS.map(function (k) { return { key: k }; }), handlers);
  const status = mountLanes('status', BOARD_COLUMNS, handlers);
  // Status mode on the phone: one count button per column, the carousel's switcher.
  el.append(status.strip, week.columns, status.columns);

  const empty = document.createElement('div');
  empty.className = 'board-empty';
  el.appendChild(empty);

  /**
   * @param {Array<object>} items   the shared filtered list in the scope (done = done today unless the done pill is pressed)
   * @param {object} filters        {status: [...], sort}
   * @param {{selectable?: boolean, isSelected?: (id:number)=>boolean,
   *          ai?: object, triaging?: boolean, suggestions?: object}} [opts]
   * @returns {{inbox: number, overdue: number, today: number}}  the header line's counts
   */
  function render(items, filters, opts) {
    last = [items, filters, opts];
    const o = opts || {};
    const f = filters || { status: [], sort: 'due' };
    const t = todayISO();
    modes.querySelectorAll('.segmented-item').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
    });
    el.dataset.mode = mode;
    week.columns.hidden = mode !== 'week';
    status.columns.hidden = mode !== 'status';
    status.strip.hidden = mode !== 'status';

    const all = items || [];
    // What the lanes hold: the open tasks — and, in Status mode, today's done
    // ones too, for the Done column. A ticked status shows what it picked.
    const open = f.status.length ? all : all.filter(function (x) { return !CLOSED[x.status]; });
    const counts = {
      inbox: open.filter(function (x) { return x.status === 'inbox'; }).length,
      overdue: open.filter(function (x) { return x.due && x.due < t; }).length,
      today: open.filter(function (x) { return x.due === t; }).length,
    };

    const rowOpts = { selectable: !!o.selectable, isSelected: o.isSelected, suggestions: o.suggestions, mode: mode };
    let shown = 0;
    // Only the mode on screen holds rows: a task is one row in the pane, so
    // the keymap, the selection marks and a new task's focus find that one.
    (mode === 'week' ? status : week).clear();
    if (mode === 'week') {
      const lanes = weekLanes(t);
      const byLane = {};
      WEEK_KEYS.forEach(function (k) { byLane[k] = []; });
      open.forEach(function (x) { byLane[laneOf(x.due, lanes)].push(x); });
      week.fill(WEEK_KEYS.map(function (k) {
        const lane = lanes.find(function (l) { return l.key === k; });
        return lane ? { key: k, label: lane.label, title: laneSpan(lane), drop: lane.drop, rows: byLane[k] } : null;
      }), f.sort, rowOpts);
      shown = open.length;
    } else {
      const byStatus = {};
      BOARD_COLUMNS.forEach(function (c) { byStatus[c.key] = []; });
      all.forEach(function (x) { if (byStatus[x.status]) byStatus[x.status].push(x); });
      const wantsDone = f.status.indexOf('done') >= 0;
      // Only a REAL status pill narrows which columns show — a pseudo-value
      // ticked alone (`deferred` #87, `blocked` #100) is not a column key, so
      // treating it as one hid every column instead of leaving all four up and
      // letting the (already server-filtered) items land in their own status.
      const realStatuses = f.status.filter(function (s) {
        return BOARD_COLUMNS.some(function (c) { return c.key === s; });
      });
      status.fill(BOARD_COLUMNS.map(function (col) {
        if (realStatuses.length && realStatuses.indexOf(col.key) < 0) return null;
        const label = col.key === 'done' && wantsDone ? 'Done' : col.label;
        return { key: col.key, label: label, title: label, drop: col.key, rows: byStatus[col.key] };
      }), f.sort, rowOpts);
      shown = BOARD_COLUMNS.reduce(function (n, c) { return n + byStatus[c.key].length; }, 0);
    }

    // Every lane collapsed: one way forward instead of a row of bare headers.
    empty.hidden = shown > 0;
    if (!shown) {
      empty.replaceChildren(emptyStateEl('square-kanban', 'Nothing on the board', handlers.onAdd ? {
        actionLabel: 'Add a task', onAction: function () { handlers.onAdd(); },
      } : undefined));
    }

    const ai = o.ai || {};
    triage.hidden = mode !== 'status' || counts.inbox === 0;
    triage.disabled = !ai.enabled || !!o.triaging;
    triage.dataset.state = o.triaging ? 'loading' : ai.enabled ? 'ready' : 'error';
    triage.title = o.triaging ? 'Generating suggestions…'
      : !ai.enabled ? (ai.reason || 'AI triage unavailable') : 'Stage AI suggestions for every Inbox task';
    triage.querySelector('span').textContent = o.triaging ? 'Triaging…'
      : !ai.enabled ? (ai.configured ? 'AI unavailable' : 'Triage off') : 'Triage Inbox';
    if (mode === 'status') status.place(false, true);
    return counts;
  }

  return {
    el: el,
    render: render,
    // The pane was hidden until now — position the carousel on the remembered
    // column once it has layout (no animation on arrival).
    show: function () { requestAnimationFrame(function () { status.place(false); }); },
  };
}

// ------------------------------------------------------------------ lanes
/**
 * One mode's lanes: the columns container, the phone strip (Status mode's
 * carousel switcher) and the drop targets, built once.
 * `fill(lanes, sort, rowOpts)` takes one entry per skeleton lane, in order —
 * `{key, label, title, drop, rows}`, or null for a lane this calendar or the
 * status filter does not have.
 */
function mountLanes(kind, skeleton, handlers) {
  const columns = document.createElement('div');
  columns.className = 'board-columns board-' + kind;
  const strip = document.createElement('div');
  strip.className = 'board-strip';
  strip.setAttribute('role', 'tablist');
  strip.setAttribute('aria-label', 'Board columns');
  const parts = {};
  let current = skeleton[1] ? skeleton[1].key : skeleton[0].key;   // Todo, in Status mode
  // Has the carousel actually been placed on `current`, with real layout?
  // The nav fires its onChange (→ `show()`) during boot, before the first list
  // has loaded, so the first attempt can run against a pane that has no layout
  // and no rows: every rect is 0, the scroll clamps to the first column, and
  // the strip is left naming a column the carousel is not on. `place()`
  // re-asserts the position until one attempt sticks.
  let positioned = false;

  skeleton.forEach(function (lane) {
    const section = document.createElement('section');
    section.className = 'board-col';
    section.dataset.col = lane.key;
    const h = document.createElement('h3');
    h.className = 'board-col-title';
    // the overline role on the name alone: the count beside it is a number,
    // never transformed (styles.css `.overline`)
    const label = document.createElement('span');
    label.className = 'board-col-label overline';
    const n = document.createElement('span');
    n.className = 'board-col-count section-count';
    n.dataset.col = lane.key;
    h.append(label, n);
    if (lane.key === 'done') {
      // the reading surface behind this column (#102) — a link, not a tab
      const link = document.createElement('a');
      link.className = 'board-col-link';
      link.href = '#journal';
      link.textContent = 'journal';
      link.title = 'Done journal — everything closed, by day';
      h.appendChild(link);
    }
    section.appendChild(h);
    const list = document.createElement('ul');
    list.className = 'trows board-list';
    list.setAttribute('role', 'list');
    list.dataset.col = lane.key;
    section.appendChild(list);
    wireDropTarget(section, kind, handlers);
    columns.appendChild(section);

    parts[lane.key] = { section: section, label: label, count: n, list: list };
    if (kind !== 'status') return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'board-strip-btn';
    b.dataset.col = lane.key;
    b.setAttribute('role', 'tab');
    const bl = document.createElement('span');
    bl.textContent = lane.short;
    const bn = document.createElement('span');
    bn.className = 'board-count';
    b.append(bl, ' ', bn);
    b.addEventListener('click', function () { current = lane.key; place(true); });
    strip.appendChild(b);
    Object.assign(parts[lane.key], { strip: b, stripCount: bn });
  });

  function phone() { return window.matchMedia(PHONE_MQ).matches; }
  /** The lanes on screen: present, and on the phone not collapsed away. */
  function visibleKeys() {
    return skeleton.map(function (l) { return l.key; }).filter(function (k) {
      const s = parts[k].section;
      return !s.hidden && !(phone() && s.classList.contains('is-empty'));
    });
  }
  function syncStrip() {
    if (kind !== 'status') return;
    skeleton.forEach(function (lane) {
      const active = lane.key === current;
      parts[lane.key].strip.classList.toggle('active', active);
      parts[lane.key].strip.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }
  /** Put the carousel on `current` (Status mode on the phone; elsewhere every
   *  lane is on screen at once). `onlyIfUnplaced` is a refresh: it closes the
   *  boot race and never yanks a carousel the reader has swiped. */
  function place(smooth, onlyIfUnplaced) {
    const keys = visibleKeys();
    if (keys.length && keys.indexOf(current) < 0) current = keys[0];
    if (!phone() || kind !== 'status') {
      positioned = true;
    } else if (!(onlyIfUnplaced && positioned) && parts[current] && keys.length) {
      // Scroll only the carousel container — scrollIntoView would also yank
      // the page vertically (launcher phone-verify lesson).
      const box = columns.getBoundingClientRect();
      const left = parts[current].section.getBoundingClientRect().left - box.left + columns.scrollLeft;
      columns.scrollTo({ left: left, behavior: smooth ? 'smooth' : 'auto' });
      // Only count it as placed when the container could actually scroll —
      // an empty or unlaid-out carousel silently clamps to column one.
      positioned = box.width > 0 && columns.scrollWidth > columns.clientWidth;
    }
    syncStrip();
  }
  function nearestKey() {
    const keys = visibleKeys();
    if (!keys.length) return current;
    const first = parts[keys[0]].section;
    const st = getComputedStyle(columns);
    const w = Math.max(1, first.offsetWidth + parseFloat(st.columnGap || st.gap || '0'));
    return keys[Math.min(keys.length - 1, Math.max(0, Math.round(columns.scrollLeft / w)))];
  }
  let scrollTimer = 0;
  columns.addEventListener('scroll', function () {
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(function () { current = nearestKey(); syncStrip(); }, 80);
  }, { passive: true });

  function fill(lanes, sort, rowOpts) {
    lanes.forEach(function (lane, i) {
      const p = parts[skeleton[i].key];
      p.section.hidden = !lane;
      if (p.strip) p.strip.hidden = !lane;
      if (!lane) return;
      const rows = sortItems(lane.rows, sort);
      p.section.dataset.drop = lane.drop == null ? '' : lane.drop;
      p.section.setAttribute('aria-label', lane.label);
      p.section.classList.toggle('is-empty', rows.length === 0);
      p.label.textContent = lane.label;
      p.label.parentElement.title = lane.title;
      p.count.textContent = String(rows.length);
      p.count.setAttribute('aria-label', rows.length + (rows.length === 1 ? ' task' : ' tasks'));
      if (p.strip) {
        p.strip.classList.toggle('is-empty', rows.length === 0);
        p.strip.title = lane.label;
        p.stripCount.textContent = String(rows.length);
      }
      p.list.replaceChildren();
      rows.forEach(function (t) { p.list.appendChild(buildRow(t, handlers, rowOpts)); });
    });
  }

  function clear() {
    skeleton.forEach(function (lane) { parts[lane.key].list.replaceChildren(); });
  }

  return { columns: columns, strip: strip, fill: fill, clear: clear, place: place };
}

// ------------------------------------------------------------------ rows
function buildRow(t, handlers, opts) {
  const o = opts || {};
  const week = o.mode === 'week';
  const selected = o.isSelected ? o.isSelected(t.id) : false;
  // Drag is off in Select mode: a card that both drags to another lane and
  // ticks on tap turns every slightly-moved tap into a change (#81).
  const li = taskRow(t, handlers, {
    draggable: !o.selectable, selectable: o.selectable, selected: selected,
    // a status column already says the status; a week lane does not
    hideStatus: !week,
    // the phone Board's status columns are a sideways carousel: a row swipe
    // would fight it. Week mode on the phone is one list, so the swipe stays.
    swipe: week,
    // a lane has no width for a third square beside the circle and the kebab
    verb: false,
  });
  if (o.selectable) return li;
  const suggestion = o.suggestions ? o.suggestions[t.id] : null;
  if (suggestion) li.appendChild(suggestionStrip(suggestion, handlers));
  li.addEventListener('dragstart', function (ev) {
    ev.dataTransfer.setData('text/plain', String(t.id));
    ev.dataTransfer.effectAllowed = 'move';
    li.classList.add('is-dragging');
  });
  li.addEventListener('dragend', function () { li.classList.remove('is-dragging'); });
  return li;
}

function triageButton(handlers) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'button-ghost board-triage hit-target';
  button.hidden = true;
  button.innerHTML = icon('bot') + '<span>Triage Inbox</span>';
  button.addEventListener('click', function () {
    Promise.resolve(handlers.onTriage()).catch(function () { /* caller toasts */ });
  });
  return button;
}

function suggestionStrip(suggestion, handlers) {
  const strip = document.createElement('div');
  strip.className = 'ai-suggestion';
  strip.title = suggestion.reason;
  const summary = document.createElement('span');
  summary.className = 'ai-suggestion-summary';
  const bits = [
    suggestion.parent ? 'under ' + suggestion.parent.title : 'top level',
    suggestion.priority,
    'due: ' + (suggestion.due || 'none'),
    suggestion.person ? suggestion.person.name : 'unassigned',
  ];
  summary.textContent = bits.join(' · ');
  const actions = document.createElement('span');
  actions.className = 'ai-suggestion-actions';
  [['check', 'Accept suggestion', handlers.onAcceptSuggestion],
    ['x', 'Reject suggestion', handlers.onRejectSuggestion]].forEach(function (entry) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'icon-button ai-suggestion-action';
    button.setAttribute('aria-label', entry[1] + ' for ' + suggestion.task_title);
    button.title = entry[1];
    button.innerHTML = icon(entry[0]);
    button.addEventListener('click', function (event) {
      event.stopPropagation();
      button.disabled = true;
      Promise.resolve(entry[2](suggestion.id)).catch(function () { button.disabled = false; });
    });
    actions.appendChild(button);
  });
  strip.append(summary, actions);
  return strip;
}

/** A lane takes a dropped row: a status column sets its status, a week lane
 *  its due date (`data-drop`, the lane's first day; empty = No date). A drop
 *  on the lane the row is already in changes nothing. */
function wireDropTarget(section, kind, handlers) {
  section.addEventListener('dragover', function (ev) {
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    section.classList.add('is-drop-target');
  });
  section.addEventListener('dragleave', function (ev) {
    if (!section.contains(ev.relatedTarget)) section.classList.remove('is-drop-target');
  });
  section.addEventListener('drop', function (ev) {
    ev.preventDefault();
    section.classList.remove('is-drop-target');
    const id = Number(ev.dataTransfer.getData('text/plain'));
    if (!id || section.querySelector('.trow[data-id="' + id + '"]')) return;
    const drop = section.dataset.drop;
    const write = kind === 'status' ? handlers.onStatus(id, drop) : handlers.onDue(id, drop || null);
    Promise.resolve(write).catch(function () { /* toasted by the caller */ });
  });
}
