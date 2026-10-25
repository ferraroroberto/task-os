/* task-os — the Time tab's dialogs, on the vendored editor modal.
 *
 * One `<dialog id="timeDialog">` shell, built per ask like confirm.js does:
 *
 *   openEntryEditor   add time already spent, or edit any entry (either
 *                     person's): person, category, day, start, minutes, note
 *   askSwitch         a timer is running — "Stop and start <category>"
 *   promptText        a name (add / rename an area)
 *   promptCategory    a category's name and subtitle (add / edit)
 *   pickOption        one choice from a list (move a category to an area)
 *   showInfo          a read-only explanation (the comparison's ⓘ)
 *
 * Every one has exactly one full-width primary (design.md `modal`); the ×,
 * Esc and the backdrop all mean "no". The destructive Delete is confirm.js's.
 */

'use strict';

import { api } from './api.js';
import { closeOnBackdrop, modalCard } from './modal.js';
import { addDaysISO, clockOf, hhmmToMinutes, minutesToHHMM } from './time-format.js';

const MINUTE_CHIPS = [15, 30, 45, 60, 90, 120];

/** Open `#timeDialog` titled `title`; `build(card, finish)` fills the body and
 *  calls `finish(value)` to close with an answer. Resolves to that value, or
 *  null when it was dismissed. */
function openDialog(title, build) {
  const dialog = document.getElementById('timeDialog');
  if (!dialog) return Promise.resolve(null);
  return new Promise(function (resolve) {
    let answer = null;
    const shell = modalCard({
      cardClass: 'time-dialog-card', title: title, titleId: 'timeDialogTitle', closeLabel: 'Close',
      onClose: function () { dialog.close(); },
    });
    const finish = function (value) { answer = value; dialog.close(); };
    const focus = build(shell.card, finish);
    const offBackdrop = closeOnBackdrop(dialog);
    dialog.addEventListener('close', function onClose() {
      dialog.removeEventListener('close', onClose);
      offBackdrop();
      dialog.replaceChildren();
      resolve(answer);
    });
    dialog.replaceChildren(shell.card);
    dialog.showModal();
    (focus || shell.close).focus();
  });
}

function row(label, control, id) {
  const r = document.createElement('div');
  r.className = 'row time-form-row';
  const span = document.createElement('span');
  span.textContent = label;
  if (id) span.id = id;
  r.append(span, control);
  return r;
}

function primary(label, track) {
  const actions = document.createElement('div');
  actions.className = 'detail-actions';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'button-primary detail-save-btn';
  btn.textContent = label;
  if (track) btn.dataset.track = track;
  actions.appendChild(btn);
  return { actions: actions, button: btn };
}

function message() {
  const p = document.createElement('p');
  p.className = 'time-form-msg';
  p.setAttribute('role', 'alert');
  return p;
}

/** A row of pick buttons (Today / Yesterday, the minute chips): pressed when
 *  its value is the field's. */
function picks(values, label, onPick) {
  const wrap = document.createElement('div');
  wrap.className = 'time-picks';
  values.forEach(function (v) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button-surface time-pick';
    b.dataset.value = String(v.value);
    b.textContent = v.label;
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', function () { onPick(v.value); });
    wrap.appendChild(b);
  });
  wrap.setAttribute('aria-label', label);
  wrap.setAttribute('role', 'group');
  return {
    el: wrap,
    sync: function (current) {
      wrap.querySelectorAll('.time-pick').forEach(function (b) {
        b.setAttribute('aria-pressed', b.dataset.value === String(current) ? 'true' : 'false');
      });
    },
  };
}

/** The category picker: one optgroup per area, archived areas and
 *  categories left out — except the entry's own, which an edit keeps. */
function categorySelect(meta, currentId) {
  const sel = document.createElement('select');
  sel.className = 'select-native';
  sel.setAttribute('aria-label', 'Category');
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = 'Choose…';
  sel.appendChild(blank);
  meta.areas.forEach(function (a) {
    const cats = a.categories.filter(function (c) { return c.id === currentId || (!a.archived && !c.archived); });
    if (!cats.length) return;
    const g = document.createElement('optgroup');
    g.label = a.name;
    cats.forEach(function (c) {
      const o = document.createElement('option');
      o.value = String(c.id);
      o.textContent = c.name;
      g.appendChild(o);
    });
    sel.appendChild(g);
  });
  sel.value = currentId ? String(currentId) : '';
  return sel;
}

/** The person picker: a segmented control for up to five people (design.md:
 *  2–5 peers), a select past that. */
