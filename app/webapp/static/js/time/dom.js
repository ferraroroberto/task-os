/* task-os — the Time tab's DOM builders every part shares. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { initialOf } from '../../time-format.js';

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function avatar(name) {
  const a = el('span', 'action-row-avatar time-avatar', initialOf(name));
  a.setAttribute('aria-hidden', 'true');
  return a;
}

/** The small sample of a person's bar fill beside their name: the key to the bars. */
export function swatch(fill) {
  const s = el('span', 'time-fill time-swatch');
  s.dataset.fill = fill;
  s.setAttribute('aria-hidden', 'true');
  return s;
}

export function titleText(title, meta) {
  const t = el('span', 'action-row-text');
  t.appendChild(el('span', 'action-row-title', title));
  if (meta) t.appendChild(el('span', 'action-row-meta', meta));
  return t;
}

export function cardHead(glyph, title, extra) {
  const head = el('div', 'time-card-head');
  const h = el('h2', 'time-card-title');
  h.innerHTML = icon(glyph);
  h.appendChild(document.createTextNode(title));
  head.appendChild(h);
  if (extra) head.appendChild(extra);
  return head;
}

export function segmented(label, items, current, onPick, cls) {
  const seg = el('div', 'segmented' + (cls ? ' ' + cls : ''));
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-label', label);
  items.forEach(function (it) {
    const b = el('button', 'segmented-item', it.label);
    b.type = 'button';
    b.dataset.value = it.value;
    if (it.track) b.dataset.track = it.track;
    b.setAttribute('aria-pressed', String(it.value) === String(current) ? 'true' : 'false');
    b.addEventListener('click', function () { onPick(it.value); });
    seg.appendChild(b);
  });
  return seg;
}
