/* task-os — the ONE filter state every tab shares, and its sheet (#46, #48, #395).
 *
 * Board, Today, Search and the journal are renderings of the same list, so
 * they read one filter state — this module owns its shape, its URL encoding
 * (`?status=todo&project=12&person=3,5&sort=updated` is the same shareable
 * view on every tab) and the controls that edit it:
 *
 *   <input class="filter-q">          the live text filter, always visible in
 *                                     the pane's own top strip (#80); the
 *                                     list's count is its placeholder (#393)
 *   <button class="filter-open">      beside it: the filter glyph and how many
 *                                     settings are on (#395)
 *   <dialog id="filterSheet">         what the button opens — the vendored
 *                                     editor modal: sort first, then status ·
 *                                     project · person · due · modified;
 *                                     status and person are ticks in place
 *
 * Nothing about the state needs the sheet open to read: the count is on the
 * button, and the button's name says what is on in words. The text input is
 * built once, so a re-render never moves the caret.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES, todayISO } from './format.js';
import { closeOnBackdrop, modalCard } from './modal.js';
import { CLOSED, SORTS, sortLabel } from './rows.js';

export const DEFAULT_FILTERS = { status: [], project: '', person: [], due: '', updated: '', q: '', sort: 'due', scope: 'mine' };
/**
 * Whose tasks a list shows (#391, decision 1 of #390): the owner's own, the
 * issues the forge sync brings in, or both. A task is an issue when it carries
 * an `issue_ref` — the coding task the sync made (`coding` ⇔ issue_ref). One
 * URL key, `scope`, absent for the default Mine. It is not a sheet control:
 * the segmented switch under the strip owns it (scope.js), so the sheet
 * neither counts it nor resets it on Clear.
 */
export const SCOPES = [['mine', 'Mine'], ['issues', 'Issues'], ['all', 'All']];
/**
 * The status multi-select's pseudo-value (#87). Not a status: it flips the
 * list from the awake tasks to the sleeping ones (a `starts` date still in the
 * future), intersected with any real statuses ticked alongside it. The server
 * splits it back out in `app/webapp/routers/tasks.py`; `matchesFilters` below
 * applies the same rule to rows that never went through /api/tasks.
 */
export const DEFERRED = 'deferred';
/**
 * The status multi-select's second pseudo-value (#100). Same shape as
 * `DEFERRED`: not a status, narrows the list to tasks with an open blocker,
 * intersected with any real statuses ticked alongside it. The server splits
 * it back out in `app/webapp/routers/tasks.py`; `matchesFilters` below
 * applies the same rule to rows that never went through /api/tasks.
 */
export const BLOCKED = 'blocked';
export const DUE_WINDOWS = [['', 'Any due date'], ['today', 'Due today'], ['week', 'Due this week'], ['overdue', 'Overdue']];
// The `stale*` windows are the inverse (#101): untouched for MORE than N days.
// The boundary date is computed client-side — the API only ever sees a plain
// `updated_before=YYYY-MM-DD`, no relative magic server-side.
export const UPDATED_WINDOWS = [['', 'Modified any time'], ['today', 'Modified today'], ['week', 'Modified in 7 days'], ['month', 'Modified in 30 days'], ['stale30', 'Untouched > 30 days'], ['stale60', 'Untouched > 60 days'], ['stale90', 'Untouched > 90 days']];
const TEXT_DEBOUNCE_MS = 250;

