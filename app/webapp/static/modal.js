/* task-os — the two pieces every editor modal repeats.
 *
 * `modalCard` builds the card shell the vendored editor modal draws — a
 * `detail-card`, its `detail-header` with the title and the × — for the dialogs
 * that build their card per ask (confirm.js, snooze.js, keys.js). The ones whose
 * markup is static in index.html (quick-add, the palette) only need
 * `closeOnBackdrop`, which all four dialogs share: a click on the `<dialog>`
 * itself (the backdrop, outside the card) means "close".
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

/**
 * @param {{cardClass: string, title: string, titleId: string, closeLabel: string,
 *          onClose: () => void}} o
 * @returns {{card: HTMLElement, close: HTMLButtonElement}}  the card already holds its header;
 *          append the body after it
 */
export function modalCard(o) {
  const card = document.createElement('div');
  card.className = 'detail-card ' + o.cardClass;
  const head = document.createElement('div');
  head.className = 'detail-header';
  const h = document.createElement('h2');
  h.id = o.titleId;
  h.textContent = o.title;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'icon-button detail-close';
  close.setAttribute('aria-label', o.closeLabel);
  close.innerHTML = icon('x');
  close.addEventListener('click', o.onClose);
  head.append(h, close);
  card.appendChild(head);
  return { card: card, close: close };
}

/**
 * Close on a click on the backdrop. Returns the function that stops listening,
 * for the dialogs that rebuild their content per ask.
 * @param {HTMLDialogElement} dialog
 * @param {() => void} [onClose]   defaults to `dialog.close()`
 * @returns {() => void}
 */
export function closeOnBackdrop(dialog, onClose) {
  const handler = function (ev) {
    if (ev.target === dialog) (onClose || function () { dialog.close(); })();
  };
  dialog.addEventListener('click', handler);
  return function () { dialog.removeEventListener('click', handler); };
}
