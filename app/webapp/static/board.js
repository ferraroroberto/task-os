/* task-os — the Board tab: the status columns over the shared list.
 *
 * Inbox · Todo · Doing · Standby · Done — the first four are the open
 * statuses; Done shows the tasks completed on the current local day (older
 * done tasks never show unless the filter card's "done" pill is pressed,
 * which turns the column into plain Done). Ported from the fleet launcher's
 * board: on a wide screen the columns sit side by side as flat regions split
 * by a vertical hairline; on the phone the columns container is a scroll-
 * snap carousel (one column per swipe) and the strip above it doubles as
 * column switcher + counts. The column skeleton is built once (`mountBoard`)
 * and every refresh only swaps the rows, so the carousel position survives.
 *
 * Rows are the ONE task row (rows.js, issue #46) — title + status select on
 * line 1, the meta line under it — the same row the Table, Tree, Today and
 * Search render. Drag a row onto another column (HTML5 DnD, fine pointers)
 * or change its status select → the caller's `onStatus` → PATCH.
 *
 * `render(items, filters)` takes the shared filtered list: the status pills
 * pick which columns show (none pressed = all), `sort` orders every column.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { sortItems, taskRow } from './rows.js';

export const BOARD_COLUMNS = [
  { key: 'inbox', label: 'Inbox', short: 'Inbox', empty: 'Inbox is empty' },
  { key: 'todo', label: 'Todo', short: 'Todo', empty: 'Nothing queued' },
  { key: 'doing', label: 'Doing', short: 'Doing', empty: 'Nothing in progress' },
  { key: 'standby', label: 'Standby', short: 'Standby', empty: 'Nothing on standby' },
  { key: 'done', label: 'Done today', short: 'Done', empty: 'Nothing done today yet' },
];
const PHONE_MQ = '(max-width: 1023px)';

/**
 * Build the column skeleton once; `render(items, filters)` swaps the rows.
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>}} handlers
 * @returns {{el: HTMLElement, render: (items: Array<object>, filters: object) => void, show: () => void}}
 */
