/* task-os — the bulk-action bar: what you do with a selection (#81).
 *
 * While Select mode is on and at least one task is ticked, this bar TAKES OVER
 * the pane's top strip (the text filter and the quick-add +) rather than
 * stacking a third row above the board: the pane keeps its height, and on the
 * phone nothing lands near the floating bottom-nav pill.
 *
 *   ☑ 3 selected   [Set status…▾]   📅   ✕
 *
 * One line, and every control the same square height as the strip's own
 * buttons. Two actions, both applying the moment they are given a value — the
 * same commit gesture the single-task controls use (the row's status select
 * applies on change; a picked date on change), so nothing here needs a Save
 * the rest of the app doesn't have. `complete` is offered alongside the plain
 * statuses because the selection may hold recurring tasks; the server decides
 * per task what it means (issue #54 semantics, applied in bulk).
 *
 * Mounted once per pane (Board, Table); every instance reads the one selection
 * store, so both bars always say the same number.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { duePicker } from './dueinput.js';
import { STATUSES } from './format.js';
import * as selection from './selection.js';

const STATUS_PLACEHOLDER = '';

/**
 * @param {HTMLElement} host   the `.bulk-bar` container in a pane's top strip
 * @param {{onApply: (changes: {status?: string, due?: string}) => Promise<any>,
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

  // Date = the native picker alone: the bar is one line on the strip, and a
  // phrase box beside a status select would be the widest thing on it. The
  // API still takes the natural phrases — the Table's inline cell, the drawer
  // and the CLI are where you type them.
  const due = duePicker({
    className: 'button-surface strip-square bulk-due',
    title: 'Set the due date of the selected tasks',
    ariaLabel: 'Set the due date of the selected tasks',
    onPick: function (value) { apply({ due: value }, function () { due.picker.value = ''; }); },
  });

  const exit = document.createElement('button');
  exit.type = 'button';
  // the same class stack the strip's + and Select toggle wear, so all four
  // squares are one control by construction, not by two rules agreeing
  exit.className = 'button-surface strip-square bulk-exit';
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
    status.disabled = on;
    due.button.disabled = on;
  }

  host.append(count, status, due.button, due.picker, exit);

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
