/* task-os — the ONE filter card every tab shares (issue #46, #48).
 *
 * Board, Table, Tree, Today and Search are renderings of the same list, so
 * they read one filter state — this module owns its shape, its URL encoding
 * (`?status=doing&project=12&person=3,5&sort=updated` is the same shareable
 * view on every tab) and the card that edits it:
 *
 *   <input class="filter-q">          the live text filter, always visible in
 *                                     the pane's own top strip (#80)
 *
 *   <details class="card card--collapsible filter-card">   (vendored disclosure)
 *     summary   "Filters" · what is active, in words · "42 tasks"
 *     body      project | person · due | modified · status | sort — one
 *               control each, equal widths, two per line on the phone (#48);
 *               person and status are multi-selects (one click each, several
 *               allowed: "Anyone" / the name / "2 people")
 *
 * The card is collapsed by default: the summary line says what is applied, so
 * it never has to be open to read the state. The text input lives outside it
 * (#80) — the filter reached for most is one keystroke away — and is built
 * once, so a re-render never moves the caret. `mountFilters` keeps the open /
 * closed state and an open dropdown across re-renders.
 */

'use strict';

import { icon } from './_vendored/icons/icons.js';
import { STATUSES, todayISO } from './format.js';
import { CLOSED, SORTS, sortLabel } from './rows.js';

export const DEFAULT_FILTERS = { status: [], project: '', person: [], due: '', updated: '', q: '', sort: 'due' };
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
/** What is active, in words — the collapsed card's one line. The text is not
 * in it: whichever box owns the text is always on screen (the top strip, or
 * the Search tab's own box), so repeating it under that box is noise (#80). */
export function describeFilters(f, options) {
  const o = options || {};
  const hidden = new Set(o.hide || []);   // a hidden control's value is not applied, so not described
  const bits = [];
  if (f.status.length && !hidden.has('status')) bits.push(f.status.join(', '));
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
  if (f.due && !hidden.has('due')) bits.push((DUE_WINDOWS.find(function (w) { return w[0] === f.due; }) || [])[1].toLowerCase());
  if (f.updated && !hidden.has('updated')) bits.push((UPDATED_WINDOWS.find(function (w) { return w[0] === f.updated; }) || [])[1].toLowerCase());
  if (!hidden.has('sort')) bits.push('sorted by ' + sortLabel(f.sort));
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
 * @param {{onChange: (next: object) => void, textHost?: HTMLElement, countLabel?: string}} opts
 *        textHost — where the always-visible text input goes (the pane's top
 *        strip, #80). Omitted on the Search tab: its own box owns the text,
 *        so there is no second text field and `Clear` leaves the query alone.
 * @returns {{render: (filters: object, options: {projects: Array, people: Array, count: number}) => void,
 *            setOpen: (open: boolean) => void}}
 */
/**
 * @param {HTMLElement} host
 * @param {{onChange: (f: object) => void, textHost?: HTMLElement, hide?: string[],
 *          countLabel?: string}} opts
 *          hide = control names this card leaves out (`status` · `due` ·
 *          `updated` · `sort` · `project` · `person`) — the journal (#102)
 *          drops the four that say nothing about a closed task; a hidden
 *          control's value is neither drawn nor described
 */
export function mountFilters(host, opts) {
  const hidden = new Set(opts.hide || []);
  let open = false;
  let openMenu = null;       // the multi-select left open across a re-render
  let textTimer = 0;
  let textEl = null;         // the strip's input — built once, never re-rendered
  let current = DEFAULT_FILTERS;   // the state the controls were last drawn from

  /** The live text filter, in the pane's top strip (#80). */
  function renderText(filters) {
    if (!opts.textHost) return;
    if (!textEl) {
      textEl = document.createElement('input');
      textEl.type = 'search';
      textEl.className = 'input-native filter-q';
      textEl.placeholder = 'Filter text…';
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
  }

  function render(filters, options) {
    const o = options || {};
    current = filters;
    renderText(filters);
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
    const bits = describeFilters(filters, { projects: o.projects, people: o.people, hide: opts.hide });
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
    // 1. project | person  (the text is the strip's, #80)
    const projectValues = [['', 'All projects']].concat((o.projects || []).map(function (p) {
      return [p.id, (p.depth ? ' '.repeat(p.depth) : '') + p.title];
    }));
    if (!hidden.has('project')) row.appendChild(selectEl('project', 'Project', projectValues, filters.project, change('project')));
    if (!hidden.has('person')) {
      row.appendChild(multiSelect('person', 'Person', (o.people || []).map(function (p) { return [String(p.id), p.name]; }),
        filters.person, change('person'), { none: 'Anyone', many: 'people', open: openMenu === 'person' }));
    }
    // 2. due | modified
    if (!hidden.has('due')) row.appendChild(selectEl('due', 'Due window', DUE_WINDOWS, filters.due, change('due')));
    if (!hidden.has('updated')) row.appendChild(selectEl('updated', 'Modified window', UPDATED_WINDOWS, filters.updated, change('updated')));
    // 3. status | sort
    // `deferred` and `blocked` ride the end of the status list — the one
    // visible way to see the sleeping (#87) and the locked (#100) tasks the
    // working views leave out.
    const statusValues = STATUSES.map(function (s) { return [s, s]; }).concat([[DEFERRED, DEFERRED], [BLOCKED, BLOCKED]]);
    if (!hidden.has('status')) {
      row.appendChild(multiSelect('status', 'Status', statusValues,
        filters.status, change('status'), { none: 'Open tasks', many: 'statuses', open: openMenu === 'status' }));
    }
    if (!hidden.has('sort')) row.appendChild(selectEl('sort', 'Sort', SORTS.map(function (s) { return [s[0], 'Sort: ' + s[1]]; }), filters.sort, change('sort')));
    if (!isDefaultFilters(Object.assign({}, filters, { q: opts.textHost ? filters.q : '' }))) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'button-ghost filter-clear';
      clear.textContent = 'Clear';
      clear.addEventListener('click', function () {
        opts.onChange(Object.assign({}, DEFAULT_FILTERS, { q: opts.textHost ? '' : filters.q }));
      });
      row.appendChild(clear);
    }
    body.appendChild(row);
    card.appendChild(body);
    host.appendChild(card);
  }

  return { render: render, setOpen: function (v) { open = !!v; } };
}