export function mountBoard(handlers) {
  const el = document.createElement('div');
  el.className = 'board';
  let currentCol = 'todo';
  // Has the carousel actually been placed on `currentCol`, with real layout?
  // The nav fires its onChange (→ `show()`) during boot, before the first list
  // has loaded, so the first attempt can run against a pane that has no layout
  // and no rows: every rect is 0, the scroll clamps to the first column, and
  // the strip is left saying "Todo" over an Inbox carousel. `render()`
  // re-asserts the position until one attempt sticks.
  let positioned = false;

  // Phone strip: one count button per column, doubles as the carousel switcher.
  const strip = document.createElement('div');
  strip.className = 'board-strip';
  strip.setAttribute('role', 'tablist');
  strip.setAttribute('aria-label', 'Board columns');
  const stripBtns = {};
  BOARD_COLUMNS.forEach(function (col) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'board-strip-btn';
    b.dataset.col = col.key;
    b.setAttribute('role', 'tab');
    b.title = col.label;
    b.textContent = col.short + ' ';
    const n = document.createElement('span');
    n.className = 'board-count';
    n.textContent = '0';
    b.appendChild(n);
    b.addEventListener('click', function () { showColumn(col.key, true); });
    strip.appendChild(b);
    stripBtns[col.key] = b;
  });
  el.appendChild(strip);

  const columns = document.createElement('div');
  columns.className = 'board-columns';
  const sections = {};
  const lists = {};
  const counts = {};
  const titles = {};
  const empties = {};
  BOARD_COLUMNS.forEach(function (col) {
    const section = document.createElement('section');
    section.className = 'board-col';
    section.dataset.col = col.key;
    section.setAttribute('aria-label', col.label);
    const h = document.createElement('h3');
    h.className = 'board-col-title';
    const label = document.createElement('span');
    label.textContent = col.label;
    h.appendChild(label);
    const n = document.createElement('span');
    n.className = 'board-col-count';
    n.dataset.col = col.key;
    n.textContent = '0';
    h.appendChild(n);
    section.appendChild(h);
    const list = document.createElement('ul');
    list.className = 'trows board-list';
    list.setAttribute('role', 'list');
    list.dataset.col = col.key;
    section.appendChild(list);
    const empty = document.createElement('div');
    empty.className = 'board-empty';
    empty.dataset.col = col.key;
    empty.appendChild(emptyStateEl('square-kanban', col.empty));
    section.appendChild(empty);
    wireDropTarget(section, col.key, handlers);
    columns.appendChild(section);
    sections[col.key] = section;
    lists[col.key] = list;
    counts[col.key] = n;
    titles[col.key] = label;
    empties[col.key] = empty;
  });
  el.appendChild(columns);

  function visibleKeys() {
    return BOARD_COLUMNS.map(function (c) { return c.key; }).filter(function (k) { return !sections[k].hidden; });
  }
  function showColumn(key, smooth) {
    currentCol = key;
    const col = sections[key];
    if (!window.matchMedia(PHONE_MQ).matches) {
      positioned = true;      // desktop grid: every column is on screen at once
    } else if (col && !col.hidden) {
      // Scroll only the carousel container — scrollIntoView would also yank
      // the page vertically (launcher phone-verify lesson).
      const box = columns.getBoundingClientRect();
      const left = col.getBoundingClientRect().left - box.left + columns.scrollLeft;
      columns.scrollTo({ left: left, behavior: smooth ? 'smooth' : 'auto' });
      // Only count it as placed when the container could actually scroll —
      // an empty or unlaid-out carousel silently clamps to column one.
      positioned = box.width > 0 && columns.scrollWidth > columns.clientWidth;
    }
    syncStrip();
  }
  function syncStrip() {
    BOARD_COLUMNS.forEach(function (col) {
      const active = col.key === currentCol;
      stripBtns[col.key].classList.toggle('active', active);
      stripBtns[col.key].setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }
  function nearestColumnKey() {
    const keys = visibleKeys();
    if (!keys.length) return currentCol;
    const first = sections[keys[0]];
    const w = Math.max(1, first.offsetWidth + parseFloat(getComputedStyle(columns).columnGap || getComputedStyle(columns).gap || '0'));
    const index = Math.min(keys.length - 1, Math.max(0, Math.round(columns.scrollLeft / w)));
    return keys[index];
  }
  let scrollTimer = 0;
  columns.addEventListener('scroll', function () {
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(function () { currentCol = nearestColumnKey(); syncStrip(); }, 80);
  }, { passive: true });
  syncStrip();

  /**
   * @param {Array<object>} items   the shared filtered list (done = done today unless the done pill is pressed)
   * @param {object} filters        {status: [...], sort}
   * @param {{selectable?: boolean, isSelected?: (id:number)=>boolean}} [opts]  Select mode (#81)
   */
  function render(items, filters, opts) {
    const o = opts || {};
    const f = filters || { status: [], sort: 'due' };
    const byStatus = {};
    BOARD_COLUMNS.forEach(function (c) { byStatus[c.key] = []; });
    (items || []).forEach(function (t) { if (byStatus[t.status]) byStatus[t.status].push(t); });
    const wantsDone = f.status.indexOf('done') >= 0;
    titles.done.textContent = wantsDone ? 'Done' : 'Done today';
    stripBtns.done.title = wantsDone ? 'Done' : 'Done today';
    BOARD_COLUMNS.forEach(function (col) {
      const hidden = f.status.length > 0 && f.status.indexOf(col.key) < 0;
      sections[col.key].hidden = hidden;
      stripBtns[col.key].hidden = hidden;
      const rows = sortItems(byStatus[col.key], f.sort);
      counts[col.key].textContent = String(rows.length);
      stripBtns[col.key].querySelector('.board-count').textContent = String(rows.length);
      lists[col.key].replaceChildren();
      rows.forEach(function (t) {
        lists[col.key].appendChild(buildRow(t, handlers, {
          selectable: !!o.selectable,
          selected: o.isSelected ? o.isSelected(t.id) : false,
        }));
      });
      empties[col.key].hidden = rows.length > 0;
    });
    if (sections[currentCol].hidden) {
      const keys = visibleKeys();
      if (keys.length) currentCol = keys[0];
    }
    // Close the boot race: the rows are in now, so if the carousel was never
    // really placed, place it — the strip and the visible column must name the
    // same thing. Once one attempt sticks this never runs again, so a refresh
    // can never yank a carousel the reader has swiped.
    if (!positioned) showColumn(currentCol, false);
    else syncStrip();
  }

  return {
    el: el,
    render: render,
    // The pane was hidden until now — position the carousel on the remembered
    // column once it has layout (no animation on arrival).
    show: function () { requestAnimationFrame(function () { showColumn(currentCol, false); }); },
  };
}

// ------------------------------------------------------------------ rows
function buildRow(t, handlers, opts) {
  const o = opts || {};
  // Drag is off in Select mode: a card that both drags to another column and
  // ticks on tap turns every slightly-moved tap into a status change (#81).
  const li = taskRow(t, handlers, {
    draggable: !o.selectable, selectable: o.selectable, selected: o.selected,
  });
  if (o.selectable) return li;
  li.addEventListener('dragstart', function (ev) {
    ev.dataTransfer.setData('text/plain', String(t.id));
    ev.dataTransfer.effectAllowed = 'move';
    li.classList.add('is-dragging');
  });
  li.addEventListener('dragend', function () { li.classList.remove('is-dragging'); });
  return li;
}

function wireDropTarget(section, status, handlers) {
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
    if (!id) return;
    const from = section.parentElement.querySelector('.trow[data-id="' + id + '"]');
    if (from && from.dataset.status === status) return;
    handlers.onStatus(id, status).catch(function () { /* toasted by the caller */ });
  });
}
