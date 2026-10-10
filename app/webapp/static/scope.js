/* task-os — the scope switch: Mine · Issues · All (#391, decision 1 of #390).
 *
 * The vendored segmented control (`_vendored/segmented/`, project-scaffolding
 * #341) over the shared filter state's `scope` key (filters.js `SCOPES`,
 * `matchesScope`). One builder for every list that shows it — Today first;
 * the Board, Search and the journal take the same switch in their own steps.
 * The raised segment is the state, so the switch says which scope is on and
 * nothing above it repeats that in words.
 *
 * Built once per host and updated in place, so a re-render never moves the
 * focus off the segment the user just pressed.
 */

'use strict';

import { SCOPES } from './filters.js';

/**
 * Mount the switch into `host`.
 * @param {HTMLElement} host
 * @param {(scope: string) => void} onChange  the picked scope, only when it changed
 * @returns {{render: (scope: string) => void}}
 */
export function mountScope(host, onChange) {
  const group = document.createElement('div');
  group.className = 'segmented scope-switch';
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Whose tasks');
  SCOPES.forEach(function (s) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'segmented-item';
    b.dataset.scope = s[0];
    b.setAttribute('aria-pressed', 'false');
    b.textContent = s[1];
    group.appendChild(b);
  });
  let current = '';
  group.addEventListener('click', function (ev) {
    const seg = ev.target.closest('.segmented-item');
    if (!seg || seg.dataset.scope === current) return;
    render(seg.dataset.scope);
    onChange(seg.dataset.scope);
  });
  host.replaceChildren(group);

  function render(scope) {
    current = scope;
    group.querySelectorAll('.segmented-item').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.scope === scope));
    });
  }

  return { render: render };
}
