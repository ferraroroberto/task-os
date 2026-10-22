/* task-os — the Time tab (#457): a time tracker with household shares.
 *
 * Three views in one segmented control, all over `/api/time/*`
 * (`src/time_repo.py` owns every rule; this file only draws and asks):
 *
 *   Log      today per person (the glance card), this device's running
 *            timer (Stop and save · Discard; past `long_timer_minutes` a
 *            "minutes to save" correction), the start list (Recent first,
 *            then by area — a tap starts, or offers Switch while one runs)
 *            and Add time already spent
 *   Totals   Today · 7 days · 30 days · All, an area filter and, outside the
 *            compare area, Me · Everyone; on the compare area with two or
 *            more people, the household comparison: head-to-head, the split
 *            bar, coverage, the guess card, the per-category bars. With two
 *            or more people it opens there, at 30 days (the prototype's
 *            Totals, #463), and the comparison and the guess card stay up
 *            with nothing logged: only the bars give way to the empty state
 *   History  date-grouped rows, a filter above 12, "Show older entries";
 *            the row (and its menu's Edit) opens the editor, Start again,
 *            Delete last behind the confirm
 *
 * Nothing loads until the tab is first shown (`show()`), so Today's first
 * paint makes no `/api/time` call. While the tab is up the timers and today's
 * totals are re-read every POLL_MS, so a timer the other device started
 * appears without a reload. "Today" is always the server's.
 *
 * The tab logs as whoever is signed in (#475): `/api/time/meta` says who
 * (`you`), so there is no per-device picker and nothing is stored. Only a
 * request that is no member (a team sign-in whose name matches nobody) is
 * asked once per visit, in memory. People are told apart by their initial and,
 * in the bars, by solid vs hatched fill — never a second hue.
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';
import { createRowMenu } from './_vendored/row-menu/row-menu.js';
import { api, qs } from './api.js';
import { confirmDialog } from './confirm.js';
import { askSwitch, openEntryEditor, showInfo } from './time-dialogs.js';
import {
  clockOf, dayLabel, entrySpan, fmtElapsed, fmtMinutes, initialOf,
} from './time-format.js';
import { mountTimeSettings } from './time-settings.js';
import { toast } from './toast.js';

//: The per-device person key #457 stored; ignored since #475 and removed on the first read.
const STALE_PERSON_KEY = 'task-os.time.person';
const POLL_MS = 15000;
const HISTORY_PAGE = 50;
const FILTER_ABOVE = 12;   // design.md action-row.filterAboveRows
//: The Totals periods, in order (an object would list 7 and 30 first).
const PERIODS = [['today', 'Today'], ['7', '7 days'], ['30', '30 days'], ['all', 'All']];
const PERIOD_LABELS = Object.fromEntries(PERIODS);
//: Bars tell people apart by fill, never by hue: the first solid, then hatched, then dotted.
const FILLS = ['solid', 'hatched', 'dotted'];

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function dropStalePerson() {
  try { localStorage.removeItem(STALE_PERSON_KEY); } catch (_) { /* private mode */ }
}

/**
 * @param {{onHead: () => void}} opts
 * @returns {{show: () => void, hide: () => void, headText: () => string,
 *            settingsShown: () => void, openSheet: (key: string) => void}}
 */
