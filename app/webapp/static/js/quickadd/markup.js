/* task-os — quick-add: the dialog's markup. The `#quickAdd` shell in
 * index.html stays empty, like every other editor-modal dialog there, and
 * the composer fills it before it looks a field up.
 */

'use strict';

/** Fill the `#quickAdd` shell with its form. */
export function fillQuickAdd(dialog) {
  dialog.innerHTML = `
  <form class="detail-card quickadd-card" autocomplete="off">
    <div class="detail-header">
      <h2 id="quickAddTitle">Add task</h2>
      <button type="button" class="icon-button detail-close" aria-label="Close">
        <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-x"></use></svg>
      </button>
    </div>
    <div class="quick-add-row">
      <span class="quick-add-glyph">
        <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-plus"></use></svg>
      </span>
      <input class="quick-add-input" type="text" enterkeyhint="done" aria-label="Task title"
             placeholder='e.g. "renew passport next friday",  "order sensor &rsaquo; garden-bot",  "#12" to nest'>
      <!-- Click to dictate the line above, click again to stop — the glyph
           becomes a stop square while recording and the words appear on the
           line as they are heard. Never a dead button: when no transcription
           endpoint answers it stays visible, disabled, and the reason is
           spelled out in the hint below. -->
      <button type="button" class="icon-button quick-add-mic" data-track="quick-add.voice" aria-label="Dictate (click to start)"
              aria-pressed="false" disabled>
        <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-mic"></use></svg>
      </button>
    </div>
    <p class="quick-add-voice-hint" aria-live="polite" hidden></p>
    <div class="quick-add-chips" aria-live="polite"></div>

    <div class="row row--stack">
      <span><label for="quickAddDesc">Description</label></span>
      <textarea id="quickAddDesc" class="input-native quick-add-desc" rows="2"
                placeholder="Optional — markdown welcome"></textarea>
    </div>
    <div class="row">
      <span><label for="quickAddDue">Due</label></span>
      <input id="quickAddDue" class="input-native quick-add-due" type="date">
    </div>
    <div class="row">
      <span><label for="quickAddStarts">Starts</label></span>
      <input id="quickAddStarts" class="input-native quick-add-starts" type="date">
    </div>
    <div class="row">
      <span><label for="quickAddStatus">Status</label></span>
      <select id="quickAddStatus" class="select-native quick-add-status"></select>
    </div>
    <div class="row row--stack">
      <span>
        <label for="quickAddFolder">Folder</label>
        <button type="button" class="button-ghost folder-pick quick-add-pick"
                aria-label="Find in folder index" title="Find in folder index"
                aria-expanded="false" aria-controls="quickAddPicker">
          <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-search"></use></svg>
          <span class="folder-pick-label">Find in folder index</span>
        </button>
      </span>
      <input id="quickAddFolder" class="input-native quick-add-folder" type="text"
             placeholder="{onedrive}/folder  — or paste an absolute path">
      <div class="folder-picker quick-add-picker" id="quickAddPicker" hidden></div>
    </div>
    <div class="row row--stack">
      <span><label for="quickAddLink">Link</label></span>
      <div class="quick-add-link">
        <input id="quickAddLink" class="input-native quick-add-link-url" type="text"
               placeholder="https://…  — a conversation, a doc, an issue">
        <input class="input-native quick-add-link-label" type="text"
               aria-label="Link label" placeholder="label (optional)">
      </div>
    </div>

    <div class="detail-actions">
      <!-- The dialog's one primary (design.md modal.primaryButton): the vendored
           button-primary — 48px, accent-fill, the AA disabled recipe. -->
      <button type="submit" class="button-primary detail-save-btn quick-add-submit" data-track="quick-add.submit" disabled>Add</button>
    </div>
  </form>
`;
}
