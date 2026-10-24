/* task-os — Settings → Email archiving: the cells of one mail's row, shared by
 * the grid and the phone card. */

'use strict';

import { fmtTsShort, folderChip, pct } from '../../format.js';
import { shortFolder, shortenPaths } from './text.js';

const STATE_WORDS = {
  archived: 'filed',
  moved: 'moved by you',
  needs_review: 'needs you',
  failed: 'failed',
  reverted: 'reverted',
};
const STATE_TONE = {
  archived: 'ok', moved: 'ok', needs_review: 'warn', failed: 'warn', reverted: 'off',
};
//: The desktop table caps a row's file chips so five real files (and their
//: attachments) cannot force a subject/state row several lines tall (#178).
//: One since #339's J-10: a row reads in two lines, and one chip + "+N more" +
//: the ⋮ is exactly the action-row budget (#350). The phone card keeps
//: showing every file — its own width already wraps each chip to its own
//: line (#173) and a card has room to grow.
const FILES_CAP = 1;
//: The archiver's own naming: `NNN - <name>` or `YYYY-MM-DD - NNN - <name>`
//: ahead of the readable part. Worth keeping in the desktop table (it sorts
//: the folder by date), least useful on a 390px chip (#173) — the full name
//: stays in the chip's `title` either way.
const FILE_NAME_PREFIX = /^(?:\d{4}-\d{2}-\d{2} - )?\d+ - /;

export function stateChip(item) {
  const s = document.createElement('span');
  const reviewed = item.status === 'needs_review' && item.decided_at;
  s.className = 'archive-state status-' + (reviewed ? 'off' : STATE_TONE[item.status] || 'off');
  s.textContent = reviewed ? 'reviewed' : STATE_WORDS[item.status] || item.status;
  if (item.decided_at) s.title = 'reviewed ' + fmtTsShort(item.decided_at);
  return s;
}

export function destinationEl(item) {
  const el = document.createElement('span');
  el.className = 'archive-dest';
  if (!item.chosen_folder) {
    el.classList.add('muted');
    el.textContent = 'still in the Inbox';
    return el;
  }
  el.textContent = shortFolder(item.chosen_folder);
  el.title = item.chosen_folder;
  return el;
}

/** The archived files as opener chips — the same per-PC `taskos://` link
 *  every folder chip in the app carries, so a `.msg` opens in the mail
 *  client on whichever PC is looking. `opts.cap` (the desktop table only)
 *  shows at most `FILES_CAP` and folds the rest behind a *+N more* chip
 *  that expands them in place, one click, no re-render (#178). */
export function filesEl(ctx, item, opts) {
  const cap = (opts || {}).cap;
  const el = document.createElement('span');
  el.className = 'archive-files folder-chips';
  if (!item.files.length) {
    el.classList.add('muted');
    el.textContent = item.attachments ? '– (' + item.attachments + ' attachment(s))' : '–';
    return el;
  }
  function chipFor(path) {
    const name = String(path).split(/[\\/]+/).pop();
    const label = ctx.narrow() ? name.replace(FILE_NAME_PREFIX, '') : name;
    return folderChip(path, { label: label, icon: /\.msg$/i.test(name) ? 'mail' : 'file-text' });
  }
  const shown = cap ? item.files.slice(0, FILES_CAP) : item.files;
  const rest = cap ? item.files.slice(FILES_CAP) : [];
  shown.forEach(function (path) { el.appendChild(chipFor(path)); });
  if (rest.length) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'chip archive-files-more';
    more.textContent = '+' + rest.length + ' more';
    more.title = rest.length + ' more file(s)';
    more.addEventListener('click', function (ev) {
      ev.stopPropagation();          // a plain expand, not a row-level action
      rest.forEach(function (path) { el.insertBefore(chipFor(path), more); });
      more.remove();
    });
    el.appendChild(more);
  }
  return el;
}

export function confidenceEl(item) {
  const el = document.createElement('span');
  if (item.confidence == null) {
    el.className = 'muted';
    el.textContent = '–';
    return el;
  }
  el.className = 'archive-confidence';
  el.textContent = pct(item.confidence);
  // rank 0 = the model landed on the archiver's own top candidate
  el.title = item.chosen_rank === 0
    ? 'the model picked the archiver’s own top candidate'
    : item.chosen_rank == null ? 'no ranked pick' : 'the model picked candidate #' + (item.chosen_rank + 1);
  return el;
}

export function reasonEl(ctx, item) {
  const el = document.createElement('span');
  el.className = 'archive-reason';
  const text = item.error ? (item.reason ? item.reason + ' · ' + item.error : item.error)
    : (item.reason || '');
  // The full sentence is always the title — the fold is what is on screen.
  el.textContent = (ctx.narrow() ? shortenPaths(text) : text) || '–';
  el.title = text;
  if (item.error) el.classList.add('archive-reason-error');
  return el;
}

export function subjectEl(item) {
  const s = document.createElement('span');
  s.className = 'archive-subject';
  s.textContent = item.subject || '(no subject)';
  s.title = (item.subject || '(no subject)') + ' · ' + item.message_id;
  return s;
}

/** The grid's first cell: the subject, then one muted line of who · when
 *  — the phone card's first two lines, in one cell. */
export function subjectCellEl(item) {
  const box = document.createElement('div');
  box.className = 'archive-subject-cell';
  const who = document.createElement('span');
  who.className = 'archive-who muted';
  who.textContent = (item.sender || '–') + ' · ' + (item.sent_at ? fmtTsShort(item.sent_at) : '–');
  who.title = who.textContent;
  box.append(subjectEl(item), who);
  return box;
}
