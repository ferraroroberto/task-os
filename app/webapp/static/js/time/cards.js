/* task-os — the Totals view's cards: the household comparison, the guess
 * card and the per-category bars. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { api } from '../../api.js';
import { showInfo } from '../../time-dialogs.js';
import { fmtMinutes, initialOf } from '../../time-format.js';
import { PERIOD_LABELS, nameOf, nameYou } from './data.js';
import { avatar, cardHead, el, swatch } from './dom.js';

//: Bars tell people apart by fill, never by hue: the first solid, then hatched, then dotted.
const FILLS = ['solid', 'hatched', 'dotted'];

function fillFor(ctx, person) {
  const i = ctx.st.meta.people.findIndex(function (p) { return p.id === person; });
  return FILLS[Math.max(0, i) % FILLS.length];
}

export function compareCard(ctx, s, people) {
  const card = el('section', 'card time-compare');
  const info = el('button', 'icon-button hit-target time-info');
  info.type = 'button';
  info.setAttribute('aria-label', 'How the comparison works');
  info.title = 'How the comparison works';
  info.innerHTML = icon('info');
  info.addEventListener('click', function () {
    showInfo({
      title: 'How the comparison works',
      lines: [
        'Each person logs their own time here; the shares are of the time logged, not of the time spent.',
        'In the bars, each person has their own fill (solid, hatched) and their initial; the colour is the same for everyone.',
        '"Days with something logged" shows how complete each log is: a share is only as good as the days behind it.',
      ],
    });
  });
  const share = function (p) { return Math.round(s.by_person[p] / s.total_minutes * 100); };
  const area = ctx.st.meta.areas.find(function (a) { return a.slug === s.area; });
  card.appendChild(cardHead('activity', (area ? area.name : 'Area') + ' · ' + PERIOD_LABELS[s.period], info));
  const h2h = el('div', 'time-h2h');
  people.forEach(function (p) {
    const col = el('div', 'time-h2h-person');
    const name = el('div', 'time-h2h-name');
    name.append(avatar(nameOf(ctx, p)), document.createTextNode(nameYou(ctx, p)), swatch(fillFor(ctx, p)));
    col.append(name, el('div', 'time-h2h-big', fmtMinutes(s.by_person[p])),
      el('div', 'muted time-h2h-pct', s.total_minutes ? share(p) + '% of logged time' : 'nothing logged'));
    h2h.appendChild(col);
  });
  const split = el('div', 'time-split');
  split.setAttribute('role', 'img');
  split.setAttribute('aria-label', s.total_minutes ? people.map(function (p) {
    return nameOf(ctx, p) + ' ' + share(p) + '%';
  }).join(', ') : 'Nothing logged yet');
  people.forEach(function (p) {
    const f = el('span', 'time-fill');
    f.dataset.fill = fillFor(ctx, p);
    f.style.width = (s.total_minutes ? s.by_person[p] / s.total_minutes * 100 : 0) + '%';
    split.appendChild(f);
  });
  const coverage = el('p', 'muted time-coverage', 'Days with something logged: ' + people.map(function (p) {
    return nameOf(ctx, p) + ' ' + s.days_logged[p] + ' of ' + s.span_days;
  }).join(', ') + '.');
  card.append(h2h, split, coverage);
  return card;
}

export function guessCard(ctx, s, people, g) {
  const st = ctx.st;
  const card = el('section', 'card time-guess');
  card.appendChild(cardHead('user', 'Guess your share'));
  if (!g || !g.mine) {
    card.appendChild(el('p', 'muted time-card-note',
      'Before you look: what share of this time do you think is yours? The other answers stay hidden until yours is in.'));
    card.appendChild(guessForm(ctx, null));
    return card;
  }
  const mine = el('p', 'time-guess-mine');
  mine.append('Your guess: ', el('strong', '', g.mine.pct + '%'), ' ');
  const change = el('button', 'button-ghost time-guess-change', 'Change');
  change.type = 'button';
  change.dataset.track = 'time-guess-change';
  change.addEventListener('click', function () { mine.replaceWith(guessForm(ctx, g.mine.pct)); });
  mine.appendChild(change);
  card.appendChild(mine);
  const others = people.filter(function (p) { return p !== st.person; });
  const missing = others.filter(function (p) { return !(g.others && g.others[p]); });
  if (missing.length) {
    card.appendChild(el('p', 'muted time-card-note', missing.map(function (p) { return nameOf(ctx, p); }).join(', ') + (missing.length > 1 ? ' have' : ' has') + ' not guessed yet.'));
    return card;
  }
  const table = el('table', 'time-cmp');
  const head = el('tr');
  head.append(el('th', '', ''), el('th', '', 'Guessed'), el('th', '', 'Logged'));
  const thead = el('thead');
  thead.appendChild(head);
  const tbody = el('tbody');
  let sum = 0;
  people.forEach(function (p) {
    const pct = p === st.person ? g.mine.pct : g.others[p].pct;
    sum += pct;
    const tr = el('tr');
    const who = el('td');
    who.append(avatar(nameOf(ctx, p)), document.createTextNode(nameYou(ctx, p)), swatch(fillFor(ctx, p)));
    tr.append(who, el('td', '', pct + '%'),
      el('td', '', s.total_minutes ? Math.round(s.by_person[p] / s.total_minutes * 100) + '%' : '–'));
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
  card.append(table, el('p', 'muted time-card-note', 'The guesses add up to ' + sum + '%. Accurate views would add up to 100%.'));
  return card;
}

function guessForm(ctx, current) {
  const form = el('form', 'time-guess-form');
  const label = el('label', 'time-guess-field');
  label.appendChild(el('span', '', 'Your share, %'));
  const input = el('input', 'input-native time-minutes');
  input.type = 'number';
  input.inputMode = 'numeric';
  input.min = '0';
  input.max = '100';
  input.id = 'timeGuessPct';
  if (current !== null) input.value = String(current);
  label.appendChild(input);
  const go = el('button', 'button-tint', 'Lock in');
  go.type = 'submit';
  go.dataset.track = 'time-guess';
  const msg = el('p', 'time-form-msg');
  msg.setAttribute('role', 'alert');
  form.append(label, go, msg);
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const v = Math.round(Number(input.value));
    if (input.value === '' || !(v >= 0 && v <= 100)) { msg.textContent = 'Enter a number from 0 to 100.'; return; }
    try {
      await api('/api/time/guesses/' + encodeURIComponent(ctx.st.person), { method: 'PUT', body: { pct: v } });
      ctx.loadTotals();
    } catch (err) {
      msg.textContent = err.message;
    }
  });
  return form;
}

export function categoryCard(ctx, s, people) {
  const card = el('section', 'card time-cats');
  card.appendChild(cardHead('list-checks', 'By category'));
  let max = 0;
  s.by_category.forEach(function (c) { people.forEach(function (p) { max = Math.max(max, c.by_person[p] || 0); }); });
  s.by_category.forEach(function (c) {
    const block = el('div', 'time-cat');
    block.appendChild(el('div', 'time-cat-name', c.name));
    people.forEach(function (p) {
      const line = el('div', 'time-bar-line');
      const v = c.by_person[p] || 0;
      const track = el('div', 'time-track');
      track.title = nameOf(ctx, p) + ' ' + fmtMinutes(v);
      const fill = el('span', 'time-fill');
      fill.dataset.fill = fillFor(ctx, p);
      fill.style.width = (v ? Math.max(1, v / max * 100) : 0) + '%';
      track.appendChild(fill);
      if (people.length > 1) line.appendChild(el('span', 'time-initial', initialOf(nameOf(ctx, p))));
      line.append(track, el('span', 'time-bar-value' + (v ? '' : ' muted'), v ? fmtMinutes(v) : '–'));
      block.appendChild(line);
    });
    card.appendChild(block);
  });
  return card;
}
