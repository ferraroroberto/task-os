/* task-os — "Your name": the author recorded on the comments and activity this
 * install writes. The row shows the stored name; the sheet edits it and saves it
 * to the config file through `PUT /api/your-name`. */

'use strict';

import { api } from '../../api.js';
import { toast } from '../../toast.js';

const SHEET_HTML = `
  <p class="card-meta">The name recorded on the comments and activity this install writes. Leave it blank to use the first team member, else <code>me</code>. A name picked in team mode, or a member signed in with their own token, still wins. Earlier entries keep the name they were written under.</p>
  <form class="your-name-form" id="yourNameForm" autocomplete="off">
    <label class="your-name-field">
      <span class="row-actions-label">Name</span>
      <input data-track="settings.your-name" id="yourNameInput" class="input-native" type="text"
             maxlength="80" spellcheck="false" autocomplete="off" placeholder="me">
    </label>
    <div class="card-actions">
      <button data-track="settings.your-name-save" type="submit" id="yourNameSave" class="button-surface">Save name</button>
    </div>
    <p class="card-meta" id="yourNameStatus" role="status" aria-live="polite"></p>
  </form>`;

/** Fill this card's section, which the sheet's markup leaves empty: the form
 *  sits beside the code that reads it. Call it after the sheet is filled and
 *  before the elements are looked up. */
export function buildYourNameSheet() {
  document.getElementById('yourNameCard').innerHTML = SHEET_HTML;
}

/** The author half of `GET /api/status` (`{your_name, author}`); `null` when the
 *  status call itself failed. The row says what is stored ("not set" when blank);
 *  the fallback name shows in the field's placeholder and the saved line, not in
 *  the row. A field being typed in is left alone. */
export function renderYourName(ctx, st) {
  ctx.els.yourNameMeta.textContent = st ? (st.your_name || 'not set') : 'unknown';
  if (st && document.activeElement !== ctx.els.yourNameInput) ctx.els.yourNameInput.value = st.your_name;
  if (st) ctx.els.yourNameInput.placeholder = st.your_name ? '' : st.author;
}

export function wireYourName(ctx) {
  const els = ctx.els;
  els.yourNameForm.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    els.yourNameSave.disabled = true;
    els.yourNameStatus.textContent = '';
    try {
      const st = await api('/api/your-name', { method: 'PUT', body: { name: els.yourNameInput.value } });
      els.yourNameInput.blur();
      renderYourName(ctx, st);
      els.yourNameStatus.textContent = st.your_name ? 'Saved. New comments and activity are recorded as ' + st.author + '.'
        : 'Cleared. New comments and activity are recorded as ' + st.author + '.';
      toast('Name saved', 'success');
    } catch (err) {
      els.yourNameStatus.textContent = err.message || 'Could not save the name';
      toast(err.message || 'Could not save the name', 'error');
    }
    els.yourNameSave.disabled = false;
  });
}
