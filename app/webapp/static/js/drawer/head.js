/* task-os — the drawer's head: the breadcrumb (which is the parent control),
 * the Inbox tag, the task menu, close, and the editable title. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { createRowMenu } from '../../_vendored/row-menu/row-menu.js';
import { deleteCurrent } from './foot.js';
import { pickParent } from './props.js';

// One menu for the head's ⋯: only one drawer is ever open.
const taskMenu = createRowMenu({ className: 'drawer-task-menu' });

/** The breadcrumb as one button: where the task lives is where the owner
 *  looks to move it, so a tap on the trail opens the parent picker. Each
 *  ancestor stays its own span, so the trail still reads as the path. */
function breadcrumbs(ctx, t) {
  const crumbs = document.createElement('button');
  crumbs.type = 'button';
  crumbs.dataset.track = 'drawer.parent-change';
  crumbs.className = 'drawer-crumbs drawer-change-parent';
  crumbs.setAttribute('aria-label', 'Change parent of ' + t.title);
  crumbs.title = 'Change parent';
  crumbs.insertAdjacentHTML('beforeend', icon('corner-down-right'));
  const trail = document.createElement('span');
  trail.className = 'crumb-trail';
  (t.breadcrumb || []).forEach(function (c, i) {
    if (i) {
      const sep = document.createElement('span');
      sep.className = 'crumb-sep';
      sep.textContent = '›';
      trail.appendChild(sep);
    }
    const s = document.createElement('span');
    s.className = 'crumb';
    s.textContent = c.title;
    trail.appendChild(s);
  });
  if (!(t.breadcrumb || []).length) {
    const top = document.createElement('span');
    top.className = 'crumb crumb-root';
    top.textContent = 'Top level';
    trail.appendChild(top);
  }
  crumbs.appendChild(trail);
  crumbs.insertAdjacentHTML('beforeend', icon('chevron-down'));
  crumbs.addEventListener('click', function () { pickParent(ctx, t); });
  return crumbs;
}

/** The ⋯ menu: what the drawer does to the task as a whole. Its header names
 *  the task's code, which no longer takes a line of its own. */
function taskMenuButton(ctx, t) {
  const more = document.createElement('button');
  more.dataset.track = 'drawer.task-more';
  more.type = 'button';
  more.className = 'icon-button drawer-task-more';
  more.setAttribute('aria-label', 'Task actions');
  more.innerHTML = icon('ellipsis');
  const parent = (t.breadcrumb || []).slice(-1)[0];
  const closed = t.status === 'done' || t.status === 'cancelled';
  taskMenu.attach('task-' + t.id, more, [
    { label: parent ? 'Open ' + parent.title : 'Open parent', glyph: 'corner-down-right',
      hidden: !parent, dataset: { action: 'open-parent', track: 'drawer.crumb' },
      onTap: function () { if (parent) ctx.opts.onOpen(parent.id); } },
    // Done rolls a recurring task to its next date; this closes it for good.
    { label: 'Done, end the series', glyph: 'circle-check',
      hidden: !t.recurrence || closed, dataset: { action: 'end-series', track: 'drawer.end-series' },
      onTap: function () { ctx.setStatus('done', { endSeries: true }); } },
    { label: 'Delete task', glyph: 'trash-2', danger: true,
      dataset: { action: 'delete', track: 'drawer.delete' },
      onTap: function () { deleteCurrent(ctx, t); } },
  ], { header: t.code || ('#' + t.id) });
  taskMenu.endRender();
  return more;
}

export function renderHead(ctx, t) {
  const head = document.createElement('div');
  head.className = 'drawer-head';
  head.appendChild(breadcrumbs(ctx, t));
  // Inbox is not a segment (it is where a task waits to be filed, not a
  // state to pick), so an Inbox task says so here, with no segment raised.
  if (t.status === 'inbox') {
    const tag = document.createElement('span');
    tag.className = 'chip drawer-inbox-tag';
    tag.textContent = 'Inbox';
    head.appendChild(tag);
  }
  const close = document.createElement('button');
  close.dataset.track = 'drawer.close';
  close.type = 'button';
  close.className = 'icon-button detail-close drawer-close';
  close.setAttribute('aria-label', 'Close');
  close.innerHTML = icon('x');
  close.addEventListener('click', function () { ctx.opts.onClose(); });
  head.append(taskMenuButton(ctx, t), close);
  return head;
}

export function renderTitleRow(ctx, t) {
  const titleRow = document.createElement('div');
  titleRow.className = 'drawer-title-row';
  // A textarea, not an input: a long title wraps to 2–3 lines instead of
  // clipping off-screen on the phone. Enter still commits (below),
  // never a newline; the height follows the content.
  const title = document.createElement('textarea');
  title.rows = 1;
  title.id = 'drawerTitle';
  title.className = 'drawer-title';
  title.value = t.title;
  title.setAttribute('aria-label', 'Title');
  const fitTitle = function () {
    title.style.height = 'auto';
    title.style.height = title.scrollHeight + 'px';
  };
  title.addEventListener('input', fitTitle);
  requestAnimationFrame(fitTitle);
  title.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); title.blur(); }
    if (ev.key === 'Escape') { title.value = t.title; title.blur(); }
  });
  title.addEventListener('blur', function () {
    const v = title.value.trim();
    if (v && v !== t.title) ctx.patch({ title: v });
    else title.value = t.title;
  });
  titleRow.appendChild(title);
  if (t.is_project) {
    const chip = document.createElement('span');
    chip.className = 'chip chip-project';
    chip.textContent = 'project';
    titleRow.appendChild(chip);
  }
  return titleRow;
}
