/* task-os — the ONE filter card every tab shares (issue #46, #48).
 *
 * Board, Table, Tree, Today and Search are renderings of the same list, so
 * they read one filter state — this module owns its shape, its URL encoding
 * (`?status=doing&project=12&person=3,5&sort=updated` is the same shareable
 * view on every tab) and the card that edits it:
 *
 *   <details class="card card--collapsible filter-card">   (vendored disclosure)
 *     summary   "Filters" · what is active, in words · "42 tasks"
 *     body      text · project | person · due | modified · status | sort — one
 *               control each, equal widths, two per line on the phone (#48);
 *               person and status are multi-selects (one click each, several
 *               allowed: "Anyone" / the name / "2 people")
 *
 * Collapsed by default: the summary line says what is applied, so the card
 * never has to be open to read the state. `mountFilters` keeps the open /
 * closed state, an open dropdown and the text input's focus across re-renders.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES, todayISO } from './format.js';
import { CLOSED, SORTS, sortLabel } from './rows.js';

export const DEFAULT_FILTERS = { status: [], project: '', person: [], due: '', updated: '', q: '', sort: 'due' };
export const DUE_WINDOWS = [['', 'Any due date'], ['today', 'Due today'], ['week', 'Due this week'], ['overdue', 'Overdue']];
export const UPDATED_WINDOWS = [['', 'Modified any time'], ['today', 'Modified today'], ['week', 'Modified in 7 days'], ['month', 'Modified in 30 days']];
const TEXT_DEBOUNCE_MS = 250;

function csv(value) {
  return (value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
}

// ------------------------------------------------------------ URL state
export function filtersFromSearch(search) {
  const p = new URLSearchParams(search || '');
  const f = Object.assign({}, DEFAULT_FILTERS);
  f.status = csv(p.get('status')).filter(function (s) { return STATUSES.indexOf(s) >= 0; });
  f.project = p.get('project') || '';
  f.person = csv(p.get('person')).filter(function (s) { return /^\d+$/.test(s); });
  f.due = DUE_WINDOWS.some(function (w) { return w[0] === p.get('due'); }) ? p.get('due') : '';
  f.updated = UPDATED_WINDOWS.some(function (w) { return w[0] === p.get('updated'); }) ? p.get('updated') : '';
  f.q = p.get('q') || '';
  f.sort = SORTS.some(function (s) { return s[0] === p.get('sort'); }) ? p.get('sort') : 'due';
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
  const s = p.toString();
  return s ? '?' + s : '';
}

export function isDefaultFilters(f) {
  return filtersToSearch(f) === '';
}

// ------------------------------------------------------- server params
/** `updated` window → the ISO date the list API's `updated_since` takes. */
export function updatedSince(window, now) {
  if (!window) return '';
  const d = now ? new Date(now) : new Date();
  const days = window === 'today' ? 0 : (window === 'week' ? 7 : 30);
  d.setDate(d.getDate() - days);
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
  if (f.status.length) { if (f.status.indexOf(t.status) < 0) return false; }
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
    const since = updatedSince(f.updated, today ? today + 'T00:00:00' : undefined);
    if (!t.updated_at || String(t.updated_at).slice(0, 10) < since) return false;
  }
  return true;
}

// ------------------------------------------------------------ summary
/** What is active, in words — the collapsed card's one line. */
export function describeFilters(f, options) {
  const o = options || {};
  const bits = [];
  if (f.status.length) bits.push(f.status.join(', '));
  if (f.project) {
    const p = (o.projects || []).find(function (x) { return String(x.id) === String(f.project); });
    bits.push(p ? p.title : 'project #' + f.project);
  }
  if (f.person.length) {
    bits.push(f.person.map(function (id) {
      const p = (o.people || []).find(function (x) { return String(x.id) === String(id); });
      return p ? p.name : 'person #' + id;
    }).join(', '));
  }
  if (f.due) bits.push((DUE_WINDOWS.find(function (w) { return w[0] === f.due; }) || [])[1].toLowerCase());
  if (f.updated) bits.push((UPDATED_WINDOWS.find(function (w) { return w[0] === f.updated; }) || [])[1].toLowerCase());
  if (f.q && !o.hideText) bits.push('"' + f.q + '"');
  bits.push('sorted by ' + sortLabel(f.sort));
  return bits;
}

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

