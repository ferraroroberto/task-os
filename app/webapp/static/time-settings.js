/* task-os — the Time tab's two Settings rows and their sheets (#457).
 *
 *   This device → Time tracking as   who this device logs time for (a
 *                                    label, never a credential); with one
 *                                    person configured it simply names them
 *   Tools → Time categories          areas and their categories: add,
 *                                    rename (a category's subtitle too,
 *                                    #463), reorder, move a category to
 *                                    another area, archive / unarchive;
 *                                    delete only a category nothing points
 *                                    at (`in_use` false, #463), so every
 *                                    past entry keeps its category and its
 *                                    totals
 *
 * The rows and sheet bodies are markup in index.html (the Settings pattern,
 * #397); this fills them. Every write goes to `/api/time/{areas,categories}`
 * and then `onMetaChanged()` re-reads the meta the Time tab draws from.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { createRowMenu } from './_vendored/row-menu/row-menu.js';
import { api } from './api.js';
import { confirmDialog } from './confirm.js';
import { pickOption, promptCategory, promptText } from './time-dialogs.js';
import { initialOf } from './time-format.js';
import { toast } from './toast.js';

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/**
 * @param {{meta: () => (object|null), person: () => (string|null),
 *          onPerson: (id: string) => void, onMetaChanged: () => Promise<any>}} opts
 * @returns {{render: () => void, openSheet: (key: string) => void}}
 */
