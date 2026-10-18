/* task-os — the two view switches under a pane's strip.
 *
 *   scope  Tasks · Issues · All   which kind of task (#391, decision 1 of #390;
 *                                 relabelled in #477 — "Mine" moved to the other axis)
 *   whose  Mine · Everyone        whose tasks (#477, Step 4/4 of #471); only
 *                                 mounted on Today and Board, and only shown
 *                                 with two or more members
 *
 * The vendored segmented control (`_vendored/segmented/`, project-scaffolding
 * #341) over the shared filter state's `scope` and `whose` keys (filters.js
 * `SCOPES`, `WHOSE`). One builder for every list that shows either — the two
 * are separate axes and never fold into one control. The raised segment is the
 * state, so a switch says what is on and nothing above it repeats that in words.
 *
 * Built once per host and updated in place, so a re-render never moves the
 * focus off the segment the user just pressed.
 */

'use strict';

import { SCOPES, WHOSE } from './filters.js';

/** One switch: `key` names the data attribute and the usage-log prefix. */
function mountSwitch(host, spec, onChange) {
  const group = document.createElement('div');
  group.className = 'segmented ' + spec.className;
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', spec.label);
  spec.options.forEach(function (o) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'segmented-item';
    b.dataset[spec.key] = o[0];
    b.dataset.track = spec.key + '.' + o[0];
    b.setAttribute('aria-pressed', 'false');
    b.textContent = o[1];
    group.appendChild(b);
  });
  let current = '';
  group.addEventListener('click', function (ev) {
    const seg = ev.target.closest('.segmented-item');
    if (!seg || seg.dataset[spec.key] === current) return;
    render(seg.dataset[spec.key]);
    onChange(seg.dataset[spec.key]);
  });
  host.replaceChildren(group);

  function render(value) {
    current = value;
    group.querySelectorAll('.segmented-item').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset[spec.key] === value));
    });
  }

  return { render: render };
}

/**
 * Mount the scope switch (Tasks · Issues · All) into `host`.
 * @param {HTMLElement} host
 * @param {(scope: string) => void} onChange  the picked scope, only when it changed
 * @returns {{render: (scope: string) => void}}
 */
export function mountScope(host, onChange) {
  return mountSwitch(host, { key: 'scope', className: 'scope-switch', label: 'Kind of task', options: SCOPES }, onChange);
}

/**
 * Mount the whose switch (Mine · Everyone) into `host`.
 * @param {HTMLElement} host
 * @param {(whose: string) => void} onChange  the picked value, only when it changed
 * @returns {{render: (whose: string) => void}}
 */
export function mountWhose(host, onChange) {
  return mountSwitch(host, { key: 'whose', className: 'whose-switch', label: 'Whose tasks', options: WHOSE }, onChange);
}
