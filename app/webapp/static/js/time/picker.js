/* task-os — the Time tab's "who is tracking time?" card, for a sign-in that is no member. */

'use strict';

import { avatar, el, titleText } from './dom.js';

export function renderPicker(ctx) {
  const card = el('section', 'card action-list time-picker-card');
  const head = el('div', 'time-card-head');
  head.append(el('h2', 'time-card-title', 'Who is tracking time?'));
  const note = el('p', 'muted time-card-note', 'This sign-in is not one of the members, so say who this is for. Only a label for this visit.');
  const list = el('ul', 'action-rows');
  ctx.st.meta.people.forEach(function (p) {
    const li = el('li', 'action-row');
    const btn = el('button', 'action-row-main');
    btn.type = 'button';
    btn.dataset.track = 'time-pick-person';
    btn.append(avatar(p.name), titleText(p.name));
    btn.addEventListener('click', function () {
      ctx.st.person = p.id;
      ctx.rerender();
    });
    li.appendChild(btn);
    list.appendChild(li);
  });
  card.append(head, note, list);
  ctx.els.picker.replaceChildren(card);
}
