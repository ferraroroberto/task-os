/* task-os — the Board tab: five status columns over /api/board.
 *
 * Inbox · Todo · Doing · Standby · Done today (done today = completed on the
 * current local day; older done tasks never show). Ported from the fleet
 * launcher's board: on a wide screen all five columns sit side by side and
 * each scrolls on its own; on the phone the columns container is a
 * scroll-snap carousel (one column per swipe) and the strip above it doubles
 * as column switcher + counts. The column skeleton is built once
 * (`mountBoard`) and every refresh only swaps the cards, so the carousel
 * position survives a re-render.
 *
 * Cards: project (root ancestor) · person → title → due (relative, overdue
 * tinted) · priority · recurrence · folder / issue chips · children count →
 * last comment. Click / Enter opens the drawer. Drag a card onto another
 * column (HTML5 DnD) → the caller's `onStatus` → PATCH; on a touch device the
 * card carries a status select instead (no pointer to drag with).
 *
 * The filter row above the columns (project · person · text) is the shared
 * `state.filters` the Table also reads, so `?project=12` is the same
 * shareable URL on both tabs.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { STATUSES, chipFor, issueChip, linkify, relDue } from './format.js';
import { filterSelect } from './table.js';

export const BOARD_COLUMNS = [
  { key: 'inbox', label: 'Inbox', short: 'Inbox', empty: 'Inbox is empty' },
  { key: 'todo', label: 'Todo', short: 'Todo', empty: 'Nothing queued' },
  { key: 'doing', label: 'Doing', short: 'Doing', empty: 'Nothing in progress' },
  { key: 'standby', label: 'Standby', short: 'Standby', empty: 'Nothing on standby' },
  { key: 'done', label: 'Done today', short: 'Done', empty: 'Nothing done today yet' },
];
const COMMENT_MAX = 70;
const PHONE_MQ = '(max-width: 1023px)';

// ------------------------------------------------------------- filter row
/**
 * @param {HTMLElement} host
 * @param {object} filters   the shared filter state (project · person · q read here)
 * @param {{projects: Array<{id:number,title:string,depth?:number}>, people: Array<{id:number,name:string}>, count: number}} options
 * @param {(next: object) => void} onChange
 */
export function renderBoardFilters(host, filters, options, onChange) {
  host.innerHTML = '';
  host.hidden = false;
  const bar = document.createElement('div');
  bar.className = 'filter-row';

  const glyph = document.createElement('span');
  glyph.className = 'filter-glyph';
  glyph.innerHTML = icon('list-filter');
  glyph.title = 'Filters';
  bar.appendChild(glyph);

  const projectValues = [['', 'All projects']].concat((options.projects || []).map(function (p) {
    return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
  }));
  bar.appendChild(filterSelect('project', 'Project', projectValues, filters.project, function (v) {
    onChange(Object.assign({}, filters, { project: v }));
  }));
  const personValues = [['', 'Anyone']].concat((options.people || []).map(function (p) { return [p.id, p.name]; }));
  bar.appendChild(filterSelect('person', 'Person', personValues, filters.person, function (v) {
    onChange(Object.assign({}, filters, { person: v }));
  }));

  const q = document.createElement('input');
  q.type = 'search';
  q.className = 'input-native filter-q';
  q.placeholder = 'Filter text…';
  q.setAttribute('aria-label', 'Filter text');
  q.value = filters.q;
  let qt = 0;
  q.addEventListener('input', function () {
    window.clearTimeout(qt);
    qt = window.setTimeout(function () { onChange(Object.assign({}, filters, { q: q.value.trim() })); }, 250);
  });
  bar.appendChild(q);

  const count = document.createElement('span');
  count.className = 'filter-count';
  count.textContent = options.count + (options.count === 1 ? ' card' : ' cards');
  bar.appendChild(count);

  if (filters.project || filters.person || filters.q) {
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'button-ghost filter-clear';
    clear.textContent = 'Clear';
    clear.addEventListener('click', function () {
      onChange(Object.assign({}, filters, { project: '', person: '', q: '' }));
    });
    bar.appendChild(clear);
  }
  host.appendChild(bar);
}