export function mountTimeSettings(opts) {
  const els = {
    personValue: document.getElementById('timePersonValue'),
    personList: document.getElementById('timePersonList'),
    catsValue: document.getElementById('timeCatsValue'),
    catsHost: document.getElementById('timeCatsHost'),
  };
  const menu = createRowMenu({ className: 'time-admin-menu' });

  /** The two rows' values. */
  function render() {
    const meta = opts.meta();
    if (!meta) return;
    const me = meta.people.find(function (p) { return p.id === opts.person(); });
    els.personValue.textContent = me ? me.name : 'Not picked';
    const areas = meta.areas.filter(function (a) { return !a.archived; });
    const cats = areas.reduce(function (n, a) {
      return n + a.categories.filter(function (c) { return !c.archived; }).length;
    }, 0);
    els.catsValue.textContent = areas.length + (areas.length === 1 ? ' area · ' : ' areas · ') + cats
      + (cats === 1 ? ' category' : ' categories');
    if (!els.personList.closest('[hidden]')) renderPeople();
    if (!els.catsHost.closest('[hidden]')) renderCategories();
  }

  function openSheet(key) {
    if (key === 'timeperson') renderPeople();
    if (key === 'timecats') renderCategories();
  }

  // ------------------------------------------------------------ people
  function renderPeople() {
    const meta = opts.meta();
    if (!meta) return;
    const ul = el('ul', 'action-rows');
    meta.people.forEach(function (p) {
      const li = el('li', 'action-row');
      const btn = el('button', 'action-row-main');
      btn.type = 'button';
      btn.dataset.track = 'time-person';
      const chosen = p.id === opts.person();
      if (chosen) btn.setAttribute('aria-current', 'true');
      const av = el('span', 'action-row-avatar time-avatar', initialOf(p.name));
      av.setAttribute('aria-hidden', 'true');
      const text = el('span', 'action-row-text');
      text.appendChild(el('span', 'action-row-title', p.name));
      btn.append(av, text);
      if (chosen) {
        const check = el('span', 'time-check');
        check.innerHTML = icon('check');
        check.setAttribute('aria-label', 'This device');
        btn.appendChild(check);
      }
      btn.addEventListener('click', function () {
        if (chosen) return;
        opts.onPerson(p.id);
        toast('This device now logs time for ' + p.name);
      });
      li.appendChild(btn);
      ul.appendChild(li);
    });
    const card = el('section', 'card action-list');
    card.appendChild(ul);
    els.personList.replaceChildren(card);
  }

  // -------------------------------------------------------- categories
  async function write(path, method, body, done) {
    try {
      await api(path, { method: method, body: body });
      await opts.onMetaChanged();
      if (done) toast(done);
    } catch (err) {
      toast(err.message, 'error');
    }
    renderCategories();
  }

  function renameArea(a) {
    promptText({ title: 'Rename area', label: 'Name', value: a.name }).then(function (name) {
      if (name) write('/api/time/areas/' + a.id, 'PATCH', { name: name }, 'Renamed');
    });
  }

  /** Name and subtitle; only what changed is sent, and an emptied subtitle clears it. */
  function editCategory(c) {
    promptCategory({ title: 'Edit category', name: c.name, hint: c.hint }).then(function (v) {
      if (!v) return;
      const body = {};
      if (v.name !== c.name) body.name = v.name;
      if (v.hint !== (c.hint || '')) body.hint = v.hint;
      write('/api/time/categories/' + c.id, 'PATCH', body, 'Saved ' + v.name);
    });
  }

  /** Delete a category no entry or timer points at; the server refuses (409
   *  `category_in_use`) if one landed since the meta was read. */
  async function deleteCategory(a, c) {
    const ok = await confirmDialog({
      title: 'Delete ' + c.name + '?',
      lines: ['It has no entries, so no totals change. It leaves ' + a.name + ' for good.'],
      action: 'Delete category',
    });
    if (ok) write('/api/time/categories/' + c.id, 'DELETE', undefined, 'Deleted ' + c.name);
  }

  function areaItems(a, index, count) {
    return [
      { label: 'Rename', glyph: 'pencil', onTap: function () { renameArea(a); } },
      { label: 'Add category', glyph: 'plus', onTap: function () {
        promptCategory({ title: 'Add a category to ' + a.name, action: 'Add' }).then(function (v) {
          if (v) write('/api/time/categories', 'POST', { area_id: a.id, name: v.name, hint: v.hint }, 'Added ' + v.name);
        });
      } },
      { label: 'Move up', glyph: 'arrow-up', hidden: index === 0, onTap: function () {
        write('/api/time/areas/' + a.id, 'PATCH', { position: index - 1 });
      } },
      { label: 'Move down', glyph: 'arrow-down', hidden: index === count - 1, onTap: function () {
        write('/api/time/areas/' + a.id, 'PATCH', { position: index + 1 });
      } },
      { label: a.archived ? 'Unarchive' : 'Archive', glyph: 'archive', onTap: function () {
        write('/api/time/areas/' + a.id, 'PATCH', { archived: !a.archived }, a.archived ? 'Unarchived ' + a.name : 'Archived ' + a.name);
      } },
    ];
  }

  function categoryItems(meta, a, c, index, count) {
    return [
      { label: 'Edit', glyph: 'pencil', onTap: function () { editCategory(c); } },
      { label: 'Move up', glyph: 'arrow-up', hidden: index === 0, onTap: function () {
        write('/api/time/categories/' + c.id, 'PATCH', { position: index - 1 });
      } },
      { label: 'Move down', glyph: 'arrow-down', hidden: index === count - 1, onTap: function () {
        write('/api/time/categories/' + c.id, 'PATCH', { position: index + 1 });
      } },
      { label: 'Move to another area', glyph: 'arrow-right', hidden: meta.areas.length < 2, onTap: function () {
        pickOption({
          title: 'Move ' + c.name, label: 'Area', value: a.id,
          options: meta.areas.map(function (x) { return { value: x.id, label: x.name }; }),
        }).then(function (target) {
          if (target) write('/api/time/categories/' + c.id, 'PATCH', { area_id: Number(target) }, 'Moved ' + c.name);
        });
      } },
      { label: c.archived ? 'Unarchive' : 'Archive', glyph: 'archive', onTap: function () {
        write('/api/time/categories/' + c.id, 'PATCH', { archived: !c.archived }, c.archived ? 'Unarchived ' + c.name : 'Archived ' + c.name);
      } },
      { label: 'Delete', glyph: 'trash-2', danger: true, hidden: c.in_use, onTap: function () { deleteCategory(a, c); } },
    ];
  }

  function kebab(label) {
    const b = el('button', 'icon-button action-row-kebab');
    b.type = 'button';
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-haspopup', 'menu');
    b.setAttribute('aria-expanded', 'false');
    b.innerHTML = icon('ellipsis-vertical');
    return b;
  }

  function archivedChip() {
    const chip = el('span', 'chip time-chip', 'Archived');
    chip.dataset.tone = 'neutral';
    return chip;
  }

  function renderCategories() {
    const meta = opts.meta();
    if (!meta) return;
    const parts = [el('p', 'card-meta', 'Areas hold the categories you start timers on. Archived ones leave the start list and the pickers but keep their past entries and totals. A category with no entries can be deleted.')];
    meta.areas.forEach(function (a, ai) {
      const card = el('section', 'card action-list time-admin-area');
      const head = el('div', 'action-row time-admin-head');
      const main = el('div', 'action-row-main');
      const text = el('span', 'action-row-text');
      const title = el('span', 'action-row-title', a.name);
      text.appendChild(title);
      main.appendChild(text);
      if (a.archived) main.appendChild(archivedChip());
      const k = kebab('Area actions: ' + a.name);
      menu.attach('area-' + a.id, k, areaItems(a, ai, meta.areas.length));
      head.append(main, k);
      const ul = el('ul', 'action-rows');
      a.categories.forEach(function (c, ci) {
        const li = el('li', 'action-row');
        const m = el('div', 'action-row-main');
        const t = el('span', 'action-row-text');
        t.appendChild(el('span', 'action-row-title', c.name));
        if (c.hint) t.appendChild(el('span', 'action-row-meta', c.hint));
        m.appendChild(t);
        if (c.archived) m.appendChild(archivedChip());
        const ck = kebab('Category actions: ' + c.name);
        menu.attach('cat-' + c.id, ck, categoryItems(meta, a, c, ci, a.categories.length));
        li.append(m, ck);
        ul.appendChild(li);
      });
      card.append(head, ul);
      parts.push(card);
    });
    const add = el('button', 'button-surface time-admin-add');
    add.type = 'button';
    add.dataset.track = 'time-area-add';
    add.innerHTML = icon('plus');
    add.appendChild(document.createTextNode('Add area'));
    add.addEventListener('click', function () {
      promptText({ title: 'Add an area', label: 'Name', action: 'Add' }).then(function (name) {
        if (name) write('/api/time/areas', 'POST', { name: name }, 'Added ' + name);
      });
    });
    parts.push(add);
    els.catsHost.replaceChildren.apply(els.catsHost, parts);
    menu.endRender();
  }

  return { render: render, openSheet: openSheet };
}
