/* task-os — quick-add bar ("+ Add task…") mounted at the top of the Board,
 * Table and Tree panes.
 *
 * Natural language goes to POST /api/parse (server-side, so the CLI and the
 * UI agree on what "next friday" means): the parsed due date and parent show
 * as chips under the input before submit; Enter creates the task through
 * POST /api/tasks with the resolved fields and hands the new task to the
 * caller (which focuses its row).
 */

'use strict';

import { api } from './api.js';
import { icon } from './_vendored/icons/icons.js';
import { relDue } from './format.js';
import { toast } from './toast.js';

const PARSE_DEBOUNCE_MS = 180;

/**
 * @param {HTMLElement} host    the empty `.quick-add` container
 * @param {{onCreated: (task: object) => void}} opts
 * @returns {{focus: () => void}}
 */
export function mountQuickAdd(host, opts) {
  host.innerHTML = '';
  const form = document.createElement('form');
  form.className = 'quick-add-form';
  form.setAttribute('autocomplete', 'off');

  const row = document.createElement('div');
  row.className = 'quick-add-row';
  const glyph = document.createElement('span');
  glyph.className = 'quick-add-glyph';
  glyph.innerHTML = icon('plus');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'quick-add-input';
  input.placeholder = 'Add task…  e.g. "renew passport next friday",  "order sensor › garden-bot",  "#12" to nest';
  input.setAttribute('aria-label', 'Add task');
  input.enterKeyHint = 'done';
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.className = 'button-tint quick-add-submit';
  submit.textContent = 'Add';
  submit.disabled = true;
  row.append(glyph, input, submit);

  const chips = document.createElement('div');
  chips.className = 'quick-add-chips';
  chips.setAttribute('aria-live', 'polite');
  form.append(row, chips);
  host.appendChild(form);

  let parsed = null;
  let timer = 0;
  let seq = 0;

  function renderChips() {
    chips.innerHTML = '';
    if (!parsed) return;
    if (parsed.due) {
      const c = document.createElement('span');
      c.className = 'chip chip-date';
      c.dataset.due = parsed.due;
      c.innerHTML = icon('calendar-days');
      const t = document.createElement('span');
      t.className = 'chip-label';
      const rel = relDue(parsed.due);
      t.textContent = parsed.due + (rel.text ? ' · ' + rel.text : '') + (parsed.due_phrase ? '  (' + parsed.due_phrase + ')' : '');
      c.appendChild(t);
      chips.appendChild(c);
    }
    if (parsed.parent_ref) {
      const c = document.createElement('span');
      c.className = 'chip chip-parent' + (parsed.parent ? '' : ' chip-missing');
      c.innerHTML = icon('corner-down-right');
      const t = document.createElement('span');
      t.className = 'chip-label';
      if (parsed.parent) {
        c.dataset.parentId = String(parsed.parent.id);
        t.textContent = 'in ' + parsed.parent.title + ' (#' + parsed.parent.id + ')';
      } else {
        const ref = parsed.parent_ref.id != null ? '#' + parsed.parent_ref.id : parsed.parent_ref.title;
        t.textContent = 'no such parent: ' + ref;
      }
      c.appendChild(t);
      chips.appendChild(c);
    }
  }

  async function parseNow() {
    const text = input.value.trim();
    const my = ++seq;
    if (!text) { parsed = null; renderChips(); return; }
    try {
      const res = await api('/api/parse', { method: 'POST', body: { text: text } });
      if (my !== seq) return;           // a newer keystroke superseded this parse
      parsed = res;
      parsed._for = text;
      renderChips();
    } catch (_) {
      // Parsing is a convenience: a failed parse just means no chips.
      if (my === seq) { parsed = null; renderChips(); }
    }
  }

  input.addEventListener('input', function () {
    submit.disabled = !input.value.trim();
    window.clearTimeout(timer);
    timer = window.setTimeout(parseNow, PARSE_DEBOUNCE_MS);
  });

  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    window.clearTimeout(timer);
    // Make sure the chips reflect the final text before creating.
    if (!parsed || parsed._for !== text) {
      try {
        parsed = await api('/api/parse', { method: 'POST', body: { text: text } });
        parsed._for = text;
      } catch (_) { parsed = null; }
    }
    const body = { title: (parsed && parsed.title) || text };
    if (parsed && parsed.due) body.due = parsed.due;
    if (parsed && parsed.parent_ref) {
      if (!parsed.parent) {
        toast('No task matches that parent — nothing created', 'error');
        return;
      }
      body.parent_id = parsed.parent.id;
    }
    submit.disabled = true;
    try {
      const task = await api('/api/tasks', { method: 'POST', body: body });
      input.value = '';
      parsed = null;
      renderChips();
      toast('Added #' + task.id + ' ' + task.title, 'success');
      if (opts && opts.onCreated) opts.onCreated(task);
    } catch (err) {
      toast(err.message || 'Could not add the task', 'error');
      submit.disabled = false;
    }
  });

  return { focus: function () { input.focus(); } };
}