function personControl(people, current) {
  let value = current;
  if (people.length > 5) {
    const sel = document.createElement('select');
    sel.className = 'select-native';
    sel.setAttribute('aria-label', 'Person');
    people.forEach(function (p) {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = p.name;
      sel.appendChild(o);
    });
    sel.value = current;
    return { el: sel, value: function () { return sel.value; }, onChange: function (fn) { sel.addEventListener('change', fn); } };
  }
  const seg = document.createElement('div');
  seg.className = 'segmented time-person-seg';
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-label', 'Person');
  const listeners = [];
  people.forEach(function (p) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'segmented-item';
    b.dataset.value = p.id;
    b.textContent = p.name;
    b.setAttribute('aria-pressed', p.id === current ? 'true' : 'false');
    b.addEventListener('click', function () {
      value = p.id;
      seg.querySelectorAll('.segmented-item').forEach(function (x) {
        x.setAttribute('aria-pressed', x.dataset.value === value ? 'true' : 'false');
      });
      listeners.forEach(function (fn) { fn(); });
    });
    seg.appendChild(b);
  });
  return { el: seg, value: function () { return value; }, onChange: function (fn) { listeners.push(fn); } };
}

/**
 * Add time already spent (`entry` null) or edit an entry. Resolves to the
 * saved entry, or null when dismissed.
 * @param {{meta: object, person: string, today: string, now: string, entry?: object|null}} o
 *        `now` is the server's current ISO time (the default start of a new entry)
 */
export function openEntryEditor(o) {
  const editing = !!o.entry;
  const e = o.entry || {};
  const clocked = !editing || !!e.started_at;
  return openDialog(editing ? 'Edit entry' : 'Add time already spent', function (card, finish) {
    const people = o.meta.people;
    const person = people.length > 1 ? personControl(people, editing ? e.person : o.person) : null;
    const cat = categorySelect(o.meta, editing ? e.category_id : null);
    const day = document.createElement('input');
    day.type = 'date';
    day.className = 'input-native';
    day.max = o.today;
    day.value = editing ? e.day : o.today;
    day.setAttribute('aria-label', 'Day');
    const dayPicks = picks([
      { value: o.today, label: 'Today' }, { value: addDaysISO(o.today, -1), label: 'Yesterday' },
    ], 'Day', function (v) { day.value = v; sync(); });
    const minutes = document.createElement('input');
    minutes.type = 'number';
    minutes.inputMode = 'numeric';
    minutes.min = '1';
    minutes.max = String(o.meta.max_minutes);
    minutes.className = 'input-native time-minutes';
    minutes.value = editing ? String(e.minutes) : '';
    minutes.setAttribute('aria-label', 'Minutes');
    const minutePicks = picks(MINUTE_CHIPS.map(function (m) { return { value: m, label: String(m) }; }),
      'Minutes', function (v) { minutes.value = String(v); sync(); });
    const start = document.createElement('input');
    start.type = 'time';
    start.className = 'input-native';
    start.setAttribute('aria-label', 'Start');
    let startTouched = editing;
    start.value = editing ? clockOf(e.started_at) : '';
    start.addEventListener('input', function () { startTouched = true; });
    const note = document.createElement('input');
    note.type = 'text';
    note.maxLength = 140;
    note.className = 'input-native';
    note.value = editing ? (e.note || '') : '';
    note.placeholder = 'Optional';
    note.setAttribute('aria-label', 'Note');
    const msg = message();
    const save = primary(editing ? 'Save' : 'Add', editing ? 'time-edit-save' : 'time-add-save');

    if (person) card.appendChild(row('Person', person.el));
    card.appendChild(row('Category', cat));
    const dayBox = document.createElement('div');
    dayBox.className = 'time-field-stack';
    dayBox.append(day, dayPicks.el);
    card.appendChild(row('Day', dayBox));
    if (clocked) card.appendChild(row('Start', start));
    const minBox = document.createElement('div');
    minBox.className = 'time-field-stack';
    minBox.append(minutes, minutePicks.el);
    card.appendChild(row('Minutes', minBox));
    if (!clocked) {
      const p = document.createElement('p');
      p.className = 'muted time-form-note';
      p.textContent = 'Imported with a duration only, so it has no start time.';
      card.appendChild(p);
    }
    card.appendChild(row('Note', note));
    card.append(msg, save.actions);

    /** A new entry's untouched start is "it just ended": now − minutes
     *  today, 09:00 on an earlier day. */
    function defaultStart() {
      if (startTouched) return;
      const mins = Number(minutes.value) || 0;
      start.value = day.value === o.today
        ? minutesToHHMM(Math.max(0, hhmmToMinutes(clockOf(o.now)) - mins))
        : '09:00';
    }

    function payload() {
      const body = {
        category_id: Number(cat.value) || null,
        day: day.value,
        minutes: Number(minutes.value),
        note: note.value.trim(),
      };
      if (person) body.person = person.value();
      if (clocked && start.value) body.start = start.value;
      return body;
    }

    function valid(b) {
      return !!b.category_id && !!b.day && b.day <= o.today && Number.isInteger(b.minutes)
        && b.minutes >= 1 && b.minutes <= o.meta.max_minutes && (!clocked || !!b.start);
    }

    function changed(b) {
      if (!editing) return true;
      return (b.person !== undefined && b.person !== e.person) || b.category_id !== e.category_id
        || b.day !== e.day || b.minutes !== e.minutes || b.note !== (e.note || '')
        || (clocked && b.start !== clockOf(e.started_at));
    }

    let gone = false;
    function sync() {
      if (gone) { save.button.disabled = true; return; }
      if (!editing) defaultStart();
      dayPicks.sync(day.value);
      minutePicks.sync(minutes.value);
      const b = payload();
      save.button.disabled = !(valid(b) && changed(b));
    }

    [cat, day, minutes, start, note].forEach(function (el) { el.addEventListener('input', sync); });
    cat.addEventListener('change', sync);
    if (person) person.onChange(sync);
    sync();

    save.button.addEventListener('click', async function () {
      const b = payload();
      if (!editing && !b.person) b.person = o.person;
      save.button.disabled = true;
      msg.textContent = '';
      try {
        let saved;
        if (editing) {
          const patch = {};
          Object.keys(b).forEach(function (k) {
            const before = k === 'start' ? clockOf(e.started_at) : (k === 'note' ? (e.note || '') : e[k]);
            if (b[k] !== before) patch[k] = b[k];
          });
          saved = await api('/api/time/entries/' + e.id, { method: 'PATCH', body: patch });
        } else {
          saved = await api('/api/time/entries', { method: 'POST', body: b });
        }
        finish(saved);
      } catch (err) {
        if (err.status === 404) {
          // Deleted on another device: say so and stay open, with nothing to save.
          gone = true;
          msg.textContent = 'This entry was deleted meanwhile, so nothing was changed.';
          return;
        }
        msg.textContent = err.message;
        sync();
      }
    });
    return cat;
  });
}

