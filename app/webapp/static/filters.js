/* task-os — the ONE filter card every tab shares (issue #46).
 *
 * Board, Table, Tree, Today and Search are renderings of the same list, so
 * they read one filter state — this module owns its shape, its URL encoding
 * (`?status=doing&project=12&sort=updated` is the same shareable view on
 * every tab) and the card that edits it:
 *
 *   <details class="card card--collapsible filter-card">   (vendored disclosure)
 *     summary   "Filters" · what is active, in words · "42 tasks"
 *     body      status pills (incl. done / cancelled, so finished items are
 *               findable) · project · person · due window · modified window ·
 *               text · sort (the Tree's order comes from here too) · Clear
 *
 * Collapsed by default: the summary line says what is applied, so the card
 * never has to be open to read the state. `mountFilters` keeps the open /
 * closed state and the text input's focus across re-renders.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES, todayISO } from './format.js';
import { CLOSED, SORTS, sortLabel } from './rows.js';

export const DEFAULT_FILTERS = { status: [], project: '', person: '', due: '', updated: '', q: '', sort: 'due' };
export const DUE_WINDOWS = [['', 'Any due date'], ['today', 'Due today'], ['week', 'Due this week'], ['overdue', 'Overdue']];
export const UPDATED_WINDOWS = [['', 'Modified any time'], ['today', 'Modified today'], ['week', 'Modified in 7 days'], ['month', 'Modified in 30 days']];
const TEXT_DEBOUNCE_MS = 250;

// ------------------------------------------------------------ URL state
export function filtersFromSearch(search) {
  const p = new URLSearchParams(search || '');
  const f = Object.assign({}, DEFAULT_FILTERS);
  f.status = (p.get('status') || '').split(',').map(function (s) { return s.trim(); }).filter(function (s) { return STATUSES.indexOf(s) >= 0; });
  f.project = p.get('project') || '';
  f.person = p.get('person') || '';
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
  if (f.person) p.set('person', f.person);
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

/** The /api/tasks query for a filter state (undefined = not sent). */
export function listParams(f) {
  return {
    status: f.status.length ? f.status : undefined,
    project: f.project || undefined,
    person: f.person || undefined,
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
  if (f.person) {
    const who = t.person_id != null ? t.person_id : (t.person ? t.person.id : null);
    if (String(who) !== String(f.person)) return false;
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
  if (f.person) {
    const p = (o.people || []).find(function (x) { return String(x.id) === String(f.person); });
    bits.push(p ? p.name : 'person #' + f.person);
  }
  if (f.due) bits.push((DUE_WINDOWS.find(function (w) { return w[0] === f.due; }) || [])[1].toLowerCase());
  if (f.updated) bits.push((UPDATED_WINDOWS.find(function (w) { return w[0] === f.updated; }) || [])[1].toLowerCase());
  if (f.q && !o.hideText) bits.push('"' + f.q + '"');
  bits.push('sorted by ' + sortLabel(f.sort));
  return bits;
}

// ---------------------------------------------------------------- card
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
  let textTimer = 0;

  function render(filters, options) {
    const o = options || {};
    // keep the typist's place: a keystroke re-renders the card around them
    const active = document.activeElement;
    const typing = active && host.contains(active) && active.classList.contains('filter-q');
    const caret = typing ? active.selectionStart : null;

    host.replaceChildren();
    host.hidden = false;
    const card = document.createElement('details');
    card.className = 'card card--collapsible filter-card';
    card.open = open;
    card.addEventListener('toggle', function () { open = card.open; });

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

    // status pills — standard pill size, a toggle each; none pressed = open tasks
    const st = document.createElement('div');
    st.className = 'filter-status';
    st.setAttribute('role', 'group');
    st.setAttribute('aria-label', 'Status');
    STATUSES.forEach(function (s) {
      const on = filters.status.indexOf(s) >= 0;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pill pill-' + s + ' filter-pill hit-target' + (on ? ' active' : '');
      b.dataset.status = s;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.textContent = s;
      b.addEventListener('click', function () {
        const set = filters.status.slice();
        const i = set.indexOf(s);
        if (i >= 0) set.splice(i, 1); else set.push(s);
        opts.onChange(Object.assign({}, filters, { status: set }));
      });
      st.appendChild(b);
    });
    body.appendChild(st);

    const row = document.createElement('div');
    row.className = 'filter-row';
    function change(name) {
      return function (value) { const next = Object.assign({}, filters); next[name] = value; opts.onChange(next); };
    }
    const projectValues = [['', 'All projects']].concat((o.projects || []).map(function (p) {
      return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
    }));
    row.appendChild(selectEl('project', 'Project', projectValues, filters.project, change('project')));
    const personValues = [['', 'Anyone']].concat((o.people || []).map(function (p) { return [p.id, p.name]; }));
    row.appendChild(selectEl('person', 'Person', personValues, filters.person, change('person')));
    row.appendChild(selectEl('due', 'Due window', DUE_WINDOWS, filters.due, change('due')));
    row.appendChild(selectEl('updated', 'Modified window', UPDATED_WINDOWS, filters.updated, change('updated')));
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
