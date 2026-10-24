/* task-os — quick-add: the parse preview. The parent chip and the two date
 * fields are written here and nowhere else, whether the line was typed or
 * spoken. */

'use strict';

import { api } from '../../api.js';
import { icon } from '../../_vendored/icons/icons.js';
import { relDue } from '../../format.js';

/** The parse preview: the parent only — the due is in the Due field, where
 *  it can be corrected, so a chip repeating it would be a second truth. */
export function renderChips(ctx) {
  const parsed = ctx.st.parsed;
  const chips = ctx.els.chips;
  chips.innerHTML = '';
  if (!parsed || !parsed.parent_ref) return;
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

/** The phrase the parser understood, next to the date it produced. Both date
 *  fields fill this way, so `due oct 15 starts oct 1` previews as two
 *  correctable dates rather than one date and a mystery (#87). */
export function showDate(el, iso, phrase) {
  el.value = iso || '';
  const rel = iso ? relDue(iso) : { text: '' };
  el.title = iso
    ? (phrase ? '"' + phrase + '"' : '') + (rel.text ? (phrase ? ' · ' : '') + rel.text : '')
    : '';
}

/** Apply a parse result to the preview — the one place chips and the two
 *  date fields are written, whether the line was typed or spoken. */
export function applyParse(ctx, res, text) {
  const st = ctx.st;
  st.parsed = res;
  st.parsed._for = text;
  renderChips(ctx);
  if (!st.touched.due) showDate(ctx.els.due, st.parsed.due, st.parsed.due_phrase);
  if (!st.touched.starts) showDate(ctx.els.starts, st.parsed.starts, st.parsed.starts_phrase);
}

export async function parseNow(ctx) {
  const st = ctx.st;
  const text = ctx.els.input.value.trim();
  const my = ++st.seq;
  if (!text) {
    st.parsed = null;
    renderChips(ctx);
    if (!st.touched.due) showDate(ctx.els.due, '', '');
    if (!st.touched.starts) showDate(ctx.els.starts, '', '');
    return;
  }
  try {
    const res = await api('/api/parse', { method: 'POST', body: { text: text } });
    if (my !== st.seq) return;           // a newer keystroke superseded this parse
    applyParse(ctx, res, text);
  } catch (_) {
    // Parsing is a convenience: a failed parse just means no preview.
    if (my === st.seq) { st.parsed = null; renderChips(ctx); }
  }
}
