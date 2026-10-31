/* task-os — how the Time tab writes durations, clock times and days.
 *
 * Shared by time.js, time-dialogs.js and time-settings.js. Every day here is
 * the server's (`/api/time/meta` → `today`): a phone in another zone never
 * shifts an entry's day, so nothing below reads the browser's calendar.
 */

'use strict';

import { addDays, fmtDay } from './format.js';

/** 90 → "1h 30m", 120 → "2h", 45 → "45m", 0 → "0m". */
export function fmtMinutes(min) {
  const m = Math.max(0, Math.round(min || 0));
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (!h) return r + 'm';
  return r ? h + 'h ' + r + 'm' : h + 'h';
}

/** The wall-clock HH:MM an ISO timestamp was written with (the server's zone). */
export function clockOf(iso) {
  return iso ? iso.slice(11, 16) : '';
}

/** An entry's time line: "09:10 to 10:40 · 1h 30m", or the duration alone
 *  for an entry without a clock range (an imported one). */
export function entrySpan(e) {
  const dur = fmtMinutes(e.minutes);
  return e.started_at ? clockOf(e.started_at) + ' to ' + clockOf(e.ended_at) + ' · ' + dur : dur;
}

/** "Today", "Yesterday", else "Mon 7 Sep" — relative to the server's `today`. */
export function dayLabel(day, today) {
  if (day === today) return 'Today';
  if (day === addDays(today, -1)) return 'Yesterday';
  return fmtDay(day);
}

/** A running timer's clock: "4:05" under an hour, "1:04:05" past it. */
export function fmtElapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = function (n) { return String(n).padStart(2, '0'); };
  return (h ? h + ':' + pad(m) : m) + ':' + pad(s % 60);
}

/** A person's initials, at most two — how the tab tells people apart, never
 *  by colour: "Sam Rivera" → "SR", "Person 2" → "P2", "Sam" → "S". */
export function initialOf(name) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase() || '?';
}

/** Minutes since midnight of an HH:MM (null when it is not one). */
export function hhmmToMinutes(v) {
  const m = /^(\d{2}):(\d{2})$/.exec(v || '');
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/** …and back: 545 → "09:05", clamped to the day. */
export function minutesToHHMM(n) {
  const v = Math.max(0, Math.min(23 * 60 + 59, Math.round(n)));
  return String(Math.floor(v / 60)).padStart(2, '0') + ':' + String(v % 60).padStart(2, '0');
}