function csv(value) {
  return (value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
}

// ------------------------------------------------------------ URL state
export function filtersFromSearch(search) {
  const p = new URLSearchParams(search || '');
  const f = Object.assign({}, DEFAULT_FILTERS);
  f.status = csv(p.get('status')).filter(function (s) { return STATUSES.indexOf(s) >= 0 || s === DEFERRED || s === BLOCKED; });
  f.project = p.get('project') || '';
  f.person = csv(p.get('person')).filter(function (s) { return /^\d+$/.test(s); });
  f.due = DUE_WINDOWS.some(function (w) { return w[0] === p.get('due'); }) ? p.get('due') : '';
  f.updated = UPDATED_WINDOWS.some(function (w) { return w[0] === p.get('updated'); }) ? p.get('updated') : '';
  f.q = p.get('q') || '';
  f.sort = SORTS.some(function (s) { return s[0] === p.get('sort'); }) ? p.get('sort') : 'due';
  f.scope = SCOPES.some(function (s) { return s[0] === p.get('scope'); }) ? p.get('scope') : 'mine';
  return f;
}

export function filtersToSearch(f) {
  const p = new URLSearchParams();
  if (f.status.length) p.set('status', f.status.join(','));
  if (f.project) p.set('project', f.project);
  if (f.person.length) p.set('person', f.person.join(','));
  if (f.due) p.set('due', f.due);
  if (f.updated) p.set('updated', f.updated);
  if (f.q) p.set('q', f.q);
  if (f.sort && f.sort !== 'due') p.set('sort', f.sort);
  if (f.scope && f.scope !== 'mine') p.set('scope', f.scope);
  const s = p.toString();
  return s ? '?' + s : '';
}

/** Is `t` in `scope`? — the one rule every list that shows the switch reads. */
export function matchesScope(t, scope) {
  if (scope === 'issues') return !!(t && t.issue_ref);
  if (scope === 'all') return true;
  return !(t && t.issue_ref);
}

// ------------------------------------------------------- server params
/** `updated` window → the ISO date the list API's `updated_since` takes. */
export function updatedSince(window, now) {
  if (!window || window.indexOf('stale') === 0) return '';
  const d = now ? new Date(now) : new Date();
  const days = window === 'today' ? 0 : (window === 'week' ? 7 : 30);
  d.setDate(d.getDate() - days);
  return todayISO(d);
}

/** `stale*` window → the ISO boundary `updated_before` takes: untouched > N
 * days = last touched strictly before today − N (a task touched exactly N
 * days ago is not YET stale). */
export function updatedBefore(window, now) {
  if (!window || window.indexOf('stale') !== 0) return '';
  const d = now ? new Date(now) : new Date();
  d.setDate(d.getDate() - Number(window.slice(5)));
  return todayISO(d);
}

/** The /api/tasks query for a filter state (undefined = not sent; arrays join with commas). */
export function listParams(f) {
  return {
    status: f.status.length ? f.status : undefined,
    project: f.project || undefined,
    person: f.person.length ? f.person : undefined,
    due: f.due || undefined,
    q: f.q || undefined,
    updated_since: updatedSince(f.updated) || undefined,
    updated_before: updatedBefore(f.updated) || undefined,
  };
}

// -------------------------------------------------- client-side predicate
/**
 * The same filter applied in the browser — for rows that did not come through
 * /api/tasks (the Search tab's hits). Text (`q`) is not applied here: the
 * search box owns the text on that tab.
 * @param {object} t  a task summary (status, root, breadcrumb, person_id, due, updated_at)
 * @param {object} f  the filter state
 * @param {string} [today]  ISO date (tests)
 */
export function matchesFilters(t, f, today) {
  // Deferral is a modifier, not a status, so it is resolved before the status
  // branch and intersects with whatever real statuses are ticked. Note the
  // asymmetry with the server's default (#87): ticking `deferred` narrows to
  // the sleeping tasks here too, but NOT ticking it hides nothing — the only
  // caller is the Search tab, and a deferred task is meant to stay findable.
  if (f.status.indexOf(DEFERRED) >= 0 && !(t.starts && t.starts > (today || todayISO()))) return false;
  // Same shape as deferred (#100): ticking `blocked` narrows to tasks with an
  // open blocker; not ticking it hides nothing (a blocked task stays findable
  // wherever this predicate runs — the Search tab).
  if (f.status.indexOf(BLOCKED) >= 0 && !t.blocked) return false;
  const statuses = f.status.filter(function (s) { return s !== DEFERRED && s !== BLOCKED; });
  if (statuses.length) { if (statuses.indexOf(t.status) < 0) return false; }
  else if (CLOSED[t.status]) return false;
  if (f.project) {
    const pid = String(f.project);
    const inCrumb = (t.breadcrumb || []).some(function (c) { return String(c.id) === pid; });
    if (!inCrumb && !(t.root && String(t.root.id) === pid)) return false;
  }
  if (f.person.length) {
    const who = t.person_id != null ? t.person_id : (t.person ? t.person.id : null);
    if (f.person.indexOf(String(who)) < 0) return false;
  }
  if (f.due) {
    const tIso = today || todayISO();
    if (!t.due) return false;
    if (f.due === 'today' && t.due !== tIso) return false;
    if (f.due === 'overdue' && !(t.due < tIso)) return false;
    if (f.due === 'week') {
      const end = new Date(tIso + 'T00:00:00');
      end.setDate(end.getDate() + 7);
      if (t.due < tIso || t.due > todayISO(end)) return false;
    }
  }
  if (f.updated) {
    const ref = today ? today + 'T00:00:00' : undefined;
    const day = t.updated_at ? String(t.updated_at).slice(0, 10) : '';
    const before = updatedBefore(f.updated, ref);
    if (before) { if (!day || day >= before) return false; }
    else if (!day || day < updatedSince(f.updated, ref)) return false;
  }
  return true;
}

// ------------------------------------------------------------ summary
/** What is active, in words — the filter button's accessible name and title,
 * so the line the old card's summary carried is still one hover or one
 * screen-reader stop away (#395). The text is not in it: it is in the field
 * beside the button. A hidden control's value is not applied, so not described. */
export function describeFilters(f, options) {
  const o = options || {};
  const hidden = new Set(o.hide || []);
  const bits = [];
  if (f.status.length && !hidden.has('status')) bits.push(f.status.join(', '));
  if (f.project && !hidden.has('project')) {
    const p = (o.projects || []).find(function (x) { return String(x.id) === String(f.project); });
    bits.push(p ? p.title : 'project #' + f.project);
  }
  if (f.person.length && !hidden.has('person')) {
    bits.push(f.person.map(function (id) {
      const p = (o.people || []).find(function (x) { return String(x.id) === String(id); });
      return p ? p.name : 'person #' + id;
    }).join(', '));
  }
  if (f.due && !hidden.has('due')) bits.push((DUE_WINDOWS.find(function (w) { return w[0] === f.due; }) || [])[1].toLowerCase());
  if (f.updated && !hidden.has('updated')) bits.push((UPDATED_WINDOWS.find(function (w) { return w[0] === f.updated; }) || [])[1].toLowerCase());
  if (f.sort && f.sort !== 'due' && !hidden.has('sort')) bits.push('sorted by ' + sortLabel(f.sort));
  return bits;
}

/** How many settings the sheet's Clear would reset — the number on the filter
 *  button (#395). Neither the text (the field beside the button shows it) nor
 *  the scope (the switch's) counts; a non-default sort does, since Clear
 *  resets it too. A hidden control's value is not applied, so not counted. */
export function activeFilterCount(f, hide) {
  const hidden = new Set(hide || []);
  let n = 0;
  if (f.status.length && !hidden.has('status')) n += 1;
  if (f.project && !hidden.has('project')) n += 1;
  if (f.person.length && !hidden.has('person')) n += 1;
  if (f.due && !hidden.has('due')) n += 1;
  if (f.updated && !hidden.has('updated')) n += 1;
  if (f.sort && f.sort !== 'due' && !hidden.has('sort')) n += 1;
  return n;
}

/** Do two states draw the same sheet? (the text and the scope are not on it) */
function sameControls(a, b) {
  const strip = { q: '', scope: 'mine' };
  return filtersToSearch(Object.assign({}, a, strip)) === filtersToSearch(Object.assign({}, b, strip));
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ---------------------------------------------------------------- controls
function selectEl(name, label, values, current, onChange) {
  const sel = document.createElement('select');
  sel.className = 'select-native filter-select';
  sel.name = name;
  sel.setAttribute('aria-label', label);
  values.forEach(function (v) {
    const o = document.createElement('option');
    o.value = String(v[0]);
    o.textContent = v[1];
    if (String(v[0]) === String(current)) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener('change', function () { onChange(sel.value); });
  return sel;
}

/**
 * Several-allowed choices as ticks in place (#395): the sheet has the room the
 * old card's popover checklist lacked, so status and person are a group of
 * checkboxes, one tap each.
 * @param {string} name
 * @param {string} labelId   the id of the row label that names the group
 * @param {Array<[string,string]>} values   [value, label]
 * @param {Array<string>} selected
 * @param {(next: Array<string>) => void} onChange
 */
function checkGroup(name, labelId, values, selected, onChange) {
  const group = document.createElement('div');
  group.className = 'filter-checks';
  group.dataset.name = name;
  group.setAttribute('role', 'group');
  group.setAttribute('aria-labelledby', labelId);
  values.forEach(function (v) {
    const opt = document.createElement('label');
    opt.className = 'filter-check';
    opt.dataset.value = String(v[0]);
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'check';
    cb.name = name;
    cb.value = String(v[0]);
    cb.checked = selected.indexOf(String(v[0])) >= 0;
    cb.addEventListener('change', function () {
      const ticked = [];
      group.querySelectorAll('input:checked').forEach(function (el) { ticked.push(el.value); });
      onChange(ticked);
    });
    opt.append(cb, document.createTextNode(v[1]));
    group.appendChild(opt);
  });
  return group;
}

// ---------------------------------------------------------------- sheet
const SHEET_ID = 'filterSheet';
let sheetOwner = null;   // the mountFilters handle whose controls the one sheet shows

/**
 * Mount one tab's filter controls; call `render(filters, options)` on every
 * state change. One instance per tab, all reading the same state (#46, #48).
 *
 * The strip (#395): the text field and, beside it, the filter button carrying
 * the active-filter count; the button opens the sheet — the vendored editor
 * modal (`#filterSheet`, static in index.html like the date sheet) with sort
 * first, then status · project · person · due · modified, applied as they
 * change. The tabs share the one `<dialog>`; whichever instance opened it
 * draws its controls.
 * @param {{onChange: (f: object) => void, textHost?: HTMLElement, buttonHost?: HTMLElement,
 *          hide?: string[], countLabel?: string}} opts
 *          textHost — where the always-visible text input goes (the pane's top
 *          strip, #80). Omitted on the Search tab: its own box owns the text,
 *          so there is no second text field and Clear leaves the query alone.
 *          buttonHost — where the filter button goes; defaults to `textHost`
 *          (Search passes its own box).
 *          countLabel — the word before "tasks" in the text field's
 *          placeholder, which carries the list's count ("Filter 12 closed
 *          tasks…", #393)
 *          hide — control names this tab leaves out (`status` · `due` ·
 *          `updated` · `sort` · `project` · `person`); the journal (#102)
 *          drops the four that say nothing about a closed task. A hidden
 *          control's value is neither drawn, counted nor described.
 * @returns {{render: (filters: object, options: {projects: Array, people: Array, count?: number}) => void,
 *            openSheet: () => void}}
 */
export function mountFilters(opts) {
  const hidden = new Set(opts.hide || []);
  let textTimer = 0;
  let textEl = null;         // the strip's input — built once, never re-rendered
  let button = null;         // the filter button — built once, updated in place
  let badge = null;
  let current = DEFAULT_FILTERS;   // the state last rendered
  let options = {};
  let drawn = null;          // the state the open sheet's controls show; null while closed
  let sheetClear = null;     // the open sheet's Clear button
  const handle = { render: render, openSheet: openSheet };

  /** The live text filter, in the pane's top strip (#80). */
  function renderText(filters) {
    if (!opts.textHost) return;
    if (!textEl) {
      textEl = document.createElement('input');
      textEl.type = 'search';
      textEl.className = 'input-native filter-q';
      textEl.setAttribute('aria-label', 'Filter text');
      textEl.addEventListener('input', function () {
        window.clearTimeout(textTimer);
        const value = textEl.value.trim();
        textTimer = window.setTimeout(function () { opts.onChange(Object.assign({}, current, { q: value })); }, TEXT_DEBOUNCE_MS);
      });
      opts.textHost.replaceChildren(textEl);
    }
    opts.textHost.hidden = false;
    // Never yank the value out from under the typist: their keystrokes are
    // already in the box and the debounce means `filters.q` trails them.
    if (document.activeElement !== textEl && textEl.value !== filters.q) textEl.value = filters.q;
    // The count's one home is the text field's placeholder (#393).
    textEl.placeholder = options.count == null ? 'Filter text…'
      : 'Filter ' + options.count + ' ' + (opts.countLabel ? opts.countLabel + ' ' : '') + (options.count === 1 ? 'task' : 'tasks') + '…';
  }

  /** The filter button: the glyph, plus how many settings are on. */
  function renderButton(filters) {
    const host = opts.buttonHost || opts.textHost;
    if (!host) return;
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'icon-button filter-open';
      button.setAttribute('aria-haspopup', 'dialog');
      button.innerHTML = icon('list-filter');
      badge = document.createElement('span');
      badge.className = 'filter-count';
      button.appendChild(badge);
      button.addEventListener('click', openSheet);
      host.appendChild(button);
    }
    const n = activeFilterCount(filters, opts.hide);
    badge.textContent = n ? String(n) : '';
    badge.hidden = !n;
    button.classList.toggle('has-value', n > 0);
    const words = describeFilters(filters, { projects: options.projects, people: options.people, hide: opts.hide });
    const name = n ? 'Filters, ' + n + ' on: ' + words.join(' · ') : 'Filters';
    button.setAttribute('aria-label', name);
    button.title = name;
  }

  function render(filters, o) {
    current = filters;
    options = o || {};
    renderText(filters);
    renderButton(filters);
    // A change from outside the sheet (the palette's filter commands) redraws
    // an open sheet; one the sheet itself made already shows, so it is left
    // alone and the control the user is on keeps the focus.
    const dialog = document.getElementById(SHEET_ID);
    if (sheetOwner === handle && dialog && dialog.open && drawn && !sameControls(filters, drawn)) {
      const hadFocus = dialog.contains(document.activeElement);
      drawn = filters;
      drawSheet(dialog);
      if (hadFocus) focusClose(dialog);
    }
  }

  function focusClose(dialog) {
    const c = dialog.querySelector('.detail-close');
    if (c) c.focus();
  }

  /** Commit one sheet change: built on what the sheet shows, so two quick
   *  changes never lose the first to a render still on its way. The controls
   *  already show it; only Clear follows. */
  function commit(patch) {
    drawn = Object.assign({}, drawn || current, patch);
    if (sheetClear) sheetClear.hidden = !activeFilterCount(drawn, opts.hide);
    opts.onChange(drawn);
  }

  function row(name, label, control) {
    const r = document.createElement('div');
    r.className = 'row filter-sheet-row';
    r.dataset.name = name;
    const l = document.createElement('span');
    l.id = 'filterSheet-' + name;
    l.textContent = label;
    r.append(l, control);
    return r;
  }

  function drawSheet(dialog) {
    const f = drawn || current;
    drawn = f;
    const card = modalCard({
      cardClass: 'filter-card', title: 'Filters', titleId: 'filterSheetTitle',
      closeLabel: 'Close filters', onClose: function () { dialog.close(); },
    }).card;
    function set(name) { return function (value) { const p = {}; p[name] = value; commit(p); }; }
    // 1. sort first (#395): it orders every list, filtered or not
    if (!hidden.has('sort')) {
      card.appendChild(row('sort', 'Sort', selectEl('sort', 'Sort', SORTS.map(function (s) { return [s[0], cap(s[1])]; }), f.sort, set('sort'))));
    }
    // 2. status — `deferred` and `blocked` ride the end: the one visible way
    //    to see the sleeping (#87) and the locked (#100) tasks the working views
    //    leave out. None ticked = the open tasks.
    if (!hidden.has('status')) {
      const statusValues = STATUSES.concat([DEFERRED, BLOCKED]).map(function (s) { return [s, cap(s)]; });
      const r = row('status', 'Status', checkGroup('status', 'filterSheet-status', statusValues, f.status, set('status')));
      r.classList.add('is-stacked');
      card.appendChild(r);
    }
    // 3. project · person
    if (!hidden.has('project')) {
      const projectValues = [['', 'All projects']].concat((options.projects || []).map(function (p) {
        return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
      }));
      card.appendChild(row('project', 'Project', selectEl('project', 'Project', projectValues, f.project, set('project'))));
    }
    const people = options.people || [];
    if (!hidden.has('person') && (people.length || f.person.length)) {
      const r = row('person', 'Person', checkGroup('person', 'filterSheet-person',
        people.map(function (p) { return [String(p.id), p.name]; }), f.person, set('person')));
      r.classList.add('is-stacked');
      card.appendChild(r);
    }
    // 4. due · modified
    if (!hidden.has('due')) card.appendChild(row('due', 'Due', selectEl('due', 'Due window', DUE_WINDOWS, f.due, set('due'))));
    if (!hidden.has('updated')) card.appendChild(row('updated', 'Modified', selectEl('updated', 'Modified window', UPDATED_WINDOWS, f.updated, set('updated'))));

    // Applied as they change, so the footer's one primary only closes; Clear
    // sits beside it while there is something to clear.
    const actions = document.createElement('div');
    actions.className = 'detail-actions filter-actions';
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'button-ghost filter-clear';
    clear.textContent = 'Clear';
    clear.hidden = !activeFilterCount(f, opts.hide);
    clear.addEventListener('click', function () {
      const base = drawn || f;
      drawn = Object.assign({}, DEFAULT_FILTERS, { q: opts.textHost ? '' : base.q, scope: base.scope });
      opts.onChange(drawn);
      drawSheet(dialog);
      focusClose(dialog);
    });
    sheetClear = clear;
    actions.appendChild(clear);
    const done = document.createElement('button');
    done.type = 'button';
    done.className = 'button-primary filter-done';
    done.textContent = 'Done';
    done.addEventListener('click', function () { dialog.close(); });
    actions.appendChild(done);
    card.appendChild(actions);
    dialog.replaceChildren(card);
  }

  function openSheet() {
    const dialog = document.getElementById(SHEET_ID);
    if (!dialog) return;
    if (dialog.open) dialog.close();
    sheetOwner = handle;
    drawn = null;
    const offBackdrop = closeOnBackdrop(dialog);
    dialog.addEventListener('close', function onClose() {
      dialog.removeEventListener('close', onClose);
      offBackdrop();
      dialog.replaceChildren();
      drawn = null;
      sheetClear = null;
      if (sheetOwner === handle) sheetOwner = null;
    });
    drawSheet(dialog);
    dialog.showModal();
  }

  return handle;
}
