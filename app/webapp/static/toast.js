/* task-os — toasts for user-initiated command results and errors.
 *
 * One live region (#toasts, role="status") owns every toast; errors flip it
 * to assertive for the announcement. Never used for passive/background
 * status (design.md "Async data & feedback") — that renders inline.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

const TTL_MS = 4500;

/**
 * @param {string} message
 * @param {'info'|'success'|'error'} [kind='info']
 */
export function toast(message, kind) {
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
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';   // .toast-close carries the 44px expansion itself
  close.setAttribute('aria-label', 'Dismiss');
  close.innerHTML = icon('x');
  close.addEventListener('click', function () { el.remove(); });
  el.appendChild(close);
  host.appendChild(el);
  window.setTimeout(function () { if (el.isConnected) el.remove(); }, TTL_MS);
}
