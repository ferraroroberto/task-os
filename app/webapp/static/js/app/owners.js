/* task-os — the person row under a pane's strip.
 *
 *   [Mine] [Person] [Person] … [+N more] [Everyone]
 *
 * Whose tasks a Today or Board list shows, as the vendored segmented control
 * (`_vendored/segmented/`) the scope switch beside it also is: Mine first, the
 * other members between, Everyone last, the raised segment the state. A tap
 * picks that one person. At most five segments fit, so an install with more
 * members keeps the picked and the recently picked ones in the row and puts the
 * rest behind "+N more", a sheet with a name filter where several people can be
 * ticked; "+N more" is the raised segment while the pick is several people. The
 * state is the shared filter's (`owners` + `whose`, filters.js); this file only
 * draws it and reports taps.
 *
 * Built once per host and updated in place: the row only rebuilds when the set
 * of segments changes, and the focus stays on the segment the user just pressed.
 */

'use strict';

import { modalCard, onceClosed } from '../../modal.js';
import { pickedOwners, visibleOwners } from '../../filters.js';

const MORE = 'more';
const EVERYONE = 'everyone';

/** One segment; the full name rides on `title` for a label the segment clips. */
function segment(kind, id, label, track) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'segmented-item';
  b.dataset.owner = id;
  b.dataset.kind = kind;
  // dynamic-id-exempt: track is one of four fixed ids (owners.mine, .person, .more, .everyone), never a member id
  b.dataset.track = track;
  b.setAttribute('aria-pressed', 'false');
  b.title = label;
  const text = document.createElement('span');
  text.className = 'segmented-label';
  text.textContent = label;
  b.appendChild(text);
  return b;
}

/**
 * Mount the person row into `host`.
 * @param {HTMLElement} host
 * @param {{onPick: (id: string) => void, onEveryone: () => void,
 *          onOpenMore: () => void}} on
 * @returns {{render: (f: object, ctx: {members: Array, viewer: string|null, recent: string[]}) => void,
 *            ordered: () => Array}}
 */
export function mountOwners(host, on) {
  const group = document.createElement('div');
  group.className = 'segmented owner-switch';
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Whose tasks');
  group.dataset.surface = 'strip.person-row';
  host.replaceChildren(group);
  let drawnKey = '';
  let ordered = [];

  group.addEventListener('click', function (ev) {
    const b = ev.target.closest('.segmented-item');
    if (!b) return;
    if (b.dataset.kind === MORE) on.onOpenMore();
    else if (b.dataset.kind === EVERYONE) on.onEveryone();
    else if (b.getAttribute('aria-pressed') !== 'true') on.onPick(b.dataset.owner);
  });

  function rebuild(shown, more, viewer, key) {
    const focused = document.activeElement && group.contains(document.activeElement)
      ? document.activeElement.dataset.owner : null;
    const segments = [];
    if (viewer) segments.push(segment('person', viewer, 'Mine', 'owners.mine'));
    shown.forEach(function (m) { segments.push(segment('person', m.id, m.name, 'owners.person')); });
    if (more) segments.push(segment(MORE, MORE, '+' + more + ' more', 'owners.more'));
    segments.push(segment(EVERYONE, EVERYONE, 'Everyone', 'owners.everyone'));
    group.replaceChildren.apply(group, segments);
    drawnKey = key;
    if (focused) {
      const again = group.querySelector('.segmented-item[data-owner="' + CSS.escape(focused) + '"]');
      if (again) again.focus();
    }
  }

  function render(f, ctx) {
    const picked = pickedOwners(f, ctx.viewer);
    const vis = visibleOwners(ctx.members, ctx.viewer, picked, ctx.recent);
    ordered = vis.ordered;
    const key = [ctx.viewer, vis.more].concat(vis.shown.map(function (m) { return m.id + ':' + m.name; })).join('|');
    if (key !== drawnKey) rebuild(vis.shown, vis.more, ctx.viewer, key);
    const everyone = f.whose === 'everyone' && !picked.length;
    const several = picked.length > 1;
    group.querySelectorAll('.segmented-item').forEach(function (b) {
      const on_ = b.dataset.kind === EVERYONE ? everyone
        : b.dataset.kind === MORE ? several : !several && picked.indexOf(b.dataset.owner) >= 0;
      b.setAttribute('aria-pressed', String(on_));
    });
  }

  return { render: render, ordered: function () { return ordered; } };
}

/**
 * The "+N more" sheet: every member besides the viewer, the picked and the
 * recently picked first, a name filter above and one tick per person. A tick
 * applies at once (like the filter sheet); Done closes.
 * @param {{people: Array<{id: string, name: string}>, picked: () => string[],
 *          onToggle: (id: string) => void}} o
 */
export function openOwnerSheet(o) {
  const dialog = document.getElementById('ownerDialog');
  if (!dialog) return;
  const shell = modalCard({
    cardClass: 'parent-card owner-card', title: 'People', titleId: 'ownerDialogTitle',
    closeLabel: 'Close people', onClose: function () { dialog.close(); },
  });
  const card = shell.card;

  const filter = document.createElement('input');
  filter.type = 'search';
  filter.className = 'parent-filter owner-filter';
  filter.placeholder = 'Filter ' + o.people.length + ' people';
  filter.setAttribute('aria-label', 'Filter people');
  filter.autocomplete = 'off';

  const list = document.createElement('div');
  list.className = 'filter-checks owner-list';
  list.setAttribute('role', 'group');
  list.setAttribute('aria-label', 'People');
  const empty = document.createElement('p');
  empty.className = 'parent-empty muted';
  empty.textContent = 'No one matches';
  empty.hidden = true;

  const rows = o.people.map(function (p) {
    const label = document.createElement('label');
    label.className = 'filter-check';
    label.dataset.value = p.id;
    const cb = document.createElement('input');
    cb.dataset.track = 'owners.option';
    cb.type = 'checkbox';
    cb.className = 'check';
    cb.value = p.id;
    cb.checked = o.picked().indexOf(p.id) >= 0;
    cb.addEventListener('change', function () {
      o.onToggle(p.id);
      const now = o.picked();
      rows.forEach(function (r) { r.cb.checked = now.indexOf(r.id) >= 0; });
    });
    label.append(cb, document.createTextNode(p.name));
    list.appendChild(label);
    return { id: p.id, el: label, cb: cb, hay: p.name.toLowerCase() };
  });

  filter.addEventListener('input', function () {
    const words = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    rows.forEach(function (r) {
      const hit = words.every(function (w) { return r.hay.indexOf(w) !== -1; });
      r.el.hidden = !hit;
      if (hit) shown += 1;
    });
    empty.hidden = shown !== 0;
  });

  const actions = document.createElement('div');
  actions.className = 'filter-actions';
  const done = document.createElement('button');
  done.dataset.track = 'owners.done';
  done.type = 'button';
  done.className = 'button-primary filter-done';
  done.textContent = 'Done';
  done.addEventListener('click', function () { dialog.close(); });
  actions.appendChild(done);

  card.append(filter, list, empty, actions);
  onceClosed(dialog, function () {});
  dialog.replaceChildren(card);
  dialog.showModal();
  // a keyboard that opens over a phone's list hides what it filters
  if (window.matchMedia('(pointer: fine)').matches) filter.focus();
}
