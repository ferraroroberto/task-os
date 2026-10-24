/* task-os — the Time tab's frame: show / hide, the poll, the three views and
 * the header line. */

'use strict';

import { emptyStateEl } from '../../_vendored/empty-state/empty-state.js';
import { fmtMinutes } from '../../time-format.js';
import { loadMeta, refreshLive, refreshRecent, timerOf } from './data.js';
import { loadHistory } from './history.js';
import { buildLog, renderGlance, renderTimer, tick, timerSignature } from './log.js';
import { renderPicker } from './picker.js';
import { loadTotals } from './totals.js';

const POLL_MS = 15000;

export function show(ctx) {
  const st = ctx.st;
  st.shown = true;
  loadMeta(ctx).then(function () {
    if (!st.shown) return;
    rerender(ctx);
    startPolling(ctx);
  }).catch(function () {
    ctx.els.log.replaceChildren(emptyStateEl('triangle-alert', 'Could not read the time tracker', {
      actionLabel: 'Retry', onAction: function () { show(ctx); },
    }));
    showView(ctx, 'log');
  });
}

export function hide(ctx) {
  ctx.st.shown = false;
  stopPolling(ctx);
  ctx.historyMenu.close();
}

function startPolling(ctx) {
  const st = ctx.st;
  stopPolling(ctx);
  st.poll = window.setInterval(function () {
    if (!st.shown || document.hidden) return;
    const before = timerSignature(timerOf(ctx, st.person));
    refreshLive(ctx).then(function () {
      renderGlance(ctx);
      // Rebuild the timer card only when the running timer itself changed
      // (stopped/switched/started elsewhere) — a same-timer poll must never
      // discard a typed "minutes to save" correction or steal focus.
      if (timerSignature(timerOf(ctx, st.person)) !== before) renderTimer(ctx);
    }).catch(function () {});
  }, POLL_MS);
  st.tick = window.setInterval(function () { tick(ctx); }, 1000);
}

function stopPolling(ctx) {
  const st = ctx.st;
  if (st.poll) window.clearInterval(st.poll);
  if (st.tick) window.clearInterval(st.tick);
  st.poll = st.tick = null;
}

/** Everything, from fresh reads: what a show, a person change or a category edit needs. */
export async function rerender(ctx) {
  const st = ctx.st;
  const els = ctx.els;
  if (!st.meta || !st.shown) return;
  const needPicker = !st.person;
  els.picker.hidden = !needPicker;
  els.views.hidden = needPicker;
  if (needPicker) {
    [els.log, els.totals, els.history].forEach(function (v) { v.hidden = true; });
    renderPicker(ctx);
    ctx.opts.onHead();
    return;
  }
  try {
    await Promise.all([refreshLive(ctx), refreshRecent(ctx)]);
  } catch (_) {
    els.log.replaceChildren(emptyStateEl('triangle-alert', 'Could not read the time tracker', {
      actionLabel: 'Retry', onAction: function () { rerender(ctx); },
    }));
    showView(ctx, 'log');
    return;
  }
  buildLog(ctx);
  showView(ctx, st.view);
}

export function showView(ctx, view) {
  const els = ctx.els;
  ctx.st.view = view;
  els.views.querySelectorAll('.segmented-item').forEach(function (b) {
    b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false');
  });
  els.log.hidden = view !== 'log';
  els.totals.hidden = view !== 'totals';
  els.history.hidden = view !== 'history';
  if (view === 'totals') loadTotals(ctx);
  if (view === 'history') loadHistory(ctx, false);
}

export function wireViews(ctx) {
  ctx.els.views.addEventListener('click', function (ev) {
    const b = ev.target.closest('.segmented-item');
    if (b && ctx.st.person) showView(ctx, b.dataset.view);
  });
}

/** The header's context line: who has a timer running, else this device
 *  person's time today. Empty until the tab has read anything. */
export function headText(ctx) {
  const st = ctx.st;
  if (!st.meta || !st.todaySummary) return '';
  if (st.timers.length) return st.timers.length + ' running';
  const mine = st.person ? st.todaySummary.by_person[st.person] || 0 : st.todaySummary.total_minutes;
  return mine ? fmtMinutes(mine) + ' today' : 'Nothing logged today';
}
