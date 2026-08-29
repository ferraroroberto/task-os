/* task-os — the due-date controls, in one place.
 *
 * Two pieces, because two callers want different amounts of it:
 *
 *   duePicker()  the calendar button + the hidden `<input type="date">` it
 *                opens. The bulk-action bar (#81) uses this alone — one
 *                square button on the strip's line, no text box.
 *   dueInput()   that picker with a text box in front of it, for the natural
 *                phrases (`tomorrow`, `fri`, `in 2 weeks`). The Table's
 *                inline due cell uses this.
 *
 * The reason the picker is its own function is the coarse-pointer branch
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
  // `className` REPLACES the default modifier rather than stacking on it: the
  // Table's cell button is 30px, the strip's is a full square, and letting
  // both classes land on one element makes the two size rules fight.
  button.className = 'icon-btn ' + (o.className || 'due-pick-btn');
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

/**
 * A text box for the natural phrases, with {@link duePicker} beside it.
 * @param {{value?: string, placeholder?: string, ariaLabel?: string,
 *          onCommit: (value: string) => void, onCancel?: () => void}} opts
 *        onCommit fires on Enter in the text box and on picking a date;
 *        onCancel (optional) on Escape.
 * @returns {{row: HTMLElement, input: HTMLInputElement, picker: HTMLInputElement}}
 */
export function dueInput(opts) {
  const o = opts || {};
  const row = document.createElement('span');
  row.className = 'due-input';

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'input-native due-text';
  input.value = o.value || '';
  input.placeholder = o.placeholder || 'tomorrow · fri · in 2 weeks';
  input.setAttribute('aria-label', o.ariaLabel || 'Due date');
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); o.onCommit(input.value.trim()); }
    if (ev.key === 'Escape' && o.onCancel) { ev.preventDefault(); o.onCancel(); }
  });

  const pick = duePicker({ value: o.value, onPick: o.onCommit });
  row.append(input, pick.button, pick.picker);
  return { row: row, input: input, picker: pick.picker };
}
