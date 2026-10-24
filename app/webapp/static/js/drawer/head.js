/* task-os — the drawer's head: breadcrumb, parent tools, close, and the
 * editable title row. */

'use strict';

import { icon } from '../../_vendored/icons/icons.js';
import { openParentPicker } from '../../parentpick.js';

/** The breadcrumb trail, one button per ancestor, or "top level". */
function breadcrumbs(ctx, t) {
  const crumbs = document.createElement('nav');
  crumbs.className = 'drawer-crumbs';
  crumbs.setAttribute('aria-label', 'Breadcrumb');
  (t.breadcrumb || []).forEach(function (c, i) {
    if (i) {
      const sep = document.createElement('span');
      sep.className = 'crumb-sep';
      sep.textContent = '›';
      crumbs.appendChild(sep);
    }
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'crumb';
    b.textContent = c.title;
    b.addEventListener('click', function () { ctx.opts.onOpen(c.id); });
    crumbs.appendChild(b);
  });
  if (!(t.breadcrumb || []).length) {
    const top = document.createElement('span');
    top.className = 'crumb crumb-root';
    top.textContent = 'top level';
    crumbs.appendChild(top);
  }
  return crumbs;
}

/** Parent tools (#468): the breadcrumb is where the owner looks for the
 *  parent, so they sit on its line (#486) and wrap under it when it is long. */
function parentTools(ctx, t) {
  const opts = ctx.opts;
  const tools = document.createElement('div');
  tools.className = 'drawer-parent-tools';
  const change = document.createElement('button');
  change.type = 'button';
  change.className = 'button-ghost drawer-change-parent';
  change.setAttribute('aria-label', 'Change parent of ' + t.title);
  change.innerHTML = icon('corner-down-right') + '<span>Change parent</span>';
  change.addEventListener('click', function () {
    openParentPicker(t, opts.parentTargets ? opts.parentTargets(t.id) : [], function (parentId) {
      opts.onMove(t.id, parentId);   // toasts + refreshes; a cycle comes back as a toast
    });
  });
  tools.appendChild(change);
  if (t.parent_id != null) {
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'button-ghost drawer-remove-parent';
    remove.setAttribute('aria-label', 'Remove parent of ' + t.title);
    remove.innerHTML = icon('x') + '<span>Remove parent</span>';
    remove.addEventListener('click', function () { opts.onMove(t.id, null); });
    tools.appendChild(remove);
  }
  return tools;
}

export function renderHead(ctx, t) {
  const head = document.createElement('div');
  head.className = 'drawer-head';
  const crumbs = breadcrumbs(ctx, t);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'icon-button detail-close drawer-close';
  close.setAttribute('aria-label', 'Close');
  close.innerHTML = icon('x');
  close.addEventListener('click', function () { ctx.opts.onClose(); });
  const trail = document.createElement('div');
  trail.className = 'drawer-trail';
  trail.append(crumbs, parentTools(ctx, t));
  head.append(trail, close);
  return head;
}

export function renderTitleRow(ctx, t) {
  const titleRow = document.createElement('div');
  titleRow.className = 'drawer-title-row';
  const code = document.createElement('span');
  code.className = 'drawer-code';
  code.textContent = t.code || ('#' + t.id);
  // A textarea, not an input: a long title wraps to 2–3 lines instead of
  // clipping off-screen on the phone (#32). Enter still commits (below),
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
  titleRow.append(code, title);
  if (t.is_project) {
    const chip = document.createElement('span');
    chip.className = 'chip chip-project';
    chip.textContent = 'project';
    titleRow.appendChild(chip);
  }
  return titleRow;
}
