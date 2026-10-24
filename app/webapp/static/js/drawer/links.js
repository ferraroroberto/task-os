/* task-os — the drawer's links: the open-only pill row near the top and the
 * link editor under More fields. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { aiChip, chipFor, issueChip } from '../../format.js';
import { toast } from '../../toast.js';
import { formButton, section } from './dom.js';

/** The folder ref as its opener chip. An unresolvable ref keeps its warning
 *  ON the chip: a placeholder this server does not know is a config fault,
 *  not a silent one. */
export function folderChip(t) {
  const chip = chipFor(t.folder_ref, null, { resolved: t.folder_resolved, url: t.folder_url });
  if (t.folder_resolved) {
    chip.title = t.folder_resolved + ' — the path this server resolves the ref to';
  } else {
    chip.classList.add('chip-missing');
    chip.title = t.folder_ref + ' — placeholder not configured on this server; add it to config.placeholders';
    chip.insertAdjacentHTML('beforeend', icon('triangle-alert'));
  }
  return chip;
}

function linkChip(l) {
  // an email link is a .msg ref the opener opens as a file — same chip, mail glyph;
  // an ai link keeps the bot chip + open/resume popover regardless of URL shape
  return l.kind === 'ai'
    ? aiChip(l.url, l.label || null)
    : chipFor(l.url, l.label || null, l.kind === 'email' ? { icon: 'mail' } : undefined);
}

/** Everything the task points at, one row of pills that only open: the
 *  folder, the linked issue, then every link (one home per fact, #390).
 *  Changing any of them is under More fields. */
export function linkPills(t) {
  const sec = section('pills', 'Links', 'link');
  const pills = document.createElement('div');
  pills.className = 'drawer-pill-row folder-chips';
  if (t.folder_ref) pills.appendChild(folderChip(t));
  let issueHref = null;
  if (t.issue_ref) {
    const ic = issueChip(t.issue_ref);
    issueHref = ic.href;
    pills.appendChild(ic);
  }
  (t.links || []).forEach(function (l) {
    // linking an issue also stores it as an `issue` link; the issue chip
    // above already is that link, with its state
    if (l.kind === 'issue' && issueHref && new URL(l.url, location.href).href === issueHref) return;
    pills.appendChild(linkChip(l));
  });
  if (!pills.childElementCount) {
    const none = document.createElement('p');
    none.className = 'muted drawer-none';
    none.textContent = 'No links. Add one under More fields.';
    sec.appendChild(none);
  } else {
    sec.appendChild(pills);
  }
  return sec;
}

/** The inline label editor of one link row. */
function linkLabelEditor(ctx, t, l) {
  const editInput = document.createElement('input');
  editInput.type = 'text';
  editInput.className = 'input-native link-label-edit';
  editInput.value = l.label || '';
  editInput.placeholder = 'label';
  editInput.setAttribute('aria-label', 'Edit label for ' + (l.label || l.url));
  const commit = async function () {
    const v = editInput.value.trim();
    ctx.editingLinkId = null;
    if (v !== (l.label || '')) {
      try {
        await api('/api/tasks/' + t.id + '/links/' + l.id, { method: 'PATCH', body: { label: v || null } });
        await ctx.refresh();
      } catch (err) { toast(err.message, 'error'); ctx.render(); }
    } else {
      ctx.render();
    }
  };
  editInput.addEventListener('keydown', function (ev) {
    // stopPropagation, not just preventDefault: commit() re-renders the drawer
    // synchronously (even on a no-op Escape), which detaches this input before the
    // keydown finishes bubbling — app.js's document-level Escape handler would then
    // see a target it no longer recognizes as "a field owns this key" and close the
    // drawer on top of the cancelled edit.
    if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); editInput.blur(); }
    if (ev.key === 'Escape') { ev.stopPropagation(); editInput.value = l.label || ''; editInput.blur(); }
  });
  editInput.addEventListener('blur', commit);
  requestAnimationFrame(function () { editInput.focus(); editInput.select(); });
  return editInput;
}

/** One link: its chip with the pencil and the trash, or — while its label is
 *  being edited — the label editor alone. */
function linkRow(ctx, t, l) {
  const row = document.createElement('div');
  row.className = 'link-row';
  if (ctx.editingLinkId === l.id) {
    row.appendChild(linkLabelEditor(ctx, t, l));
    return row;
  }
  row.appendChild(linkChip(l));
  const actions = document.createElement('div');
  actions.className = 'link-actions';
  const edit = document.createElement('button');
  edit.type = 'button';
  edit.className = 'icon-button';   // the one icon button (#357): unshaded, 44px via ::before
  edit.setAttribute('aria-label', 'Edit label for ' + (l.label || l.url));
  edit.innerHTML = icon('pencil');
  edit.addEventListener('click', function () { ctx.editingLinkId = l.id; ctx.render(); });
  actions.appendChild(edit);
  const rm = document.createElement('button');
  rm.type = 'button';
  rm.className = 'icon-button danger';
  rm.setAttribute('aria-label', 'Remove link ' + (l.label || l.url));
  rm.innerHTML = icon('trash-2');
  rm.addEventListener('click', async function () {
    try {
      await api('/api/tasks/' + t.id + '/links/' + l.id, { method: 'DELETE' });
      await ctx.refresh();
    } catch (err) { toast(err.message, 'error'); }
  });
  actions.appendChild(rm);
  row.appendChild(actions);
  return row;
}

function linkAddForm(ctx, t) {
  const linkForm = document.createElement('form');
  linkForm.className = 'link-form';
  const url = document.createElement('input');
  url.type = 'text';
  url.className = 'input-native';
  url.placeholder = 'https://…  or  {onedrive}/folder';
  url.setAttribute('aria-label', 'Link URL or folder');
  const label = document.createElement('input');
  label.type = 'text';
  label.className = 'input-native';
  label.placeholder = 'label (optional)';
  label.setAttribute('aria-label', 'Link label');
  linkForm.append(url, label, formButton(linkForm, 'button-surface', 'Add link'));
  linkForm.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const u = url.value.trim();
    if (!u) return;
    try {
      // no kind: the server classifies the URL (one rule, #257)
      await api('/api/tasks/' + t.id + '/links', { method: 'POST', body: { url: u, label: label.value.trim() || null } });
      await ctx.refresh();
    } catch (err) { toast(err.message, 'error'); }
  });
  return linkForm;
}

/** The link editor under More fields: each link with its label edit and
 *  remove, then the add form. The pills at the top only open them. */
export function linksSection(ctx, t) {
  const links = section('links', 'Edit links', 'link');
  const linkList = document.createElement('div');
  linkList.className = 'drawer-links';
  (t.links || []).forEach(function (l) { linkList.appendChild(linkRow(ctx, t, l)); });
  if (!(t.links || []).length) {
    const none = document.createElement('p');
    none.className = 'muted drawer-none';
    none.textContent = 'No links.';
    linkList.appendChild(none);
  }
  links.appendChild(linkList);
  links.appendChild(linkAddForm(ctx, t));
  return links;
}
