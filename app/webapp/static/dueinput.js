/* task-os — the due-date picker, in one place.
 *
 * `duePicker()` is the calendar button + the hidden `<input type="date">` it
 * opens. Four callers wear it: the bulk-action bar's strip square (#81), the
 * snooze menu's "Pick a date…" (#87), the Table's due cell and the task row's
 * due chip (#107) — the last two because clicking a date should open a
 * calendar, not a text box you then type into. Typing a phrase (`tomorrow`,
 * `fri`, `in 2 weeks`) is still how the drawer and quick-add take a date;
 * `src/dates.py` owns that vocabulary server-side either way.
 *
 * The reason the picker is a shared function is the coarse-pointer branch
 * (#50): touch/WebKit reports `showPicker()` as a callable function and
 * calling it throws nothing — it just opens nothing — so the exception-based
 * fallback never runs there. Coarse pointers therefore skip straight to the
 * fallback (reveal the native date input and click it), which does open the
 * picker. Copy that logic per call site and one of the copies will drift.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

/**
 * The calendar button + the hidden date input it opens.
 * @param {{value?: string, ariaLabel?: string, title?: string, className?: string,
 *          onPick: (iso: string) => void}} opts
 * @returns {{button: HTMLButtonElement, picker: HTMLInputElement, nodes: Array<HTMLElement>}}
 */
export function duePicker(opts) {
  const o = opts || {};
  const button = document.createElement('button');
  button.type = 'button';
  // `className` is the WHOLE class list, not a modifier stacked on a default:
  // the Table's cell button is a 30px `.icon-btn`, the strip's is a 36/44px
  // `.button-surface .strip-square`, and letting both stacks land on one
  // element just makes their size rules fight (34px vs 36px, silently).
  button.className = o.className || 'icon-btn due-pick-btn';
  button.title = o.title || 'Pick a date';
  button.setAttribute('aria-label', o.ariaLabel || 'Pick a due date');
  button.innerHTML = icon('calendar-days');

  const picker = document.createElement('input');
  picker.type = 'date';
  picker.className = 'due-date';
  picker.tabIndex = -1;
  picker.setAttribute('aria-hidden', 'true');
  picker.value = o.value || '';

  button.addEventListener('click', function (ev) {
    ev.preventDefault();
    const coarse = window.matchMedia('(pointer: coarse)').matches;
    if (!coarse) {
      try { if (typeof picker.showPicker === 'function') { picker.showPicker(); return; } } catch (_) { /* fall through */ }
    }
    picker.classList.add('is-visible');
    picker.focus();
    picker.click();
  });
  picker.addEventListener('change', function () { o.onPick(picker.value); });

  return { button: button, picker: picker, nodes: [button, picker] };
}
