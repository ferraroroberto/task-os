/* task-os — History's words: the kind chips and one change in a line. */

'use strict';

import { fmtDay } from '../../format.js';
import { fieldWords } from '../drawer/activity.js';

/** The chips, in the issue's order; `all` is no filter. */
export const KINDS = [
  { key: 'all', label: 'All' },
  { key: 'dates', label: 'Date moved' },
  { key: 'closed', label: 'Closed/reopened' },
  { key: 'status', label: 'Status' },
  { key: 'priority', label: 'Priority' },
  { key: 'moved', label: 'Moved' },
  { key: 'comment', label: 'Comments' },
];

function dateWord(v) { return v ? fmtDay(v) : 'none'; }

function valueWord(v) { return v == null || v === '' ? '∅' : v; }

/** One change in words: "Due 17 Aug → 20 Aug", "Moved Home → the top level", "Comment: …". */
export function changeText(e) {
  switch (e.field) {
    case 'due': return 'Due ' + dateWord(e.old) + ' → ' + dateWord(e.new);
    case 'starts': return 'Start ' + dateWord(e.old) + ' → ' + dateWord(e.new);
    case 'done': return 'Completed, next due ' + dateWord(e.new);
    case 'parent': return 'Moved ' + (e.old_label || 'from the top level') + ' → ' + (e.new_label || 'the top level');
    case 'comment': return 'Comment: ' + (e.new || '');
    case 'created': return 'Created';
    case 'imported': return 'Imported';
    case 'description': return 'Notes edited';
    case 'title': return 'Renamed from ' + valueWord(e.old);
    case 'blocked_by': return e.new ? 'Blocked by ' + (e.new_label || e.new) : 'Unblocked from ' + (e.old_label || e.old);
    case 'blocks': return e.new ? 'Now blocks ' + (e.new_label || e.new) : 'No longer blocks ' + (e.old_label || e.old);
    default: {
      const w = fieldWords(e.field);
      return w.charAt(0).toUpperCase() + w.slice(1) + ' ' + valueWord(e.old) + ' → ' + valueWord(e.new);
    }
  }
}

/** "09:00" from a local ISO timestamp — the clock the change was written in. */
export function timeOf(ts) { return (ts || '').slice(11, 16); }
