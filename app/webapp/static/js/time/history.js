/* task-os — the Time tab's History view: date-grouped rows, a filter above
 * twelve, "Show older entries", and the row's edit · start again · delete. */

'use strict';

import { emptyStateEl } from '../../_vendored/empty-state/empty-state.js';
import { icon } from '../../_vendored/icons/icons.js';
import { api, qs } from '../../api.js';
import { confirmDialog } from '../../confirm.js';
import { openEntryEditor } from '../../time-dialogs.js';
import { dayLabel, entrySpan } from '../../time-format.js';
import { toast } from '../../toast.js';
import { avatar, el, titleText } from './dom.js';
import { categoryById, nameOf, refreshLive, solo } from './data.js';
import { startTimer } from './timer.js';

const HISTORY_PAGE = 50;
const FILTER_ABOVE = 12;   // design.md action-row.filterAboveRows

export async function loadHistory(ctx, more) {
  const h = ctx.st.history;
  let page;
  try {
    page = await api('/api/time/entries' + qs({ q: h.q, limit: HISTORY_PAGE, offset: more ? h.items.length : 0 }));
  } catch (_) {
    ctx.els.history.replaceChildren(emptyStateEl('triangle-alert', 'Could not read the history', {
      actionLabel: 'Retry', onAction: function () { loadHistory(ctx, false); },
    }));
    return;
  }
  h.items = more ? h.items.concat(page.items) : page.items;
  h.total = page.total;
  renderHistory(ctx);
}

/** The filter box above a long history; typing re-reads after a pause and keeps the caret. */
function filterBox(ctx) {
  const h = ctx.st.history;
  const label = el('label', 'action-row-filter time-filter');
  label.innerHTML = icon('search');
  const input = el('input');
  input.type = 'search';
  input.placeholder = 'Filter ' + h.total + ' entries…';
  input.setAttribute('aria-label', 'Filter entries');
  input.value = h.q;
  input.addEventListener('input', function () {
    window.clearTimeout(ctx.filterTimer);
    ctx.filterTimer = window.setTimeout(function () {
      h.q = input.value.trim();
      loadHistory(ctx, false).then(function () {
        const again = ctx.els.history.querySelector('.time-filter input');
        if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
      });
    }, 250);
  });
  label.appendChild(input);
  return label;
}

function renderHistory(ctx) {
  const h = ctx.st.history;
  const parts = [];
  if (h.total > FILTER_ABOVE || h.q) parts.push(filterBox(ctx));
  if (!h.items.length) {
    parts.push(h.q ? emptyStateEl('search', 'No entry matches', {
      actionLabel: 'Clear filter', onAction: function () { h.q = ''; loadHistory(ctx, false); },
    }) : emptyStateEl('clock', 'Nothing logged yet', {
      actionLabel: 'Log some time', onAction: function () { ctx.showView('log'); },
    }));
    ctx.els.history.replaceChildren.apply(ctx.els.history, parts);
    ctx.historyMenu.endRender();
    return;
  }
  let day = null;
  let list = null;
  h.items.forEach(function (e) {
    if (e.day !== day) {
      day = e.day;
      parts.push(el('h3', 'overline time-group-title', dayLabel(day, ctx.st.today)));
      const card = el('section', 'card action-list time-history-day');
      list = el('ul', 'action-rows');
      card.appendChild(list);
      parts.push(card);
    }
    list.appendChild(historyRow(ctx, e));
  });
  if (h.items.length < h.total) {
    const more = el('button', 'button-surface time-more', 'Show older entries');
    more.type = 'button';
    more.dataset.track = 'time-more';
    more.addEventListener('click', function () { loadHistory(ctx, true); });
    parts.push(more);
  }
  ctx.els.history.replaceChildren.apply(ctx.els.history, parts);
  ctx.historyMenu.endRender();
}

function historyRow(ctx, e) {
  const li = el('li', 'action-row time-entry');
  li.dataset.id = String(e.id);
  const main = el('button', 'action-row-main');
  main.type = 'button';
  main.dataset.track = 'time-edit';
  main.setAttribute('aria-haspopup', 'dialog');
  const meta = [entrySpan(e)];
  if (!solo(ctx)) meta.push(nameOf(ctx, e.person));
  if (e.note) meta.push(e.note);
  main.append(avatar(nameOf(ctx, e.person)), titleText(e.category_name, meta.join(' · ')));
  main.addEventListener('click', function () { editEntry(ctx, e); });
  const kebab = el('button', 'icon-button action-row-kebab');
  kebab.type = 'button';
  kebab.setAttribute('aria-label', 'More actions');
  kebab.setAttribute('aria-haspopup', 'menu');
  kebab.setAttribute('aria-expanded', 'false');
  kebab.innerHTML = icon('ellipsis-vertical');
  ctx.historyMenu.attach(e.id, kebab, [
    { label: 'Edit', glyph: 'pencil', onTap: function () { editEntry(ctx, e); } },
    { label: 'Start again', glyph: 'play', onTap: function () { startAgain(ctx, e); } },
    { label: 'Delete', glyph: 'trash-2', danger: true, onTap: function () { deleteEntry(ctx, e); } },
  ]);
  li.append(main, kebab);
  return li;
}

async function editEntry(ctx, e) {
  const st = ctx.st;
  const saved = await openEntryEditor({ meta: st.meta, person: st.person, today: st.today, now: st.now, entry: e });
  if (saved) toast('Entry saved');
  await Promise.all([loadHistory(ctx, false), refreshLive(ctx)]);
}

async function startAgain(ctx, e) {
  const found = categoryById(ctx, e.category_id);
  if (!found || found.category.archived || found.area.archived) {
    toast(e.category_name + ' is archived, so it cannot be started', 'error');
    return;
  }
  await startTimer(ctx, found.category);
  ctx.showView('log');
}

async function deleteEntry(ctx, e) {
  const ok = await confirmDialog({
    title: 'Delete this entry?',
    lines: [e.category_name + ', ' + dayLabel(e.day, ctx.st.today) + ': ' + entrySpan(e) + (solo(ctx) ? '' : ', ' + nameOf(ctx, e.person)) + '.'],
    warn: 'It leaves the totals for good.',
    action: 'Delete entry',
  });
  if (!ok) return;
  try {
    await api('/api/time/entries/' + e.id, { method: 'DELETE' });
    toast('Entry deleted');
  } catch (err) {
    toast(err.status === 404 ? 'That entry was already deleted' : err.message, 'error');
  }
  await Promise.all([loadHistory(ctx, false), refreshLive(ctx)]);
}
