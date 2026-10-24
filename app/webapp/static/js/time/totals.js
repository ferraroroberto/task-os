/* task-os — the Time tab's Totals view: the period / area / whose-time
 * controls, the sums and the CSV link; the cards are cards.js's. */

'use strict';

import { emptyStateEl } from '../../_vendored/empty-state/empty-state.js';
import { icon } from '../../_vendored/icons/icons.js';
import { api, qs } from '../../api.js';
import { fmtMinutes } from '../../time-format.js';
import { categoryCard, compareCard, guessCard } from './cards.js';
import { PERIODS, PERIOD_LABELS, nameOf, nameYou, solo } from './data.js';
import { avatar, cardHead, el, segmented, titleText } from './dom.js';

function totalsQuery(ctx) {
  const t = ctx.st.totals;
  const compare = !solo(ctx) && t.area && t.area === ctx.st.meta.compare_area;
  return {
    period: t.period, area: t.area,
    person: compare || solo(ctx) || t.who === 'all' ? '' : ctx.st.person,
    compare: compare,
  };
}

function totalsControls(ctx, q) {
  const st = ctx.st;
  const bar = el('div', 'time-controls');
  bar.appendChild(segmented('Period', PERIODS.map(function (pair) {
    return { value: pair[0], label: pair[1], track: 'time-period' };
  }), st.totals.period, function (v) { st.totals.period = v; loadTotals(ctx); }, 'time-period'));
  const area = el('select', 'select-native time-area');
  area.setAttribute('aria-label', 'Area');
  area.dataset.track = 'time-area';
  const all = el('option', '', 'All areas');
  all.value = '';
  area.appendChild(all);
  st.meta.areas.forEach(function (a) {
    const o = el('option', '', a.name + (a.archived ? ' (archived)' : ''));
    o.value = a.slug;
    area.appendChild(o);
  });
  area.value = st.totals.area;
  area.addEventListener('change', function () { st.totals.area = area.value; loadTotals(ctx); });
  bar.appendChild(area);
  if (!solo(ctx) && !q.compare) {
    bar.appendChild(segmented('Whose time', [
      { value: 'me', label: 'Me', track: 'time-who' },
      { value: 'all', label: 'Everyone', track: 'time-who' },
    ], st.totals.who, function (v) { st.totals.who = v; loadTotals(ctx); }, 'time-who'));
  }
  return bar;
}

export async function loadTotals(ctx) {
  const q = totalsQuery(ctx);
  let summary;
  let guesses = null;
  try {
    [summary, guesses] = await Promise.all([
      api('/api/time/summary' + qs({ period: q.period, area: q.area, person: q.person })),
      q.compare ? api('/api/time/guesses/' + encodeURIComponent(ctx.st.person)) : Promise.resolve(null),
    ]);
  } catch (_) {
    ctx.els.totals.replaceChildren(totalsControls(ctx, q), emptyStateEl('triangle-alert', 'Could not read the totals', {
      actionLabel: 'Retry', onAction: function () { loadTotals(ctx); },
    }));
    return;
  }
  renderTotals(ctx, q, summary, guesses);
}

/** The "Total" card a non-comparison view leads with: the total, then the
 *  areas (all areas) or the people (one area, more than one person). */
function sumCard(ctx, q, s, people) {
  const sum = el('section', 'card action-list time-sum');
  const ul = el('ul', 'action-rows');
  const total = el('li', 'action-row time-sum-row');
  const totalMain = el('div', 'action-row-main');
  totalMain.appendChild(titleText('Total', q.person ? nameOf(ctx, q.person) : (solo(ctx) ? '' : 'Everyone')));
  total.append(totalMain, el('span', 'action-row-value', fmtMinutes(s.total_minutes)));
  ul.appendChild(total);
  if (!q.area) {
    s.by_area.forEach(function (a) {
      const li = el('li', 'action-row time-sum-row');
      const main = el('div', 'action-row-main');
      main.appendChild(titleText(a.name));
      li.append(main, el('span', 'action-row-value', fmtMinutes(a.minutes)));
      ul.appendChild(li);
    });
  } else if (people.length > 1) {
    people.forEach(function (p) {
      const li = el('li', 'action-row time-sum-row');
      const main = el('div', 'action-row-main');
      main.append(avatar(nameOf(ctx, p)), titleText(nameYou(ctx, p)));
      li.append(main, el('span', 'action-row-value', fmtMinutes(s.by_person[p])));
      ul.appendChild(li);
    });
  }
  sum.append(cardHead('clock', PERIOD_LABELS[s.period]), ul);
  return sum;
}

function renderTotals(ctx, q, s, guesses) {
  const parts = [totalsControls(ctx, q)];
  const people = Object.keys(s.by_person);
  // the comparison and the guess card stand with nothing logged (a guess can come first)
  if (q.compare) parts.push(compareCard(ctx, s, people), guessCard(ctx, s, people, guesses));
  if (!s.total_minutes) {
    parts.push(emptyStateEl('clock', 'Nothing logged in this period', {
      actionLabel: 'Log some time', onAction: function () { ctx.showView('log'); },
    }));
    ctx.els.totals.replaceChildren.apply(ctx.els.totals, parts);
    return;
  }
  if (!q.compare) parts.push(sumCard(ctx, q, s, people));
  parts.push(categoryCard(ctx, s, people));
  const csv = el('a', 'button-surface time-csv');
  csv.href = '/api/time/entries.csv' + qs({ period: q.period, area: q.area, person: q.person });
  csv.setAttribute('download', '');
  csv.dataset.track = 'time-csv';
  csv.innerHTML = icon('download');
  csv.appendChild(document.createTextNode('Download CSV'));
  parts.push(csv);
  ctx.els.totals.replaceChildren.apply(ctx.els.totals, parts);
}
