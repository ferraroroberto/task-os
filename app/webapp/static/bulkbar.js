/* task-os — the bulk-action bar: what you do with a selection (#81).
 *
 * While Select mode is on and at least one task is ticked, this bar TAKES OVER
 * the pane's top strip (the text filter and the quick-add +) rather than
 * stacking a third row above the board: the pane keeps its height, and on the
 * phone nothing lands near the floating bottom-nav pill.
 *
 *   ☑ 3 selected   📅 Move   [Set status…▾]   🗑   ✕
 *
 * One line, and every control the same square height as the strip's own
 * buttons. Two edits, both applying the moment they are given a value — the
 * same commit gesture the single-task controls use (a status applies on
 * change; a date applies on its pick in the date sheet), so nothing here needs a Save
 * the rest of the app doesn't have. `complete` is offered alongside the plain
 * statuses because the selection may hold recurring tasks; the server decides
 * per task what it means (issue #54 semantics, applied in bulk). The third
 * action, delete (#121), is the one that asks first — the caller owns the
 * confirmation and the request; the bar only locks while it runs.
 *
 * Mounted once per pane (Board, Today); every instance reads the one selection
 * store, so both bars always say the same number.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES } from './format.js';
import * as selection from './selection.js';
import { openDatePicker } from './snooze.js';

const STATUS_PLACEHOLDER = '';

/**
 * @param {HTMLElement} host   the `.bulk-bar` container in a pane's top strip
 * @param {{onApply: (changes: {status?: string, due?: string}) => Promise<any>,
 *          onDelete: () => Promise<any>,
 *          onExit: () => void}} handlers
 * @returns {{render: () => void}}
 */
export function mountBulkBar(host, handlers) {
  host.classList.add('bulk-bar');
  host.setAttribute('role', 'toolbar');
  host.setAttribute('aria-label', 'Bulk actions');

  // The number is the one thing that must survive a narrow phone — it is what
  // says how much this next click changes. Only the word "selected" is
  // droppable (CSS), never the count itself.
  const count = document.createElement('span');
  count.className = 'bulk-count';
  count.innerHTML = icon('square-check');
  const countText = document.createElement('span');
  countText.className = 'bulk-n';
  const countWord = document.createElement('span');
  countWord.className = 'bulk-word';
  countWord.textContent = 'selected';
  count.append(countText, countWord);

  const status = document.createElement('select');
  status.className = 'select-native bulk-status';
  status.setAttribute('aria-label', 'Set status of the selected tasks');
  const placeholder = document.createElement('option');
  placeholder.value = STATUS_PLACEHOLDER;
  placeholder.textContent = 'Set status…';
  status.appendChild(placeholder);
  STATUSES.forEach(function (s) {
    // `complete` sits where it sits on a recurring row: right before `done`
    if (s === 'done') {
      const c = document.createElement('option');
      c.value = 'complete';
      c.textContent = 'complete';
      status.appendChild(c);
    }
    const o = document.createElement('option');
    o.value = s;
    o.textContent = s;
    status.appendChild(o);
  });

  // Move (#392) is the bar's first action, as it is the row's: the one date
  // sheet every re-date opens (snooze.js) — the push-out phrases, Pick a date…
  // and No date — so a selection moves the way a single row does.
  const move = document.createElement('button');
  move.type = 'button';
  move.className = 'icon-button bulk-move';
  move.title = 'Move the selected tasks…';
  move.setAttribute('aria-label', 'Move the selected tasks to another date');
  move.setAttribute('aria-haspopup', 'dialog');
  move.innerHTML = icon('calendar-days');
  move.addEventListener('click', function () {
    if (busy) return;
    const n = selection.size();
    const subject = { title: n + ' selected task' + (n === 1 ? '' : 's'), due: null, clearable: true };
    openDatePicker(subject, 'due', host, function (phrase) { apply({ due: phrase }, function () {}); });
  });

  // Delete (#121): the caller confirms and posts; this square only locks the
  // bar while that runs, exactly like an apply.
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'icon-button danger bulk-delete';
  del.title = 'Delete the selected tasks';
  del.setAttribute('aria-label', 'Delete the selected tasks');
  del.innerHTML = icon('trash-2');
  del.addEventListener('click', function () {
    if (busy) return;
    busy = true;
    setDisabled(true);
    Promise.resolve(handlers.onDelete())
      .catch(function () { /* toasted by the caller */ })
      .finally(function () { busy = false; setDisabled(false); });
  });

  const exit = document.createElement('button');
  exit.type = 'button';
  // the one icon button the strip's + wears too (#357), so the bar's three
  // glyphs are one control by construction, not by three rules agreeing
  exit.className = 'icon-button bulk-exit';
  exit.title = 'Leave select mode';
  exit.setAttribute('aria-label', 'Leave select mode');
  exit.innerHTML = icon('x');
  exit.addEventListener('click', function () { handlers.onExit(); });

  status.addEventListener('change', function () {
    const value = status.value;
    if (value === STATUS_PLACEHOLDER) return;
    apply({ status: value }, function () { status.value = STATUS_PLACEHOLDER; });
  });

  let busy = false;
  /** One apply: the controls lock so a second click can't double-post, and the
   *  control resets whether the batch succeeded or not — its value said what
   *  to do once, not what the selection now is. */
  function apply(changes, reset) {
    if (busy) return;
    busy = true;
    setDisabled(true);
    Promise.resolve(handlers.onApply(changes))
      .catch(function () { /* toasted by the caller */ })
      .finally(function () {
        busy = false;
        reset();
        setDisabled(false);
      });
  }

  function setDisabled(on) {
    move.disabled = on;
    status.disabled = on;
    del.disabled = on;
  }

  host.append(count, move, status, del, exit);

  function render() {
    const n = selection.size();
    host.hidden = !(selection.isActive() && n > 0);
    countText.textContent = String(n);
    // the visible text can lose the word on a narrow phone, so the whole
    // phrase lives on the label screen readers and the tests read
    count.setAttribute('aria-label', n + ' selected');
  }

  render();
  return { render: render };
}
