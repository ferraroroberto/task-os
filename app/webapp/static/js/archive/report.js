/* task-os — Settings → Email archiving: the report — the grid on a wide screen,
 * stacked cards under 768 px, both built from the same row objects. */

'use strict';

import { emptyStateEl } from '../../_vendored/empty-state/empty-state.js';
import { fmtTsShort } from '../../format.js';
import { verbButton } from './actions.js';
import {
  confidenceEl, destinationEl, filesEl, reasonEl, stateChip, subjectCellEl, subjectEl,
} from './cells.js';
import { actionsFor, rowMenuFor } from './rowactions.js';
import { REVIEWABLE } from './rules.js';

// Who sent it and when ride under the subject (#339): two columns fewer is
// what lets the grid fit the window, the row's actions on screen.
const COLUMNS = ['Subject', 'Destination', 'Files', 'Confidence', 'Why', 'State', ''];

/** Redraw the report; a row menu whose row did not come back closes. */
export function renderReport(ctx) {
  drawReport(ctx);
  ctx.rowMenu.endRender();
}

function drawReport(ctx) {
  const els = ctx.els;
  const st = ctx.st;
  els.host.replaceChildren();
  if (st.status && !st.status.configured) {
    els.host.appendChild(emptyCard('archive', st.status.reason || 'Batch archiving is not configured here'));
    els.acceptAll.hidden = true;
    return;
  }
  if (!st.run) {
    els.host.appendChild(emptyCard('archive', st.runs.length ? 'Pick a run above' : 'No run yet — press “Archive Inbox now”'));
    els.acceptAll.hidden = true;
    return;
  }
  const items = st.run.items || [];
  if (!items.length) {
    els.host.appendChild(emptyCard('archive', st.run.status === 'running'
      ? 'The run has started — mails appear as they are decided'
      : 'This run touched no mail'));
    els.acceptAll.hidden = true;
    return;
  }
  els.host.appendChild(ctx.phoneMq.matches ? renderCards(ctx, items) : renderTable(ctx, items));
  const pending = items.filter(function (i) {
    return REVIEWABLE.indexOf(i.status) >= 0 && !i.decided_at;
  });
  els.acceptAll.hidden = pending.length === 0;
  // A static button: `runAction` disabled it, and nothing but this redraw
  // gives it back — a cancelled confirm would otherwise leave it dead.
  els.acceptAll.disabled = st.busy;
  // The count is the rows that still offer *Accept*, and now nothing else:
  // a decided row stopped offering it above, so the button and the report
  // can no longer disagree.
  els.acceptAll.textContent = ctx.narrow()
    ? 'Accept all (' + pending.length + ')'
    : 'Accept all ' + pending.length + ' that need you';
  els.acceptAll.dataset.ids = pending.map(function (i) { return i.id; }).join(',');
}

function emptyCard(glyph, message) {
  const card = document.createElement('div');
  card.className = 'card empty-card';
  card.appendChild(emptyStateEl(glyph, message));
  return card;
}