// ------------------------------------------------------------------ mount
/**
 * Build the column skeleton once; `render(data)` swaps the cards.
 * @param {{onOpen: (id:number)=>void, onStatus: (id:number, status:string)=>Promise<any>}} handlers
 * @returns {{el: HTMLElement, render: (data: object) => void, show: () => void}}
 */
export function mountBoard(handlers) {
  const el = document.createElement('div');
  el.className = 'board';
  let currentCol = 'todo';

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
  const lists = {};
  const counts = {};
  const empties = {};
  BOARD_COLUMNS.forEach(function (col) {
    const section = document.createElement('section');
    section.className = 'board-col card';
    section.dataset.col = col.key;
    section.setAttribute('aria-label', col.label);
    const h = document.createElement('h3');
    h.className = 'board-col-title';
    h.textContent = col.label + ' ';
    const n = document.createElement('span');
    n.className = 'board-col-count';
    n.dataset.col = col.key;
    n.textContent = '0';
    h.appendChild(n);
    section.appendChild(h);
    const list = document.createElement('ul');
    list.className = 'board-list';
    list.dataset.col = col.key;
    section.appendChild(list);
    const empty = document.createElement('div');
    empty.className = 'board-empty';
    empty.dataset.col = col.key;
    empty.appendChild(emptyStateEl('square-kanban', col.empty));
    section.appendChild(empty);
    wireDropTarget(section, col.key, handlers);
    columns.appendChild(section);
    lists[col.key] = list;
    counts[col.key] = n;
    empties[col.key] = empty;
  });
  el.appendChild(columns);

  function showColumn(key, smooth) {
    currentCol = key;
    const col = columns.querySelector('.board-col[data-col="' + key + '"]');
    if (col && window.matchMedia(PHONE_MQ).matches) {
      // Scroll only the carousel container — scrollIntoView would also yank
      // the page vertically (launcher phone-verify lesson).
      const left = col.getBoundingClientRect().left - columns.getBoundingClientRect().left + columns.scrollLeft;
      columns.scrollTo({ left: left, behavior: smooth ? 'smooth' : 'auto' });
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
    const cols = columns.querySelectorAll('.board-col');
    const w = Math.max(1, cols[0].offsetWidth + parseFloat(getComputedStyle(columns).columnGap || getComputedStyle(columns).gap || '0'));
    const index = Math.min(cols.length - 1, Math.max(0, Math.round(columns.scrollLeft / w)));
    return cols[index].dataset.col;
  }
  let scrollTimer = 0;
  columns.addEventListener('scroll', function () {
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(function () { currentCol = nearestColumnKey(); syncStrip(); }, 80);
  }, { passive: true });
  syncStrip();

  function render(data) {
    const cols = (data && data.columns) || {};
    BOARD_COLUMNS.forEach(function (col) {
      const cards = cols[col.key] || [];
      counts[col.key].textContent = String(cards.length);
      stripBtns[col.key].querySelector('.board-count').textContent = String(cards.length);
      lists[col.key].replaceChildren();
      cards.forEach(function (t) { lists[col.key].appendChild(buildCard(t, handlers)); });
      empties[col.key].hidden = cards.length > 0;
    });
  }

  return {
    el: el,
    render: render,
    // The pane was hidden until now — position the carousel on the remembered
    // column once it has layout (no animation on arrival).
    show: function () { requestAnimationFrame(function () { showColumn(currentCol, false); }); },
  };
}

// ------------------------------------------------------------------ cards
function buildCard(t, handlers) {
  const li = document.createElement('li');
  li.className = 'board-item' + (t.priority === 'high' ? ' is-high' : '');
  li.dataset.id = String(t.id);
  li.dataset.status = t.status;
  li.draggable = true;

  const card = document.createElement('div');
  card.className = 'board-card';
  card.setAttribute('role', 'button');
  card.tabIndex = 0;
  card.setAttribute('aria-label', t.title);

  // top line: project (root ancestor) · person
  const top = document.createElement('span');
  top.className = 'board-card-top';
  const proj = document.createElement('span');
  proj.className = 'board-card-project';
  proj.textContent = t.root ? t.root.title : (t.is_project ? 'project' : '');
  if (t.root) proj.title = t.root.title;
  top.appendChild(proj);
  if (t.person) {
    const who = document.createElement('span');
    who.className = 'board-card-person';
    who.innerHTML = icon('user');
    who.appendChild(document.createTextNode(t.person.name));
    top.appendChild(who);
  }
  card.appendChild(top);

  const title = document.createElement('span');
  title.className = 'board-card-title';
  title.textContent = t.title;
  card.appendChild(title);

  // meta line: due · priority · recurrence · chips · children
  const meta = document.createElement('span');
  meta.className = 'board-card-meta';
  if (t.due) {
    const rel = relDue(t.due);
    const due = document.createElement('span');
    due.className = 'board-card-due' + (rel.tone ? ' due-' + rel.tone : '');
    due.title = t.due;
    due.innerHTML = icon('calendar-days');
    due.appendChild(document.createTextNode(rel.text));
    meta.appendChild(due);
  }
  if (t.priority && t.priority !== 'none') {
    const prio = document.createElement('span');
    prio.className = 'board-card-prio prio-' + t.priority;
    prio.textContent = t.priority;
    prio.title = 'priority ' + t.priority;
    meta.appendChild(prio);
  }
  if (t.recurrence) {
    const r = document.createElement('span');
    r.className = 'board-card-recur';
    r.innerHTML = icon('repeat');
    r.title = t.recurrence;
    meta.appendChild(r);
  }
  if (t.folder_ref) meta.appendChild(chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url }));
  if (t.issue_ref) meta.appendChild(issueChip(t.issue_ref));
  if (t.child_count) {
    const kids = document.createElement('span');
    kids.className = 'board-card-kids';
    kids.innerHTML = icon('list-tree');
    kids.appendChild(document.createTextNode(String(t.child_count)));
    kids.title = t.child_count + (t.child_count === 1 ? ' child task' : ' child tasks');
    meta.appendChild(kids);
  }
  if (meta.childNodes.length) card.appendChild(meta);

  if (t.last_comment) {
    const body = t.last_comment.body || '';
    const short = body.length > COMMENT_MAX ? body.slice(0, COMMENT_MAX - 1) + '…' : body;
    const c = document.createElement('span');
    c.className = 'board-card-comment';
    c.innerHTML = icon('message-square');
    const text = document.createElement('span');
    text.className = 'board-card-comment-text';
    text.appendChild(linkify(short));
    c.appendChild(text);
    c.title = t.last_comment.author + ': ' + body;
    card.appendChild(c);
  }
  li.appendChild(card);

  // Touch fallback for the drag: a status select on the card (CSS shows it
  // only on a coarse pointer).
  const sel = document.createElement('select');
  sel.className = 'select-native board-card-status';
  sel.setAttribute('aria-label', 'Status of ' + t.title);
  STATUSES.forEach(function (s) {
    const o = document.createElement('option');
    o.value = s; o.textContent = s; o.selected = s === t.status;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () {
    sel.disabled = true;
    handlers.onStatus(t.id, sel.value).catch(function () { sel.value = t.status; }).finally(function () { sel.disabled = false; });
  });
  li.appendChild(sel);

  card.addEventListener('click', function (ev) {
    if (ev.target.closest('a, select')) return;
    handlers.onOpen(t.id);
  });
  card.addEventListener('keydown', function (ev) {
    if (ev.target !== card) return;
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); handlers.onOpen(t.id); }
  });

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
    const from = section.parentElement.querySelector('.board-item[data-id="' + id + '"]');
    if (from && from.dataset.status === status) return;
    handlers.onStatus(id, status).catch(function () { /* toasted by the caller */ });
  });
}
