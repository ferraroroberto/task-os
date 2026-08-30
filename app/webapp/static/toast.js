/* task-os — toasts for user-initiated command results and errors.
 *
 * One live region (#toasts, role="status") owns every toast; errors flip it
 * to assertive for the announcement. Never used for passive/background
 * status (design.md "Async data & feedback") — that renders inline.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

const TTL_MS = 4500;
// A toast carrying an action stays up longer: 4.5 s is enough to *read* a
// result, not enough to notice an Undo, move the pointer and click it. Caught
// on the #87 walk — the snooze toast was gone before it could be used.
const ACTION_TTL_MS = 10000;

/**
 * @param {string} message
 * @param {'info'|'success'|'error'} [kind='info']
 * @param {{label: string, onClick: () => any}} [action]
 *        one optional inline action — the undo a reversible command offers
 *        (snoozing a task, #87). It runs and dismisses the toast; the caller
 *        owns what "undo" means, this only shows the button. Never a second
 *        action, and never the only way to reach an outcome: the toast expires.
 */
export function toast(message, kind, action) {
  const host = document.getElementById('toasts');
  if (!host) return;
  const k = kind || 'info';
  host.setAttribute('aria-live', k === 'error' ? 'assertive' : 'polite');
  const el = document.createElement('div');
  el.className = 'toast toast-' + k;
  el.innerHTML = icon(k === 'error' ? 'triangle-alert' : (k === 'success' ? 'circle-check' : 'activity'));
  const span = document.createElement('span');
  span.textContent = message;
  el.appendChild(span);
  if (action && action.label) {
    const act = document.createElement('button');
    act.type = 'button';
    act.className = 'button-ghost toast-action';
    act.textContent = action.label;
    act.addEventListener('click', function () {
      act.disabled = true;
      Promise.resolve(action.onClick()).finally(function () { el.remove(); });
    });
    el.appendChild(act);
  }
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';   // .toast-close carries the 44px expansion itself
  close.setAttribute('aria-label', 'Dismiss');
  close.innerHTML = icon('x');
  close.addEventListener('click', function () { el.remove(); });
  el.appendChild(close);
  host.appendChild(el);
  window.setTimeout(function () { if (el.isConnected) el.remove(); },
    action && action.label ? ACTION_TTL_MS : TTL_MS);
}