function renderTable(ctx, items) {
  const wrap = document.createElement('div');
  wrap.className = 'card archive-grid-wrap';
  const scroll = document.createElement('div');
  scroll.className = 'archive-grid-scroll';
  const table = document.createElement('table');
  table.className = 'archive-grid';
  const thead = document.createElement('thead');
  const hrow = document.createElement('tr');
  COLUMNS.forEach(function (label) {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = label;
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  const tbody = document.createElement('tbody');
  items.forEach(function (item) {
    const tr = document.createElement('tr');
    tr.className = 'archive-row';
    tr.dataset.id = String(item.id);
    tr.dataset.status = item.status;
    // The panel's own full-width row, right under this one, so opening it
    // never changes a single column's width.
    const panelRow = document.createElement('tr');
    panelRow.className = 'archive-move-row';
    panelRow.dataset.id = String(item.id);
    panelRow.hidden = true;
    const actions = rowMenuFor(ctx, item, {
      onToggle: function (open) { panelRow.hidden = !open; },
    });
    tr.append(
      cell('c-subject', subjectCellEl(item)),
      cell('c-dest', destinationEl(item)),
      cell('c-files', filesEl(ctx, item, { cap: true })),
      cell('c-conf', confidenceEl(item)),
      cell('c-why', reasonEl(ctx, item)),
      cell('c-state', stateChip(item)),
      cell('c-act', actions.el)
    );
    tbody.appendChild(tr);
    if (!actions.body) return;
    const td = document.createElement('td');
    td.colSpan = COLUMNS.length;
    td.appendChild(actions.body);
    panelRow.appendChild(td);
    tbody.appendChild(panelRow);
  });
  table.append(thead, tbody);
  scroll.appendChild(table);
  wrap.appendChild(scroll);
  return wrap;
}

function cell(cls, child) {
  const td = document.createElement('td');
  td.className = cls;
  td.appendChild(child);
  return td;
}

/** Phone: one card per mail, the actions behind the row's own disclosure —
 *  nine columns do not fit 390 px and a horizontal scroller hides the
 *  actions, which are the point of the screen. */
function renderCards(ctx, items) {
  const list = document.createElement('div');
  list.className = 'archive-cards';
  items.forEach(function (item) {
    const card = document.createElement('article');
    card.className = 'card archive-card';
    card.dataset.id = String(item.id);
    card.dataset.status = item.status;

    const head = document.createElement('div');
    head.className = 'archive-card-head';
    head.append(subjectEl(item), stateChip(item));

    // Two lines at a glance (#339): the subject with its state, then one
    // line of who · when · where it went. The files, the confidence and the
    // reason are what a review reads, so they sit behind the card's own
    // disclosure with the actions.
    const meta = document.createElement('div');
    meta.className = 'archive-card-meta muted';
    meta.append(
      (item.sender || '–') + ' · ' + (item.sent_at ? fmtTsShort(item.sent_at) : '–') + ' · ',
      destinationEl(item)
    );

    const dest = document.createElement('div');
    dest.className = 'archive-card-dest';
    dest.append(confidenceEl(item), filesEl(ctx, item));

    const why = document.createElement('p');
    why.className = 'archive-card-why muted';
    why.appendChild(reasonEl(ctx, item));

    card.append(head, meta, cardMenu(ctx, item, dest, why));
    list.appendChild(card);
  });
  return list;
}

/** *Review* is the fourth review level, so it wears the same button as the
 *  three behind it (#168) — a disclosure, not a link, and not a `<summary>`
 *  whose shape nothing else on the row shares. A card with nothing left to
 *  press still has its details to read, so the same disclosure says Details
 *  there and holds no actions. */
function cardMenu(ctx, item, dest, why) {
  const actions = actionsFor(ctx, item);
  const menu = document.createElement('div');
  menu.className = 'archive-menu';
  // The glyph alone is not a conventional icon-only name (fleet design
  // COMP-09, #424), so the word is shown beside it; the <label> makes the
  // word a second place to press, the toggle itself unchanged.
  const verb = actions.controls ? 'Review' : 'Details';
  const toggle = verbButton(actions.controls ? 'eye' : 'file-text', verb);
  toggle.classList.add('archive-menu-toggle');
  toggle.setAttribute('aria-expanded', 'false');
  const toggleHead = document.createElement('label');
  toggleHead.className = 'archive-menu-head';
  const toggleWord = document.createElement('span');
  toggleWord.className = 'archive-menu-word';
  toggleWord.textContent = verb;
  toggleHead.append(toggle, toggleWord);
  const body = document.createElement('div');
  body.className = 'archive-menu-body';
  body.hidden = true;
  body.append(dest, why, actions.el);
  if (actions.body) body.appendChild(actions.body);
  toggle.addEventListener('click', function () {
    const open = body.hidden;
    body.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  menu.append(toggleHead, body);
  return menu;
}
