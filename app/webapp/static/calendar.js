/* task-os — the Today tab's calendar lane (#96): read-only, desktop only.
 *
 * A slim column beside the task list with today's events from the private ICS
 * address in `calendar.ics_url` — so planning the day happens against the free
 * time that actually exists. It renders GET /api/today's `calendar` group and
 * nothing else; every fetch rule (timeout, cached copy, which failure is
 * which) lives in src/calendar_lane.py.
 *
 * The one rule this module owns: an empty lane never implies a free day. The
 * list is drawn as "No events today" only when the group's state is `ok`;
 * every other state — no calendar connected, the address refused, the server
 * unreachable, no answer in time, a feed that is not a calendar — says so in
 * words, and a good copy kept through a failure is shown with the failure and
 * the time it was fetched beside it. Recurring events the server could not
 * expand, and events it could not read, are counted, never hidden.
 *
 * Built for every width and hidden below 1024 px by styles.css: the phone
 * skips the lane this pass (#96, out of scope).
 */

'use strict';

import { emptyStateEl } from './_vendored/empty-state/empty-state.js';
import { icon } from './_vendored/icons/icons.js';

const FAILURE_TITLES = {
  bad_url: 'Calendar address refused',
  unreachable: 'Calendar unreachable',
  timeout: 'Calendar did not answer in time',
  parse_error: 'Calendar feed unreadable',
};

/** `HH:MM` of a server timestamp — its own wall clock, not the browser's. */
function hhmm(iso) {
  return iso && iso.length >= 16 ? iso.slice(11, 16) : '–';
}

function plural(n, one, many) {
  return n + ' ' + (n === 1 ? one : many);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/**
 * @param {object|null} cal  GET /api/today's `calendar` group; null = unknown
 * @returns {HTMLElement}
 */
export function calendarLane(cal) {
  const lane = el('aside', 'cal-lane');
  lane.setAttribute('aria-label', 'Calendar');
  const head = el('div', 'today-head');
  const h = el('h2', 'today-title');
  h.innerHTML = icon('calendar-days');
  h.appendChild(document.createTextNode('Calendar'));
  head.appendChild(h);
  const meta = el('span', 'today-counts cal-counts');
  head.appendChild(meta);
  lane.appendChild(head);

  if (!cal) {
    meta.textContent = 'unknown';
    lane.appendChild(notice('Calendar unknown', 'Today’s data did not load, so neither did the calendar.'));
    return lane;
  }
  lane.dataset.state = cal.state;

  if (!cal.configured || cal.state === 'off') {
    meta.textContent = 'off';
    lane.appendChild(emptyStateEl('calendar-days', 'No calendar connected'));
    const hint = el('p', 'cal-hint');
    hint.append('Set ');
    hint.appendChild(el('code', null, 'calendar.ics_url'));
    hint.append(' in the config to a private ICS address to see today’s events here.');
    lane.appendChild(hint);
    return lane;
  }

  const events = cal.events || [];
  const allDay = cal.all_day || [];
  const failed = cal.state !== 'ok';
  const hasCopy = !failed || cal.stale;

  if (failed) {
    const title = (FAILURE_TITLES[cal.state] || 'Calendar unavailable')
      + (cal.failing_since ? ' since ' + hhmm(cal.failing_since) : '');
    const detail = cal.error || '';
    lane.appendChild(notice(title, detail, cal.stale && cal.fetched_at
      ? 'Showing the copy from ' + hhmm(cal.fetched_at) + '.' : ''));
  } else if (cal.stale && cal.refreshing) {
    lane.appendChild(el('p', 'cal-note', 'Refreshing — showing the copy from ' + hhmm(cal.fetched_at) + '.'));
  }

  if (!hasCopy) {
    meta.textContent = 'unavailable';
    return lane;
  }
  const total = events.length + allDay.length;
  meta.textContent = failed ? 'stale' : (total ? plural(total, 'event', 'events') : 'free');

  if (allDay.length) {
    const strip = el('div', 'cal-allday');
    strip.appendChild(el('span', 'cal-allday-label', 'All day'));
    const ul = el('ul', 'cal-allday-list');
    allDay.forEach(function (ev) { ul.appendChild(el('li', 'cal-chip', ev.summary)); });
    strip.appendChild(ul);
    lane.appendChild(strip);
  }

  if (events.length) {
    const ol = el('ol', 'cal-events');
    events.forEach(function (ev) {
      const li = el('li', 'cal-event');
      li.appendChild(el('span', 'cal-time', (ev.starts_before ? '…' : ev.start) + '–' + ev.end));
      const body = el('span', 'cal-body');
      body.appendChild(el('span', 'cal-summary', ev.summary));
      if (ev.starts_before || ev.ends_after) {
        body.appendChild(el('span', 'cal-span',
          ev.starts_before ? 'started yesterday at ' + ev.start : 'ends tomorrow'));
      }
      li.appendChild(body);
      ol.appendChild(li);
    });
    lane.appendChild(ol);
  } else if (!allDay.length) {
    lane.appendChild(emptyStateEl('circle-check', failed ? 'No events in the last copy' : 'No events today'));
  }

  if (cal.skipped_recurring) {
    lane.appendChild(el('p', 'cal-note is-attention',
      plural(cal.skipped_recurring, 'recurring event', 'recurring events')
      + ' could not be checked — open the calendar itself to be sure.'));
  }
  if (cal.unreadable) {
    lane.appendChild(el('p', 'cal-note is-attention',
      plural(cal.unreadable, 'event', 'events') + ' in the feed could not be read.'));
  }
  return lane;
}

function notice(title, detail, extra) {
  const box = el('div', 'cal-notice');
  box.setAttribute('role', 'status');
  const t = el('p', 'cal-notice-title');
  t.innerHTML = icon('triangle-alert');
  t.appendChild(document.createTextNode(title));
  box.appendChild(t);
  if (detail) box.appendChild(el('p', 'cal-notice-detail', detail));
  if (extra) box.appendChild(el('p', 'cal-notice-detail', extra));
  return box;
}
