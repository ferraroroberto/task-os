/* task-os — the one destructive-action confirmation.
 *
 * `confirmDialog({title, lines, warn, action})` → Promise<boolean>. Built per
 * ask into the `<dialog id="confirmDialog">` shell in index.html — the same
 * vendored editor modal the palette, quick-add and the keys card use (native
 * showModal / close, Esc, the × and a backdrop click all mean "no"; focus
 * goes back to the opener when it closes, as the native dialog does).
 *
 * The one footer action is the destructive one, on the vendored outlined
 * recipe (`button-tint danger`, design.md) — never a fill or a tint, never a
 * competing second action, and the safe answer is every other way out.
 */

'use strict';

import { modalCard, onceClosed } from './modal.js';

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
    const shell = modalCard({
      cardClass: 'confirm-card', title: o.title, titleId: 'confirmTitle', closeLabel: 'Cancel',
      onClose: function () { dialog.close(); },
    });
    const card = shell.card;
    const close = shell.close;

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
    // The modal's one full-width footer action, outlined on danger (the
    // vendored button-tint danger) — never a solid red or a tint.
    go.className = 'button-tint danger detail-save-btn';
    go.textContent = o.action || 'Delete';
    go.addEventListener('click', function () { answer = true; dialog.close(); });
    actions.appendChild(go);
    card.appendChild(actions);

    onceClosed(dialog, function () {
      resolve(answer);
    });
    dialog.replaceChildren(card);
    dialog.showModal();
    // the primary is the only control, but the focus must not land on it —
    // Enter would confirm a delete the reader has not read yet
    close.focus();
  });
}