// One document listener closes any open multi-select on an outside click / Escape.
let outsideWired = false;
function wireOutside() {
  if (outsideWired) return;
  outsideWired = true;
  document.addEventListener('click', function (ev) {
    document.querySelectorAll('.msel[open]').forEach(function (d) { if (!d.contains(ev.target)) d.open = false; });
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') document.querySelectorAll('.msel[open]').forEach(function (d) { d.open = false; });
  });
}

/**
 * A multi-select: a select-looking summary that opens a checklist. One click
 * per option, several allowed; the summary reads `none` / the one label /
 * `N <many>` (#48).
 * @param {string} name
 * @param {string} label      aria label
 * @param {Array<[string,string]>} values   [value, label]
 * @param {Array<string>} selected
 * @param {(next: Array<string>) => void} onChange
 * @param {{none: string, many: string, open?: boolean}} texts  many = the plural noun ("people", "statuses")
 */
export function multiSelect(name, label, values, selected, onChange, texts) {
  wireOutside();
  const d = document.createElement('details');
  d.className = 'msel' + (selected.length ? ' has-value' : '');
  d.dataset.name = name;
  d.open = !!texts.open;
  const summary = document.createElement('summary');
  summary.className = 'select-native msel-summary';
  summary.setAttribute('aria-label', label);
  summary.setAttribute('role', 'button');
  const txt = document.createElement('span');
  txt.className = 'msel-text';
  const picked = values.filter(function (v) { return selected.indexOf(String(v[0])) >= 0; });
  txt.textContent = !picked.length ? texts.none : (picked.length === 1 ? picked[0][1] : picked.length + ' ' + texts.many);
  summary.appendChild(txt);
  d.appendChild(summary);
  const menu = document.createElement('div');
  menu.className = 'msel-menu';
  menu.setAttribute('role', 'group');
  menu.setAttribute('aria-label', label);
  values.forEach(function (v) {
    const opt = document.createElement('label');
    opt.className = 'msel-opt';
    opt.dataset.value = String(v[0]);
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.name = name;
    cb.value = String(v[0]);
    cb.checked = selected.indexOf(String(v[0])) >= 0;
    cb.addEventListener('change', function () {
      const next = selected.filter(function (s) { return s !== String(v[0]); });
      if (cb.checked) next.push(String(v[0]));
      onChange(next);
    });
    opt.appendChild(cb);
    opt.appendChild(document.createTextNode(v[1]));
    menu.appendChild(opt);
  });
  if (!values.length) {
    const none = document.createElement('p');
    none.className = 'msel-none muted';
    none.textContent = 'nothing to pick';
    menu.appendChild(none);
  }
  d.appendChild(menu);
  return d;
}

// ---------------------------------------------------------------- card
/**
 * Mount the filter card into `host`; call `render(filters, options)` on every
 * state change. One instance per tab (each tab has its own host), all reading
 * the same state.
 * @param {HTMLElement} host
 * @param {{onChange: (next: object) => void, hideText?: boolean, countLabel?: string}} opts
 *        hideText — the Search tab's box owns the text, so the card has no text field there
 * @returns {{render: (filters: object, options: {projects: Array, people: Array, count: number}) => void,
 *            setOpen: (open: boolean) => void}}
 */
