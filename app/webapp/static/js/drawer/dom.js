/* task-os — the drawer's two DOM builders every part shares. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';

export function section(name, title, iconName) {
  const s = document.createElement('section');
  s.className = 'drawer-section drawer-' + name;
  const h = document.createElement('h3');
  h.className = 'drawer-section-title';
  h.innerHTML = icon(iconName);
  const t = document.createElement('span');
  t.textContent = title;
  h.appendChild(t);
  s.appendChild(h);
  return s;
}

/** A sub-form's labelled button: Add link, Set folder, Add blocker, Add
 *  child, Create issue, Link, Send. Each is a utility at the control height
 *  (`button-surface` / `button-ghost`), never the view's primary action, so
 *  none is a submit button — the design measure reads every
 *  `button[type=submit]` as the primary and holds it to button-primary's
 *  48px. The click and Enter in any of the form's inputs both submit
 *  the form, so its one submit handler stays the one write path; a disabled
 *  button stops Enter as it stopped the native submit. */
export function formButton(form, className, html) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = className;
  b.innerHTML = html;
  b.addEventListener('click', function () { form.requestSubmit(); });
  form.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' || ev.target.tagName !== 'INPUT') return;
    ev.preventDefault();
    if (!b.disabled) form.requestSubmit();
  });
  return b;
}
