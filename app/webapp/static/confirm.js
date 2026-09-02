/* task-os — the one destructive-action confirmation (#121).
 *
 * `confirmDialog({title, lines, warn, action})` → Promise<boolean>. Built per
 * ask into the `<dialog id="confirmDialog">` shell in index.html — the same
 * vendored editor modal the palette, quick-add and the keys card use (native
 * showModal / close, Esc, the × and a backdrop click all mean "no"; focus
 * goes back to the opener when it closes, as the native dialog does).
 *
 * The single primary is the destructive action, restating the tint recipe
 * on `danger` per the design system — never a competing second primary, and
 * the safe answer is every other way out.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';

/**
 * @param {{title: string, lines?: Array<string|null|undefined>, warn?: string|null,
 *          action?: string}} o   `lines` are the plain sentences, `warn` the one
 *          line that changes the answer (rendered in the danger tone)
 * @returns {Promise<boolean>}  true only when the primary was pressed
 */
export function confirmDialog(o) {
  const dialog = document.getElementById('confirmDialog');
  if (!dialog) return Promise.resolve(false);
  return new Promise(function (resolve) {
    let answer = false;
    const card = document.createElement('div');
    card.className = 'detail-card confirm-card';

    const head = document.createElement('div');
    head.className = 'detail-header';
    const h = document.createElement('h2');
    h.id = 'confirmTitle';
    h.textContent = o.title;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'detail-close';
    close.setAttribute('aria-label', 'Cancel');
    close.innerHTML = icon('x');
    close.addEventListener('click', function () { dialog.close(); });
    head.append(h, close);
    card.appendChild(head);

    const body = document.createElement('div');
    body.className = 'confirm-body';
    (o.lines || []).forEach(function (line) {
      if (!line) return;
      const p = document.createElement('p');
      p.textContent = line;
      body.appendChild(p);
    });
    if (o.warn) {
      const p = document.createElement('p');
      p.className = 'confirm-warn';
      p.textContent = o.warn;
      body.appendChild(p);
    }
    card.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'detail-actions';
    const go = document.createElement('button');
    go.type = 'button';
    go.className = 'detail-save-btn confirm-danger';
    go.textContent = o.action || 'Delete';
    go.addEventListener('click', function () { answer = true; dialog.close(); });
    actions.appendChild(go);
    card.appendChild(actions);

    function onBackdrop(ev) { if (ev.target === dialog) dialog.close(); }
    dialog.addEventListener('click', onBackdrop);
    dialog.addEventListener('close', function onClose() {
      dialog.removeEventListener('close', onClose);
      dialog.removeEventListener('click', onBackdrop);
      dialog.replaceChildren();
      resolve(answer);
    });
    dialog.replaceChildren(card);
    dialog.showModal();
    // the primary is the only control, but the focus must not land on it —
    // Enter would confirm a delete the reader has not read yet
    close.focus();
  });
}