/** A timer is running: offer to stop it and start `to` (one server call).
 *  Resolves true to switch. */
export function askSwitch(o) {
  return openDialog('A timer is running', function (card, finish) {
    const p = document.createElement('p');
    p.className = 'time-dialog-text';
    p.textContent = (o.from ? o.from + ' is running. ' : '') + 'Stop it, save the time, and start ' + o.to + '?';
    const go = primary('Stop and start ' + o.to, 'time-switch');
    go.button.addEventListener('click', function () { finish(true); });
    card.append(p, go.actions);
    return null;
  }).then(function (v) { return v === true; });
}

/** One text field and one primary. Resolves to the trimmed text, or null. */
export function promptText(o) {
  return openDialog(o.title, function (card, finish) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'input-native';
    input.maxLength = 80;
    input.value = o.value || '';
    input.setAttribute('aria-label', o.label);
    const go = primary(o.action || 'Save');
    const sync = function () { go.button.disabled = !input.value.trim() || input.value.trim() === (o.value || ''); };
    input.addEventListener('input', sync);
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !go.button.disabled) finish(input.value.trim());
    });
    go.button.addEventListener('click', function () { finish(input.value.trim()); });
    card.append(row(o.label, input), go.actions);
    sync();
    return input;
  });
}

/** A category's name and its optional subtitle (the `hint` under the name),
 *  and one primary. Resolves to {name, hint} trimmed — an empty hint
 *  clears it — or null. */
export function promptCategory(o) {
  return openDialog(o.title, function (card, finish) {
    const field = function (label, value, placeholder) {
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'input-native';
      input.maxLength = 80;
      input.value = value || '';
      if (placeholder) input.placeholder = placeholder;
      input.setAttribute('aria-label', label);
      return input;
    };
    const name = field('Name', o.name);
    const hint = field('Subtitle', o.hint, 'Optional');
    const go = primary(o.action || 'Save');
    const answer = function () { return { name: name.value.trim(), hint: hint.value.trim() }; };
    const sync = function () {
      const a = answer();
      go.button.disabled = !a.name || (a.name === (o.name || '') && a.hint === (o.hint || ''));
    };
    [name, hint].forEach(function (input) {
      input.addEventListener('input', sync);
      input.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' && !go.button.disabled) finish(answer());
      });
    });
    go.button.addEventListener('click', function () { finish(answer()); });
    card.append(row('Name', name), row('Subtitle', hint), go.actions);
    sync();
    return name;
  });
}

/** One select and one primary. Resolves to the chosen value, or null. */
export function pickOption(o) {
  return openDialog(o.title, function (card, finish) {
    const sel = document.createElement('select');
    sel.className = 'select-native';
    sel.setAttribute('aria-label', o.label);
    o.options.forEach(function (opt) {
      const el = document.createElement('option');
      el.value = String(opt.value);
      el.textContent = opt.label;
      sel.appendChild(el);
    });
    sel.value = String(o.value);
    const go = primary(o.action || 'Move');
    const sync = function () { go.button.disabled = sel.value === String(o.value); };
    sel.addEventListener('change', sync);
    go.button.addEventListener('click', function () { finish(sel.value); });
    card.append(row(o.label, sel), go.actions);
    sync();
    return sel;
  });
}

/** A read-only explanation: its lines, and Done. */
export function showInfo(o) {
  return openDialog(o.title, function (card, finish) {
    o.lines.forEach(function (line) {
      const p = document.createElement('p');
      p.className = 'time-dialog-text';
      p.textContent = line;
      card.appendChild(p);
    });
    const go = primary('Done');
    go.button.addEventListener('click', function () { finish(true); });
    card.appendChild(go.actions);
    return null;
  });
}