export function mountTime(opts) {
  const els = {
    pane: document.getElementById('paneTime'),
    views: document.getElementById('timeViews'),
    picker: document.getElementById('timePicker'),
    log: document.getElementById('timeLog'),
    totals: document.getElementById('timeTotals'),
    history: document.getElementById('timeHistory'),
  };
  const st = {
    meta: null,
    metaLoad: null,
    skew: 0,                 // server clock − this device's, from the last read
    today: null,             // the server's day
    now: null,               // the server's ISO time at the last read
    person: null,
    view: 'log',
    timers: [],
    todaySummary: null,      // everyone, today: the glance card and the header line
    recent: [],
    totals: { period: null, area: null, who: 'me' },   // null until the meta picks the defaults
    history: { items: [], total: 0, q: '' },
    shown: false,
    poll: null,
    tick: null,
    busy: false,
  };
  const historyMenu = createRowMenu({ className: 'time-menu' });
  const settings = mountTimeSettings({
    meta: function () { return st.meta; },
    onMetaChanged: function () { return loadMeta(true).then(rerender); },
  });

  // ------------------------------------------------------------ loading
  function loadMeta(force) {
    if (st.metaLoad && !force) return st.metaLoad;
    st.metaLoad = api('/api/time/meta').then(function (meta) {
      st.meta = meta;
      st.today = meta.today;
      st.now = meta.now;
      st.skew = Date.parse(meta.now) - Date.now();
      const ids = meta.people.map(function (p) { return p.id; });
      dropStalePerson();
      st.person = ids.length === 1 ? ids[0] : (ids.indexOf(meta.you) >= 0 ? meta.you : st.person);
      if (st.totals.area === null) {
        // first read: the household comparison at 30 days when there is one, else everything at 7
        const compare = ids.length > 1 && meta.areas.some(function (a) { return a.slug === meta.compare_area; });
        st.totals.area = compare ? meta.compare_area : '';
        st.totals.period = compare ? '30' : '7';
      }
      if (st.totals.area && !meta.areas.some(function (a) { return a.slug === st.totals.area; })) st.totals.area = '';
      settings.render();
      return meta;
    }).catch(function (err) {
      st.metaLoad = null;
      throw err;
    });
    return st.metaLoad;
  }

  /** A person's name in a list that holds both people: the viewer's is marked. */
  function nameYou(id) {
    return id === st.person && !solo() ? nameOf(id) + ' (you)' : nameOf(id);
  }
  function solo() { return !st.meta || st.meta.people.length < 2; }
  function nameOf(id) {
    const p = st.meta && st.meta.people.find(function (x) { return x.id === id; });
    return p ? p.name : id;
  }
  function serverNow() { return Date.now() + st.skew; }

  /** Re-read the running timers and today's totals (the poll's whole job). */
  async function refreshLive() {
    const [timers, today] = await Promise.all([
      api('/api/time/timers'),
      api('/api/time/summary' + qs({ period: 'today' })),
    ]);
    st.timers = timers.items;
    st.now = timers.now;
    st.skew = Date.parse(timers.now) - Date.now();
    st.today = today.today;
    st.todaySummary = today;
    opts.onHead();
  }

  async function refreshRecent() {
    if (!st.person) { st.recent = []; return; }
    st.recent = (await api('/api/time/recent' + qs({ person: st.person }))).category_ids;
  }

  // -------------------------------------------------------------- frame
  function show() {
    st.shown = true;
    loadMeta().then(function () {
      if (!st.shown) return;
      rerender();
      startPolling();
    }).catch(function () {
      els.log.replaceChildren(emptyStateEl('triangle-alert', 'Could not read the time tracker', {
        actionLabel: 'Retry', onAction: show,
      }));
      showView('log');
    });
  }

  function hide() {
    st.shown = false;
    stopPolling();
    historyMenu.close();
  }

  function startPolling() {
    stopPolling();
    st.poll = window.setInterval(function () {
      if (!st.shown || document.hidden) return;
      const before = timerSignature(timerOf(st.person));
      refreshLive().then(function () {
        renderGlance();
        // Rebuild the timer card only when the running timer itself changed
        // (stopped/switched/started elsewhere) — a same-timer poll must never
        // discard a typed "minutes to save" correction or steal focus (#502).
        if (timerSignature(timerOf(st.person)) !== before) renderTimer();
      }).catch(function () {});
    }, POLL_MS);
    st.tick = window.setInterval(tick, 1000);
  }

  function stopPolling() {
    if (st.poll) window.clearInterval(st.poll);
    if (st.tick) window.clearInterval(st.tick);
    st.poll = st.tick = null;
  }

  /** Everything, from fresh reads: what a show, a person change or a category edit needs. */
  async function rerender() {
    if (!st.meta || !st.shown) return;
    const needPicker = !st.person;
    els.picker.hidden = !needPicker;
    els.views.hidden = needPicker;
    if (needPicker) {
      [els.log, els.totals, els.history].forEach(function (v) { v.hidden = true; });
      renderPicker();
      opts.onHead();
      return;
    }
    try {
      await Promise.all([refreshLive(), refreshRecent()]);
    } catch (_) {
      els.log.replaceChildren(emptyStateEl('triangle-alert', 'Could not read the time tracker', {
        actionLabel: 'Retry', onAction: rerender,
      }));
      showView('log');
      return;
    }
    buildLog();
    showView(st.view);
  }

  function showView(view) {
    st.view = view;
    els.views.querySelectorAll('.segmented-item').forEach(function (b) {
      b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false');
    });
    els.log.hidden = view !== 'log';
    els.totals.hidden = view !== 'totals';
    els.history.hidden = view !== 'history';
    if (view === 'totals') loadTotals();
    if (view === 'history') loadHistory(false);
  }

  els.views.addEventListener('click', function (ev) {
    const b = ev.target.closest('.segmented-item');
    if (b && st.person) showView(b.dataset.view);
  });

  function setPerson(id) {
    st.person = id;
    rerender();
  }

  // ------------------------------------------------------------- picker
  function renderPicker() {
    const card = el('section', 'card action-list time-picker-card');
    const head = el('div', 'time-card-head');
    head.append(el('h2', 'time-card-title', 'Who is tracking time?'));
    const note = el('p', 'muted time-card-note', 'This sign-in is not one of the members, so say who this is for. Only a label for this visit.');
    const list = el('ul', 'action-rows');
    st.meta.people.forEach(function (p) {
      const li = el('li', 'action-row');
      const btn = el('button', 'action-row-main');
      btn.type = 'button';
      btn.dataset.track = 'time-pick-person';
      btn.append(avatar(p.name), titleText(p.name));
      btn.addEventListener('click', function () { setPerson(p.id); });
      li.appendChild(btn);
      list.appendChild(li);
    });
    card.append(head, note, list);
    els.picker.replaceChildren(card);
  }

  function avatar(name) {
    const a = el('span', 'action-row-avatar time-avatar', initialOf(name));
    a.setAttribute('aria-hidden', 'true');
    return a;
  }

  /** The small sample of a person's bar fill beside their name: the key to the bars. */
  function swatch(fill) {
    const s = el('span', 'time-fill time-swatch');
    s.dataset.fill = fill;
    s.setAttribute('aria-hidden', 'true');
    return s;
  }

  function titleText(title, meta) {
    const t = el('span', 'action-row-text');
    t.appendChild(el('span', 'action-row-title', title));
    if (meta) t.appendChild(el('span', 'action-row-meta', meta));
    return t;
  }

  function cardHead(glyph, title, extra) {
    const head = el('div', 'time-card-head');
    const h = el('h2', 'time-card-title');
    h.innerHTML = icon(glyph);
    h.appendChild(document.createTextNode(title));
    head.appendChild(h);
    if (extra) head.appendChild(extra);
    return head;
  }

  // ---------------------------------------------------------------- log
  const log = { glance: null, timer: null, start: null };

  function buildLog() {
    log.glance = el('section', 'card action-list time-glance');
    log.timer = el('div', 'time-timer-slot');
    log.start = el('section', 'card action-list time-start');
    const add = el('button', 'button-tint time-add', 'Add time already spent');
    add.type = 'button';
    add.dataset.track = 'time-add';
    add.addEventListener('click', addEntry);
    els.log.replaceChildren(log.glance, log.timer, log.start, add);
    renderGlance();
    renderTimer();
    renderStart();
  }

  function timerOf(person) {
    return st.timers.find(function (t) { return t.person === person; }) || null;
  }

  /** Identity of the running timer card — same person/category/start means the
   *  poll must leave the card (and any typed correction) alone. */
  function timerSignature(t) {
    return t ? [t.person, t.category_id, t.started_at].join('|') : null;
  }

  function renderGlance() {
    if (!log.glance) return;
    const s = st.todaySummary;
    const list = el('ul', 'action-rows');
    st.meta.people.forEach(function (p) {
      const li = el('li', 'action-row time-glance-row');
      const main = el('div', 'action-row-main');
      const running = timerOf(p.id);
      main.append(avatar(p.name), titleText(p.name, running ? 'Timer running · ' + running.category_name : ''));
      const mins = s ? s.by_person[p.id] || 0 : null;
      const value = el('span', 'action-row-value time-glance-value' + (mins ? '' : ' muted'),
        mins === null ? '–' : (mins ? fmtMinutes(mins) : 'Nothing yet'));
      li.append(main, value);
      list.appendChild(li);
    });
    log.glance.replaceChildren(cardHead('clock', 'Today so far'), list);
  }

  function renderTimer() {
    if (!log.timer) return;
    const t = timerOf(st.person);
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
    stop.addEventListener('click', function () { stopTimer(t); });
    const discard = el('button', 'button-ghost', 'Discard');
    discard.type = 'button';
    discard.dataset.track = 'time-discard';
    discard.addEventListener('click', function () { discardTimer(); });
    actions.append(stop, discard);
    card.appendChild(actions);
    log.timer.replaceChildren(card);
    tick();
  }

  /** Once a second: the running clock and, past the long-timer threshold,
   *  the "was this forgotten?" correction (shown once, never rebuilt). */
  function tick() {
    if (!log.timer) return;
    const t = timerOf(st.person);
    const clock = log.timer.querySelector('.time-clock');
    if (!t || !clock) return;
    const ms = serverNow() - Date.parse(t.started_at);
    clock.textContent = fmtElapsed(ms);
    const long = log.timer.querySelector('.time-long');
    if (long && long.hidden && ms > st.meta.long_timer_minutes * 60000) {
      long.hidden = false;
      const hours = Math.round(st.meta.long_timer_minutes / 60 * 10) / 10;
      long.append(el('p', 'time-long-warn', 'This timer has run over ' + hours
        + ' hours. If it was left on by mistake, correct the minutes before saving.'));
      const label = el('label', 'time-long-field');
      label.appendChild(el('span', '', 'Minutes to save'));
      const input = el('input', 'input-native time-minutes');
      input.type = 'number';
      input.inputMode = 'numeric';
      input.min = '1';
      input.max = String(st.meta.max_minutes);
      input.value = String(Math.min(st.meta.max_minutes, Math.round(ms / 60000)));
      input.id = 'timeLongMinutes';
      label.appendChild(input);
      long.appendChild(label);
    }
  }

  function categoryById(id) {
    for (const a of st.meta.areas) {
      const c = a.categories.find(function (x) { return x.id === id; });
      if (c) return { area: a, category: c };
    }
    return null;
  }

  function startRow(c, area, group) {
    const li = el('li', 'action-row');
    const btn = el('button', 'action-row-main');
    btn.type = 'button';
    btn.dataset.track = 'time-start';
    btn.dataset.categoryId = String(c.id);
    btn.dataset.group = group;
    const running = timerOf(st.person);
    const isRunning = running && running.category_id === c.id;
    btn.append(titleText(c.name, isRunning ? 'Running now' : (group === 'recent' ? area.name : c.hint)));
    if (isRunning) btn.setAttribute('aria-current', 'true');
    btn.addEventListener('click', function () { startTimer(c); });
    li.appendChild(btn);
    return li;
  }

  function renderStart() {
    const parts = [cardHead('play', 'Start a timer')];
    const recent = st.recent.map(categoryById).filter(Boolean);
    if (recent.length) {
      parts.push(el('h3', 'overline time-group-title', 'Recent'));
      const ul = el('ul', 'action-rows');
      recent.forEach(function (r) { ul.appendChild(startRow(r.category, r.area, 'recent')); });
      parts.push(ul);
    }
    st.meta.areas.forEach(function (a) {
      if (a.archived) return;
      const cats = a.categories.filter(function (c) { return !c.archived; });
      if (!cats.length) return;
      parts.push(el('h3', 'overline time-group-title', a.name));
      const ul = el('ul', 'action-rows');
      cats.forEach(function (c) { ul.appendChild(startRow(c, a, a.slug)); });
      parts.push(ul);
    });
    log.start.replaceChildren.apply(log.start, parts);
  }

  async function afterTimerChange() {
    await Promise.all([refreshLive(), refreshRecent()]);
    renderGlance();
    renderTimer();
    renderStart();
  }

  async function startTimer(c) {
    if (st.busy) return;
    const running = timerOf(st.person);
    if (running && running.category_id === c.id) return;
    let doSwitch = false;
    if (running) {
      doSwitch = await askSwitch({ from: running.category_name, to: c.name });
      if (!doSwitch) return;
    }
    st.busy = true;
    try {
      const out = await api('/api/time/timers', {
        method: 'POST', body: { person: st.person, category_id: c.id, switch: doSwitch },
      });
      toast(out.entry ? 'Saved ' + fmtMinutes(out.entry.minutes) + ' of ' + out.entry.category_name
        + '; started ' + c.name : 'Started ' + c.name);
    } catch (err) {
      if (err.code === 'timer_running') {
        // Started on another device meanwhile: say why, then offer the switch.
        st.busy = false;
        await afterTimerChange();
        const other = timerOf(st.person);
        toast('A timer is already running for you' + (other ? ': ' + other.category_name : ''));
        if (other) return startTimer(c);
        return;
      }
      toast(err.message, 'error');
    } finally {
      st.busy = false;
    }
    await afterTimerChange();
  }

  async function stopTimer() {
    if (st.busy) return;
    const input = document.getElementById('timeLongMinutes');
    const body = {};
    if (input && Number(input.value) > 0) body.minutes = Math.round(Number(input.value));
    st.busy = true;
    try {
      const entry = await api('/api/time/timers/' + encodeURIComponent(st.person) + '/stop', { method: 'POST', body: body });
      toast('Saved ' + fmtMinutes(entry.minutes) + ' of ' + entry.category_name);
    } catch (err) {
      toast(err.code === 'no_timer' ? 'That timer was already stopped on another device' : err.message, 'error');
    } finally {
      st.busy = false;
    }
    await afterTimerChange();
  }

  async function discardTimer() {
    if (st.busy) return;
    st.busy = true;
    try {
      await api('/api/time/timers/' + encodeURIComponent(st.person), { method: 'DELETE' });
      toast('Timer discarded');
    } catch (err) {
      toast(err.code === 'no_timer' ? 'That timer was already stopped on another device' : err.message, 'error');
    } finally {
      st.busy = false;
    }
    await afterTimerChange();
  }

  async function addEntry() {
    const saved = await openEntryEditor({ meta: st.meta, person: st.person, today: st.today, now: st.now });
    if (!saved) return;
    toast('Saved ' + fmtMinutes(saved.minutes) + ' for ' + nameOf(saved.person));
    await afterTimerChange();
  }

  // ------------------------------------------------------------- totals
  function totalsQuery() {
    const t = st.totals;
    const compare = !solo() && t.area && t.area === st.meta.compare_area;
    return {
      period: t.period, area: t.area,
      person: compare || solo() || t.who === 'all' ? '' : st.person,
      compare: compare,
    };
  }

  function segmented(label, items, current, onPick, cls) {
    const seg = el('div', 'segmented' + (cls ? ' ' + cls : ''));
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', label);
    items.forEach(function (it) {
      const b = el('button', 'segmented-item', it.label);
      b.type = 'button';
      b.dataset.value = it.value;
      if (it.track) b.dataset.track = it.track;
      b.setAttribute('aria-pressed', String(it.value) === String(current) ? 'true' : 'false');
      b.addEventListener('click', function () { onPick(it.value); });
      seg.appendChild(b);
    });
    return seg;
  }

  function totalsControls(q) {
    const bar = el('div', 'time-controls');
    bar.appendChild(segmented('Period', PERIODS.map(function (pair) {
      return { value: pair[0], label: pair[1], track: 'time-period' };
    }), st.totals.period, function (v) { st.totals.period = v; loadTotals(); }, 'time-period'));
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
    area.addEventListener('change', function () { st.totals.area = area.value; loadTotals(); });
    bar.appendChild(area);
    if (!solo() && !q.compare) {
      bar.appendChild(segmented('Whose time', [
        { value: 'me', label: 'Me', track: 'time-who' },
        { value: 'all', label: 'Everyone', track: 'time-who' },
      ], st.totals.who, function (v) { st.totals.who = v; loadTotals(); }, 'time-who'));
    }
    return bar;
  }

  async function loadTotals() {
    const q = totalsQuery();
    let summary;
    let guesses = null;
    try {
      [summary, guesses] = await Promise.all([
        api('/api/time/summary' + qs({ period: q.period, area: q.area, person: q.person })),
        q.compare ? api('/api/time/guesses/' + encodeURIComponent(st.person)) : Promise.resolve(null),
      ]);
    } catch (_) {
      els.totals.replaceChildren(totalsControls(q), emptyStateEl('triangle-alert', 'Could not read the totals', {
        actionLabel: 'Retry', onAction: loadTotals,
      }));
      return;
    }
    renderTotals(q, summary, guesses);
  }

  function fillFor(person) {
    const i = st.meta.people.findIndex(function (p) { return p.id === person; });
    return FILLS[Math.max(0, i) % FILLS.length];
  }

  function renderTotals(q, s, guesses) {
    const parts = [totalsControls(q)];
    const people = Object.keys(s.by_person);
    // the comparison and the guess card stand with nothing logged (a guess can come first)
    if (q.compare) parts.push(compareCard(s, people), guessCard(s, people, guesses));
    if (!s.total_minutes) {
      parts.push(emptyStateEl('clock', 'Nothing logged in this period', {
        actionLabel: 'Log some time', onAction: function () { showView('log'); },
      }));
      els.totals.replaceChildren.apply(els.totals, parts);
      return;
    }
    if (!q.compare) {
      const sum = el('section', 'card action-list time-sum');
      const ul = el('ul', 'action-rows');
      const total = el('li', 'action-row time-sum-row');
      const totalMain = el('div', 'action-row-main');
      totalMain.appendChild(titleText('Total', q.person ? nameOf(q.person) : (solo() ? '' : 'Everyone')));
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
          main.append(avatar(nameOf(p)), titleText(nameYou(p)));
          li.append(main, el('span', 'action-row-value', fmtMinutes(s.by_person[p])));
          ul.appendChild(li);
        });
      }
      sum.append(cardHead('clock', PERIOD_LABELS[s.period]), ul);
      parts.push(sum);
    }
    parts.push(categoryCard(s, people));
    const csv = el('a', 'button-surface time-csv');
    csv.href = '/api/time/entries.csv' + qs({ period: q.period, area: q.area, person: q.person });
    csv.setAttribute('download', '');
    csv.dataset.track = 'time-csv';
    csv.innerHTML = icon('download');
    csv.appendChild(document.createTextNode('Download CSV'));
    parts.push(csv);
    els.totals.replaceChildren.apply(els.totals, parts);
  }

  function compareCard(s, people) {
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
    const area = st.meta.areas.find(function (a) { return a.slug === s.area; });
    card.appendChild(cardHead('activity', (area ? area.name : 'Area') + ' · ' + PERIOD_LABELS[s.period], info));
    const h2h = el('div', 'time-h2h');
    people.forEach(function (p) {
      const col = el('div', 'time-h2h-person');
      const name = el('div', 'time-h2h-name');
      name.append(avatar(nameOf(p)), document.createTextNode(nameYou(p)), swatch(fillFor(p)));
      col.append(name, el('div', 'time-h2h-big', fmtMinutes(s.by_person[p])),
        el('div', 'muted time-h2h-pct', s.total_minutes ? share(p) + '% of logged time' : 'nothing logged'));
      h2h.appendChild(col);
    });
    const split = el('div', 'time-split');
    split.setAttribute('role', 'img');
    split.setAttribute('aria-label', s.total_minutes ? people.map(function (p) {
      return nameOf(p) + ' ' + share(p) + '%';
    }).join(', ') : 'Nothing logged yet');
    people.forEach(function (p) {
      const f = el('span', 'time-fill');
      f.dataset.fill = fillFor(p);
      f.style.width = (s.total_minutes ? s.by_person[p] / s.total_minutes * 100 : 0) + '%';
      split.appendChild(f);
    });
    const coverage = el('p', 'muted time-coverage', 'Days with something logged: ' + people.map(function (p) {
      return nameOf(p) + ' ' + s.days_logged[p] + ' of ' + s.span_days;
    }).join(', ') + '.');
    card.append(h2h, split, coverage);
    return card;
  }

  function guessCard(s, people, g) {
    const card = el('section', 'card time-guess');
    card.appendChild(cardHead('user', 'Guess your share'));
    if (!g || !g.mine) {
      card.appendChild(el('p', 'muted time-card-note',
        'Before you look: what share of this time do you think is yours? The other answers stay hidden until yours is in.'));
      card.appendChild(guessForm(null));
      return card;
    }
    const mine = el('p', 'time-guess-mine');
    mine.append('Your guess: ', el('strong', '', g.mine.pct + '%'), ' ');
    const change = el('button', 'button-ghost time-guess-change', 'Change');
    change.type = 'button';
    change.dataset.track = 'time-guess-change';
    change.addEventListener('click', function () { mine.replaceWith(guessForm(g.mine.pct)); });
    mine.appendChild(change);
    card.appendChild(mine);
    const others = people.filter(function (p) { return p !== st.person; });
    const missing = others.filter(function (p) { return !(g.others && g.others[p]); });
    if (missing.length) {
      card.appendChild(el('p', 'muted time-card-note', missing.map(nameOf).join(', ') + (missing.length > 1 ? ' have' : ' has') + ' not guessed yet.'));
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
      who.append(avatar(nameOf(p)), document.createTextNode(nameYou(p)), swatch(fillFor(p)));
      tr.append(who, el('td', '', pct + '%'),
        el('td', '', s.total_minutes ? Math.round(s.by_person[p] / s.total_minutes * 100) + '%' : '–'));
      tbody.appendChild(tr);
    });
    table.append(thead, tbody);
    card.append(table, el('p', 'muted time-card-note', 'The guesses add up to ' + sum + '%. Accurate views would add up to 100%.'));
    return card;
  }

  function guessForm(current) {
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
        await api('/api/time/guesses/' + encodeURIComponent(st.person), { method: 'PUT', body: { pct: v } });
        loadTotals();
      } catch (err) {
        msg.textContent = err.message;
      }
    });
    return form;
  }

  function categoryCard(s, people) {
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
        track.title = nameOf(p) + ' ' + fmtMinutes(v);
        const fill = el('span', 'time-fill');
        fill.dataset.fill = fillFor(p);
        fill.style.width = (v ? Math.max(1, v / max * 100) : 0) + '%';
        track.appendChild(fill);
        if (people.length > 1) line.appendChild(el('span', 'time-initial', initialOf(nameOf(p))));
        line.append(track, el('span', 'time-bar-value' + (v ? '' : ' muted'), v ? fmtMinutes(v) : '–'));
        block.appendChild(line);
      });
      card.appendChild(block);
    });
    return card;
  }

  // ------------------------------------------------------------ history
  async function loadHistory(more) {
    const h = st.history;
    let page;
    try {
      page = await api('/api/time/entries' + qs({ q: h.q, limit: HISTORY_PAGE, offset: more ? h.items.length : 0 }));
    } catch (_) {
      els.history.replaceChildren(emptyStateEl('triangle-alert', 'Could not read the history', {
        actionLabel: 'Retry', onAction: function () { loadHistory(false); },
      }));
      return;
    }
    h.items = more ? h.items.concat(page.items) : page.items;
    h.total = page.total;
    renderHistory();
  }

  let filterTimer = null;
  function renderHistory() {
    const h = st.history;
    const parts = [];
    if (h.total > FILTER_ABOVE || h.q) {
      const label = el('label', 'action-row-filter time-filter');
      label.innerHTML = icon('search');
      const input = el('input');
      input.type = 'search';
      input.placeholder = 'Filter ' + h.total + ' entries…';
      input.setAttribute('aria-label', 'Filter entries');
      input.value = h.q;
      input.addEventListener('input', function () {
        window.clearTimeout(filterTimer);
        filterTimer = window.setTimeout(function () {
          h.q = input.value.trim();
          loadHistory(false).then(function () {
            const again = els.history.querySelector('.time-filter input');
            if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
          });
        }, 250);
      });
      label.appendChild(input);
      parts.push(label);
    }
    if (!h.items.length) {
      parts.push(h.q ? emptyStateEl('search', 'No entry matches', {
        actionLabel: 'Clear filter', onAction: function () { h.q = ''; loadHistory(false); },
      }) : emptyStateEl('clock', 'Nothing logged yet', {
        actionLabel: 'Log some time', onAction: function () { showView('log'); },
      }));
      els.history.replaceChildren.apply(els.history, parts);
      historyMenu.endRender();
      return;
    }
    let day = null;
    let list = null;
    h.items.forEach(function (e) {
      if (e.day !== day) {
        day = e.day;
        parts.push(el('h3', 'overline time-group-title', dayLabel(day, st.today)));
        const card = el('section', 'card action-list time-history-day');
        list = el('ul', 'action-rows');
        card.appendChild(list);
        parts.push(card);
      }
      list.appendChild(historyRow(e));
    });
    if (h.items.length < h.total) {
      const more = el('button', 'button-surface time-more', 'Show older entries');
      more.type = 'button';
      more.dataset.track = 'time-more';
      more.addEventListener('click', function () { loadHistory(true); });
      parts.push(more);
    }
    els.history.replaceChildren.apply(els.history, parts);
    historyMenu.endRender();
  }

  function historyRow(e) {
    const li = el('li', 'action-row time-entry');
    li.dataset.id = String(e.id);
    const main = el('button', 'action-row-main');
    main.type = 'button';
    main.dataset.track = 'time-edit';
    main.setAttribute('aria-haspopup', 'dialog');
    const meta = [entrySpan(e)];
    if (!solo()) meta.push(nameOf(e.person));
    if (e.note) meta.push(e.note);
    main.append(avatar(nameOf(e.person)), titleText(e.category_name, meta.join(' · ')));
    main.addEventListener('click', function () { editEntry(e); });
    const kebab = el('button', 'icon-button action-row-kebab');
    kebab.type = 'button';
    kebab.setAttribute('aria-label', 'More actions');
    kebab.setAttribute('aria-haspopup', 'menu');
    kebab.setAttribute('aria-expanded', 'false');
    kebab.innerHTML = icon('ellipsis-vertical');
    historyMenu.attach(e.id, kebab, [
      { label: 'Edit', glyph: 'pencil', onTap: function () { editEntry(e); } },
      { label: 'Start again', glyph: 'play', onTap: function () { startAgain(e); } },
      { label: 'Delete', glyph: 'trash-2', danger: true, onTap: function () { deleteEntry(e); } },
    ]);
    li.append(main, kebab);
    return li;
  }

  async function editEntry(e) {
    const saved = await openEntryEditor({ meta: st.meta, person: st.person, today: st.today, now: st.now, entry: e });
    if (saved) toast('Entry saved');
    await Promise.all([loadHistory(false), refreshLive()]);
  }

  async function startAgain(e) {
    const found = categoryById(e.category_id);
    if (!found || found.category.archived || found.area.archived) {
      toast(e.category_name + ' is archived, so it cannot be started', 'error');
      return;
    }
    await startTimer(found.category);
    showView('log');
  }

  async function deleteEntry(e) {
    const ok = await confirmDialog({
      title: 'Delete this entry?',
      lines: [e.category_name + ', ' + dayLabel(e.day, st.today) + ': ' + entrySpan(e) + (solo() ? '' : ', ' + nameOf(e.person)) + '.'],
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
    await Promise.all([loadHistory(false), refreshLive()]);
  }

  // ------------------------------------------------------------- header
  /** The header's context line: who has a timer running, else this device
   *  person's time today. Empty until the tab has read anything. */
  function headText() {
    if (!st.meta || !st.todaySummary) return '';
    if (st.timers.length) return st.timers.length + ' running';
    const mine = st.person ? st.todaySummary.by_person[st.person] || 0 : st.todaySummary.total_minutes;
    return mine ? fmtMinutes(mine) + ' today' : 'Nothing logged today';
  }

  return {
    show: show,
    hide: hide,
    headText: headText,
    /** Settings is up: its two Time rows read the meta, loaded on demand. */
    settingsShown: function () { loadMeta().then(function () { settings.render(); }).catch(function () {}); },
    openSheet: function (key) {
      loadMeta().then(function () { settings.openSheet(key); }).catch(function () {});
    },
  };
}
