/* task-os — the Time tab's Log view: today per person, this device's running
 * timer and the start list. */

'use strict';

import { clockOf, fmtElapsed, fmtMinutes } from '../../time-format.js';
import { avatar, cardHead, el, titleText } from './dom.js';
import { categoryById, serverNow, timerOf } from './data.js';

export function buildLog(ctx) {
  const log = ctx.log;
  log.glance = el('section', 'card action-list time-glance');
  log.timer = el('div', 'time-timer-slot');
  log.start = el('section', 'card action-list time-start');
  const add = el('button', 'button-tint time-add', 'Add time already spent');
  add.type = 'button';
  add.dataset.track = 'time-add';
  add.addEventListener('click', function () { ctx.addEntry(); });
  ctx.els.log.replaceChildren(log.glance, log.timer, log.start, add);
  renderGlance(ctx);
  renderTimer(ctx);
  renderStart(ctx);
}

/** Identity of the running timer card — same person/category/start means the
 *  poll must leave the card (and any typed correction) alone. */
export function timerSignature(t) {
  return t ? [t.person, t.category_id, t.started_at].join('|') : null;
}

export function renderGlance(ctx) {
  if (!ctx.log.glance) return;
  const s = ctx.st.todaySummary;
  const list = el('ul', 'action-rows');
  ctx.st.meta.people.forEach(function (p) {
    const li = el('li', 'action-row time-glance-row');
    const main = el('div', 'action-row-main');
    const running = timerOf(ctx, p.id);
    main.append(avatar(p.name), titleText(p.name, running ? 'Timer running · ' + running.category_name : ''));
    const mins = s ? s.by_person[p.id] || 0 : null;
    const value = el('span', 'action-row-value time-glance-value' + (mins ? '' : ' muted'),
      mins === null ? '–' : (mins ? fmtMinutes(mins) : 'Nothing yet'));
    li.append(main, value);
    list.appendChild(li);
  });
  ctx.log.glance.replaceChildren(cardHead('clock', 'Today so far'), list);
}

export function renderTimer(ctx) {
  const log = ctx.log;
  if (!log.timer) return;
  const t = timerOf(ctx, ctx.st.person);
  if (!t) { log.timer.replaceChildren(); return; }
  const card = el('section', 'card time-timer');
  card.setAttribute('aria-label', 'Running timer');
  card.append(el('p', 'overline', 'Timer running'), el('h2', 'time-timer-cat', t.category_name),
    el('p', 'muted time-timer-meta', t.area_name + ' · started ' + clockOf(t.started_at)));
  const clock = el('p', 'time-clock');
  clock.setAttribute('role', 'timer');
  card.appendChild(clock);
  const long = el('div', 'time-long');
  long.hidden = true;
  card.appendChild(long);
  const actions = el('div', 'time-timer-actions');
  const stop = el('button', 'button-primary', 'Stop and save');
  stop.type = 'button';
  stop.dataset.track = 'time-stop';
  stop.addEventListener('click', function () { ctx.stopTimer(); });
  const discard = el('button', 'button-ghost', 'Discard');
  discard.type = 'button';
  discard.dataset.track = 'time-discard';
  discard.addEventListener('click', function () { ctx.discardTimer(); });
  actions.append(stop, discard);
  card.appendChild(actions);
  log.timer.replaceChildren(card);
  tick(ctx);
}

/** Once a second: the running clock and, past the long-timer threshold,
 *  the "was this forgotten?" correction (shown once, never rebuilt). */
export function tick(ctx) {
  const log = ctx.log;
  if (!log.timer) return;
  const t = timerOf(ctx, ctx.st.person);
  const clock = log.timer.querySelector('.time-clock');
  if (!t || !clock) return;
  const ms = serverNow(ctx) - Date.parse(t.started_at);
  clock.textContent = fmtElapsed(ms);
  const long = log.timer.querySelector('.time-long');
  if (long && long.hidden && ms > ctx.st.meta.long_timer_minutes * 60000) {
    long.hidden = false;
    const hours = Math.round(ctx.st.meta.long_timer_minutes / 60 * 10) / 10;
    long.append(el('p', 'time-long-warn', 'This timer has run over ' + hours
      + ' hours. If it was left on by mistake, correct the minutes before saving.'));
    const label = el('label', 'time-long-field');
    label.appendChild(el('span', '', 'Minutes to save'));
    const input = el('input', 'input-native time-minutes');
    input.type = 'number';
    input.inputMode = 'numeric';
    input.min = '1';
    input.max = String(ctx.st.meta.max_minutes);
    input.value = String(Math.min(ctx.st.meta.max_minutes, Math.round(ms / 60000)));
    input.id = 'timeLongMinutes';
    label.appendChild(input);
    long.appendChild(label);
  }
}

function startRow(ctx, c, area, group) {
  const li = el('li', 'action-row');
  const btn = el('button', 'action-row-main');
  btn.type = 'button';
  btn.dataset.track = 'time-start';
  btn.dataset.categoryId = String(c.id);
  btn.dataset.group = group;
  const running = timerOf(ctx, ctx.st.person);
  const isRunning = running && running.category_id === c.id;
  btn.append(titleText(c.name, isRunning ? 'Running now' : (group === 'recent' ? area.name : c.hint)));
  if (isRunning) btn.setAttribute('aria-current', 'true');
  btn.addEventListener('click', function () { ctx.startTimer(c); });
  li.appendChild(btn);
  return li;
}

export function renderStart(ctx) {
  const parts = [cardHead('play', 'Start a timer')];
  const recent = ctx.st.recent.map(function (id) { return categoryById(ctx, id); }).filter(Boolean);
  if (recent.length) {
    parts.push(el('h3', 'overline time-group-title', 'Recent'));
    const ul = el('ul', 'action-rows');
    recent.forEach(function (r) { ul.appendChild(startRow(ctx, r.category, r.area, 'recent')); });
    parts.push(ul);
  }
  ctx.st.meta.areas.forEach(function (a) {
    if (a.archived) return;
    const cats = a.categories.filter(function (c) { return !c.archived; });
    if (!cats.length) return;
    parts.push(el('h3', 'overline time-group-title', a.name));
    const ul = el('ul', 'action-rows');
    cats.forEach(function (c) { ul.appendChild(startRow(ctx, c, a, a.slug)); });
    parts.push(ul);
  });
  ctx.log.start.replaceChildren.apply(ctx.log.start, parts);
}
