/* task-os — the recurrence vocabulary: cadences, fixed-day anchors, intervals.
 *
 * A hand-kept mirror of src/dates.py (normalise_anchor · describe_recurrence);
 * the server is the authority, this is the picker's and the chips' copy of the
 * same words. Its own module, importing nothing, so
 * tests/test_recurrence_label_parity.py can load it under node and hold
 * recurrenceLabel to describe_recurrence for every cadence ± anchor ± interval.
 */

'use strict';

export const RECURRENCES = ['', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'];

/* Fixed-day anchors (#112) — the cadences that take one, and the options each
 * offers. */
const WEEKDAY_ABBR = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const WEEKDAY_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const WEEKDAYS_ANCHOR = 'mon,tue,wed,thu,fri';
const ORDINAL_WORDS = { 1: 'first', 2: 'second', 3: 'third', 4: 'fourth', last: 'last' };

/* Intervals (#229) — the unit "every N" counts, per cadence. */
const INTERVAL_UNITS = {
  daily: 'days', weekly: 'weeks', monthly: 'months', quarterly: 'quarters', yearly: 'years',
};

/** The anchor picker's option groups for a cadence — `[]` when it takes none.
 *
 * `[{label, options: [[value, text], …]}]`; the first group is unlabelled and
 * holds the "no anchor" choice, so the picker always offers a way back to the
 * plain offset roll. The 66 monthly values are grouped rather than flat: a
 * native select is a scrollable list on the phone, and "Day of month" /
 * "Weekday" split it into two readable halves.
 */
export function anchorOptions(recurrence) {
  if (recurrence === 'weekly') {
    return [
      { options: [['', 'any day (offset from the due date)']] },
      {
        label: 'Every',
        options: [[WEEKDAYS_ANCHOR, 'weekday (Mon–Fri)']].concat(
          WEEKDAY_ABBR.map(function (abbr, i) { return [abbr, WEEKDAY_FULL[i]]; })
        ),
      },
    ];
  }
  if (recurrence === 'monthly') {
    const days = [];
    for (let d = 1; d <= 31; d++) days.push(['day-' + d, 'the ' + ordinal(d)]);
    const nths = [];
    ['1', '2', '3', '4', 'last'].forEach(function (n) {
      WEEKDAY_ABBR.forEach(function (abbr, i) {
        nths.push([n + '-' + abbr, 'the ' + ORDINAL_WORDS[n] + ' ' + WEEKDAY_FULL[i]]);
      });
    });
    return [
      { options: [['', 'same day each month']] },
      { label: 'Day of month', options: days },
      { label: 'Weekday', options: nths },
    ];
  }
  return [];
}

/** The unit an interval counts for a cadence — 'weeks' — or '' for none. */
export function intervalUnit(recurrence) {
  return INTERVAL_UNITS[recurrence] || '';
}

function ordinal(n) {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th'
    : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th';
  return n + suffix;
}

function weekdayWords(anchor, weekdaysWord) {
  if (anchor === WEEKDAYS_ANCHOR) return weekdaysWord;
  const names = String(anchor).split(',').map(function (d) {
    return WEEKDAY_FULL[WEEKDAY_ABBR.indexOf(d)] || d;
  });
  return names.length > 1
    ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]
    : names[0];
}

/** '15th' · 'first Sunday' · 'last Friday' — null for an anchor outside the grammar. */
function monthlyWords(anchor) {
  const day = /^day-(\d{1,2})$/.exec(anchor);
  if (day) return ordinal(Number(day[1]));
  const nth = /^(1|2|3|4|last)-([a-z]+)$/.exec(anchor);
  if (nth) return ORDINAL_WORDS[nth[1]] + ' ' + (WEEKDAY_FULL[WEEKDAY_ABBR.indexOf(nth[2])] || nth[2]);
  return null;
}

/** The label for a cadence + anchor + interval — 'every Friday',
 *  'monthly on the 15th', 'weekly', 'every 7 weeks on Saturday'. */
export function recurrenceLabel(recurrence, anchor, interval) {
  if (!recurrence) return '';
  const every = Number(interval) > 1 ? Number(interval) : null;
  const unit = INTERVAL_UNITS[recurrence];
  if (!anchor) return every && unit ? 'every ' + every + ' ' + unit : recurrence;
  if (recurrence === 'weekly') {
    return every
      ? 'every ' + every + ' weeks on ' + weekdayWords(anchor, 'weekdays')
      : 'every ' + weekdayWords(anchor, 'weekday');
  }
  const words = recurrence === 'monthly' ? monthlyWords(anchor) : null;
  if (!words) return recurrence;
  return (every ? 'every ' + every + ' months' : 'monthly') + ' on the ' + words;
}
