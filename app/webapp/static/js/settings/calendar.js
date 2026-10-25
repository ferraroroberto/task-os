/* task-os — the Today lane's private ICS feed: its status rows and
 * "Refresh now". */

'use strict';

import { api } from '../../api.js';
import { codeEl, fmtTsShort, statusPart } from '../../format.js';
import { toast } from '../../toast.js';
import { setWord } from './words.js';

//: The state word in the row and the card header, per `calendar.state`.
const CALENDAR_WORDS = {
  ok: 'reading', bad_url: 'address refused', unreachable: 'unreachable',
  timeout: 'timed out', parse_error: 'not a calendar',
};

/** The Today lane's half of `GET /api/status`. Off always carries its
 *  reason; every failure keeps its own word; `null` = the status call itself
 *  failed, which is "unknown", not "off". The source is the host only — the
 *  address is a secret and the API never sends it. */
export function renderCalendar(ctx, st) {
  const rows = [ctx.els.statusCalendar, ctx.els.statusCalendarSource, ctx.els.statusCalendarFetched];
  rows.forEach(function (dd) { dd.replaceChildren(); dd.classList.remove('muted'); });
  ctx.els.calendarRefresh.disabled = !(st && st.configured && st.state !== 'off');
  if (!st) {
    rows.forEach(function (dd) { dd.textContent = 'unknown'; });
    setWord(ctx, ctx.els.calendarCardMeta, 'unknown');
    return;
  }
  if (!st.configured || st.state === 'off') {
    ctx.els.statusCalendar.append(statusPart('off', 'not configured'), ' — ' + (st.reason || 'unknown'));
    ctx.els.statusCalendarSource.textContent = '–';
    ctx.els.statusCalendarFetched.textContent = '–';
    setWord(ctx, ctx.els.calendarCardMeta, 'off');
    return;
  }
  const ok = st.state === 'ok';
  const word = CALENDAR_WORDS[st.state] || st.state;
  ctx.els.statusCalendar.append(statusPart(ok ? 'ok' : 'warn', word));
  if (!ok && st.failing_since) ctx.els.statusCalendar.append(' since ' + fmtTsShort(st.failing_since));
  if (ok && st.events_today != null) {
    ctx.els.statusCalendar.append(' · ' + st.events_today + ' event(s) today');
  }
  if (st.skipped_recurring) ctx.els.statusCalendar.append(' · ' + st.skipped_recurring + ' recurring not checked');
  if (st.unreadable) ctx.els.statusCalendar.append(' · ' + st.unreadable + ' unreadable');
  if (st.error) ctx.els.statusCalendar.append(' — ' + st.error);
  ctx.els.statusCalendarSource.append(st.source ? codeEl(st.source) : 'unknown');
  ctx.els.statusCalendarSource.append(' · every ' + st.refresh_minutes + ' min · ' + st.timeout_seconds + ' s timeout');
  ctx.els.statusCalendarFetched.textContent = st.fetched_at
    ? fmtTsShort(st.fetched_at) + (st.stale ? ' (stale)' : '') : 'never';
  setWord(ctx, ctx.els.calendarCardMeta, ok ? 'on' : (st.stale ? 'stale' : 'error'));
}

export function wireCalendarRefresh(ctx) {
  ctx.els.calendarRefresh.addEventListener('click', async function () {
    ctx.els.calendarRefresh.disabled = true;
    try {
      const group = await api('/api/calendar/refresh', { method: 'POST', body: {} });
      ctx.opts.onCalendar(group);
      if (group.state === 'ok') {
        toast('Calendar: ' + (group.events.length + group.all_day.length) + ' event(s) today', 'success');
      } else {
        toast('Calendar: ' + (CALENDAR_WORDS[group.state] || group.state) + ' — ' + (group.error || group.reason || 'unknown'), 'error');
      }
    } catch (err) { toast(err.message || 'Refresh failed', 'error'); }
    ctx.refreshStatus();
  });
}