export function mountFilters(host, opts) {
  let open = false;
  let openMenu = null;     // the multi-select left open across a re-render
  let textTimer = 0;

  function render(filters, options) {
    const o = options || {};
    // keep the typist's place: a keystroke re-renders the card around them
    const active = document.activeElement;
    const typing = active && host.contains(active) && active.classList.contains('filter-q');
    const caret = typing ? active.selectionStart : null;
    const wasOpen = host.querySelector('.msel[open]');
    if (wasOpen) openMenu = wasOpen.dataset.name;

    host.replaceChildren();
    host.hidden = false;
    const card = document.createElement('details');
    card.className = 'card card--collapsible filter-card';
    card.open = open;
    card.addEventListener('toggle', function () { open = card.open; if (!open) openMenu = null; });

    const summary = document.createElement('summary');
    summary.className = 'collapse-summary';
    const main = document.createElement('span');
    main.className = 'collapse-main';
    main.innerHTML = icon('list-filter');
    const h = document.createElement('h3');
    h.className = 'collapse-title';
    h.textContent = 'Filters';
    main.appendChild(h);
    const desc = document.createElement('span');
    desc.className = 'collapse-count filter-desc';
    const bits = describeFilters(filters, { projects: o.projects, people: o.people, hideText: opts.hideText });
    if (o.count != null) bits.push(o.count + ' ' + (opts.countLabel || (o.count === 1 ? 'task' : 'tasks')));
    desc.textContent = bits.join(' · ');
    main.appendChild(desc);
    summary.appendChild(main);
    const chev = document.createElement('span');
    chev.className = 'collapse-chevron';
    chev.setAttribute('aria-hidden', 'true');
    chev.textContent = '›';
    summary.appendChild(chev);
    card.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'collapse-body filter-body';
    const row = document.createElement('div');
    row.className = 'filter-row';
    function change(name) {
      return function (value) { const next = Object.assign({}, filters); next[name] = value; opts.onChange(next); };
    }
    // 1. text (the Search tab's box owns it there)
    if (!opts.hideText) {
      const q = document.createElement('input');
      q.type = 'search';
      q.className = 'input-native filter-q';
      q.placeholder = 'Filter text…';
      q.setAttribute('aria-label', 'Filter text');
      q.value = filters.q;
      q.addEventListener('input', function () {
        window.clearTimeout(textTimer);
        textTimer = window.setTimeout(function () { opts.onChange(Object.assign({}, filters, { q: q.value.trim() })); }, TEXT_DEBOUNCE_MS);
      });
      row.appendChild(q);
    }
    // 2. project | person
    const projectValues = [['', 'All projects']].concat((o.projects || []).map(function (p) {
      return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
    }));
    row.appendChild(selectEl('project', 'Project', projectValues, filters.project, change('project')));
    row.appendChild(multiSelect('person', 'Person', (o.people || []).map(function (p) { return [String(p.id), p.name]; }),
      filters.person, change('person'), { none: 'Anyone', many: 'people', open: openMenu === 'person' }));
    // 3. due | modified
    row.appendChild(selectEl('due', 'Due window', DUE_WINDOWS, filters.due, change('due')));
    row.appendChild(selectEl('updated', 'Modified window', UPDATED_WINDOWS, filters.updated, change('updated')));
    // 4. status | sort
    row.appendChild(multiSelect('status', 'Status', STATUSES.map(function (s) { return [s, s]; }),
      filters.status, change('status'), { none: 'Open tasks', many: 'statuses', open: openMenu === 'status' }));
    row.appendChild(selectEl('sort', 'Sort', SORTS.map(function (s) { return [s[0], 'Sort: ' + s[1]]; }), filters.sort, change('sort')));
    if (!isDefaultFilters(Object.assign({}, filters, { q: opts.hideText ? '' : filters.q }))) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'button-ghost filter-clear';
      clear.textContent = 'Clear';
      clear.addEventListener('click', function () {
        opts.onChange(Object.assign({}, DEFAULT_FILTERS, { q: opts.hideText ? filters.q : '' }));
      });
      row.appendChild(clear);
    }
    body.appendChild(row);
    card.appendChild(body);
    host.appendChild(card);

    if (typing) {
      const q = host.querySelector('.filter-q');
      if (q) { q.focus(); try { q.setSelectionRange(caret, caret); } catch (_) { /* not a text control */ } }
    }
  }

  return { render: render, setOpen: function (v) { open = !!v; } };
}
