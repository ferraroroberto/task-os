/* task-os — Settings: the rows' sheet markup. The `#settingsSheet` shell in
 * index.html stays empty, like every other editor-modal dialog there: one
 * `data-sheet` section per Settings row, under the ids the cards read and
 * write, so the composer fills it before anything looks an element up.
 */

'use strict';

const CARD_HTML = `
  <div class="detail-card">
    <div class="detail-header">
      <h2 id="settingsSheetTitle" tabindex="-1" autofocus></h2>
      <button data-track="settings-sheet.close" type="button" class="icon-button detail-close" aria-label="Close">
        <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-x"></use></svg>
      </button>
    </div>
    <div class="settings-sheet-body">
      <section class="settings-sheet-section" id="rowActionsCard" data-sheet="rows" data-surface="settings.row-actions" hidden>
        <p class="card-meta">What a swipe on a task row does on a touch screen, and what the row's ⋯ menu lists, in order. On this device. An action a swipe runs always stays in the menu, and every action keeps its key and its palette entry. The task's own links and Open details always follow.</p>
        <label class="row-actions-field">
          <span class="row-actions-label">Swipe right</span>
          <select data-track="settings.swipe-right" class="select-native" id="swipeRightSelect"></select>
        </label>
        <label class="row-actions-field">
          <span class="row-actions-label">Swipe left</span>
          <select data-track="settings.swipe-left" class="select-native" id="swipeLeftSelect"></select>
        </label>
        <h4 class="row-actions-sub">The ⋯ menu</h4>
        <ul class="row-actions-list" id="rowMenuList" aria-label="Actions in the row menu"></ul>
        <button data-track="row-actions.reset" type="button" class="button-ghost row-actions-reset" id="rowActionsReset">Reset to the defaults</button>
      </section>
      <section class="settings-sheet-section" id="timeCatsCard" data-sheet="timecats" data-surface="settings.time-categories" hidden>
        <div id="timeCatsHost" class="time-admin"></div>
      </section>
      <section class="settings-sheet-section" id="paletteCard" data-sheet="palette" data-surface="settings.palette" hidden>
        <p class="card-meta">One box for tasks and commands: switch tabs, filter, sync issues, jump to a task. <kbd>Ctrl</kbd>+<kbd>K</kbd> (<kbd aria-label="Command"><svg class="icon" aria-hidden="true"><use href="#i-command"></use></svg></kbd>+<kbd>K</kbd>) opens it anywhere; on a phone this is the way in.</p>
        <div class="card-actions">
          <button type="button" id="paletteOpen" data-track="palette.open" class="button-surface">
            <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-keyboard"></use></svg>
            Open command palette
          </button>
        </div>
      </section>
      <section class="settings-sheet-section" id="accessCard" data-sheet="access" data-surface="settings.access" hidden>
        <dl class="access-rows" id="accessRows"></dl>
        <p class="card-meta">Install: in iOS Safari, Share, then Add to Home Screen; in Android Chrome, Install app. Sign-in lasts 90 days per device; <code>scripts/gen_token.py --force</code> signs every device out.</p>
        <div class="access-actions">
          <button data-track="auth.sign-out" type="button" id="signOutBtn" class="button-ghost" hidden>Sign out on this device</button>
        </div>
      </section>
      <section class="settings-sheet-section" id="issuesCard" data-sheet="issues" data-surface="settings.issues" hidden>
        <p class="card-meta">Open issues assigned to you (<code>issues.provider</code> / <code>issues.owner</code>) become <em>coding</em> tasks in Inbox; a closed issue marks its task done (actor <code>sync</code>). Nothing is ever written back except <em>Create issue</em>.</p>
        <dl class="status-rows" id="issuesStatus" aria-live="polite">
          <div class="status-row"><dt>Provider</dt><dd id="statusIssues" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Last sync</dt><dd id="statusIssuesSync" class="muted">–</dd></div>
        </dl>
        <div class="card-actions">
          <button type="button" id="issuesSyncNow" data-track="issues.sync" class="button-surface" disabled>
            <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-refresh-cw"></use></svg>
            Sync now
          </button>
        </div>
      </section>
      <section class="settings-sheet-section" id="calendarCard" data-sheet="calendar" data-surface="settings.calendar" hidden>
        <p class="card-meta">Today shows your real calendar beside the task list, read-only, from a private ICS address in <code>calendar.ics_url</code> (Google's secret iCal address or Outlook's published calendar link). Nothing is ever written to the calendar. The copy is refreshed every few minutes; recurring events the app cannot expand are counted, never dropped.</p>
        <dl class="status-rows" id="calendarStatus" aria-live="polite">
          <div class="status-row"><dt>Calendar</dt><dd id="statusCalendar" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Source</dt><dd id="statusCalendarSource" class="muted">–</dd></div>
          <div class="status-row"><dt>Last fetched</dt><dd id="statusCalendarFetched" class="muted">–</dd></div>
        </dl>
        <div class="card-actions">
          <button type="button" id="calendarRefresh" data-track="calendar.refresh" class="button-surface" disabled>
            <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-refresh-cw"></use></svg>
            Refresh now
          </button>
        </div>
      </section>
      <section class="settings-sheet-section" id="captureCard" data-sheet="capture" data-surface="settings.capture" hidden>
        <p class="card-meta">Flag an email in Outlook and archive it as usual: the next pass over folder-explorer's flagged-mail list (<code>search.folder_explorer_url</code>) lands it in Inbox with the <code>.msg</code> attached. WhatsApp messages you mark in the radar arrive the same way. Clearing a flag later never removes the task — a captured task is yours.</p>
        <dl class="status-rows" id="captureStatus" aria-live="polite">
          <div class="status-row"><dt>Flagged emails</dt><dd id="statusCapture" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Last run</dt><dd id="statusCaptureRun" class="muted">–</dd></div>
        </dl>
        <div class="card-actions">
          <button type="button" id="captureRunNow" data-track="capture.run" class="button-surface" disabled>
            <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-refresh-cw"></use></svg>
            Check now
          </button>
        </div>
      </section>
      <section class="settings-sheet-section" id="archiveCard" data-sheet="archive" data-surface="settings.archive" hidden>
        <p class="card-meta">What is left in the Inbox once the flagged mail is a task: folder-explorer's archiver (<code>search.folder_explorer_url</code>) ranks the folders each mail looks like, the local model picks one, and everything above the threshold is filed. Whatever it was not sure about waits for you in the report below, where every run can also be undone.</p>
        <div class="archive-head">
          <div class="archive-actions">
            <button type="button" id="archiveRun" data-track="archive.run" class="button-surface archive-run" disabled>
              <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-archive"></use></svg>
              <span id="archiveRunLabel">Archive Inbox now</span>
            </button>
            <!-- The bound that makes a first run safe: trust in something that
                 moves your mail is built on an undo you have seen, so start
                 with one mail. Empty = the whole Inbox. -->
            <label class="archive-limit">
              <span class="archive-limit-text">First</span>
              <input id="archiveLimit" class="input-native archive-limit-input" type="number"
                     min="1" max="1000" step="1" inputmode="numeric" placeholder="all"
                     aria-label="How many mails at most this run (empty = all)">
              <span class="archive-limit-text">mails</span>
            </label>
            <span id="archiveProgress" class="archive-progress muted" aria-live="polite"></span>
          </div>
          <dl class="status-rows" id="archiveStatus" aria-live="polite">
            <div class="status-row"><dt>Archiver</dt><dd id="statusArchive" class="muted">Loading…</dd></div>
            <div class="status-row"><dt>Service</dt><dd id="statusArchiveUrl" class="muted">–</dd></div>
            <div class="status-row"><dt>Threshold</dt><dd id="statusArchiveThreshold" class="muted">–</dd></div>
            <div class="status-row"><dt>Last run</dt><dd id="statusArchiveRun" class="muted">–</dd></div>
            <div class="status-row"><dt id="archiveRecentLabel">Recent runs</dt><dd id="statusArchiveRecent" class="muted">–</dd></div>
          </dl>
        </div>
        <div class="pane-top archive-runbar">
          <label class="archive-runbar-label" for="archiveRunPick">Run</label>
          <select data-track="archive.run-pick" id="archiveRunPick" class="select-native archive-run-pick"></select>
          <button data-track="archive.accept-all" type="button" id="archiveAcceptAll" class="button-ghost" hidden>Accept all reviewed rows</button>
        </div>
        <div id="archiveHost" data-surface="archive.report" class="archive-host"></div>
      </section>
      <section class="settings-sheet-section" id="searchCard" data-sheet="search" data-surface="settings.search" hidden>
        <p class="card-meta">One box over four indexes: tasks (always), folders and emails through folder-explorer (<code>search.folder_explorer_url</code>) and the issue cache (<code>issues.provider</code>). <kbd>Ctrl</kbd>+<kbd>K</kbd> opens the command palette anywhere.</p>
        <dl class="status-rows" id="searchStatus" aria-live="polite">
          <div class="status-row"><dt>Tasks</dt><dd id="statusSearchTasks" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Folders</dt><dd id="statusSearchFolders" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Emails</dt><dd id="statusSearchEmails" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Issues</dt><dd id="statusSearchIssues" class="muted">Loading…</dd></div>
        </dl>
      </section>
      <section class="settings-sheet-section" id="folderCard" data-sheet="opener" data-surface="settings.opener" hidden>
        <p class="card-meta">Folder refs stay portable (<code>{onedrive}/…</code>, <code>{user}/…</code>, <code>{sharepoint:name}/…</code>); the chip is a <code>taskos://</code> link a tiny per-PC handler turns into an Explorer window on <em>that</em> PC. On a phone the chip shows the path to copy.</p>
        <dl class="status-rows" aria-live="polite">
          <div class="status-row"><dt>Opener</dt><dd id="statusOpener" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Folder search</dt><dd id="statusIndex" class="muted">Loading…</dd></div>
        </dl>
        <div class="opener-block">
          <div class="opener-block-head">
            <span class="opener-block-title">Install on a PC — paste into PowerShell, no admin (30 s)</span>
            <button data-track="opener.copy" type="button" id="openerCopy" class="button-surface">
              <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-copy"></use></svg> Copy command
            </button>
          </div>
          <pre class="opener-cmd" id="openerInstall">Loading…</pre>
          <details class="opener-more">
            <!-- Labels in plain words; the file's name and place are
                 the instruction under its heading, not the heading. -->
            <summary data-track="opener.advanced">Uninstall · folder paths for each PC</summary>
            <p class="card-meta">Uninstall (removes the URL scheme and the handler, keeps your folder paths file):</p>
            <pre class="opener-cmd" id="openerUninstall"></pre>
            <div class="opener-block-head">
              <span class="opener-block-title">Folder paths for each PC</span>
              <button data-track="opener.env-copy" type="button" id="openerEnvCopy" class="button-ghost">
                <svg class="icon" aria-hidden="true" focusable="false"><use href="#i-copy"></use></svg> Copy
              </button>
            </div>
            <p class="card-meta">This install's folder placeholders: save them as <code>%LOCALAPPDATA%\\task-os\\opener.env</code> on that PC and edit the paths there.</p>
            <pre class="opener-cmd" id="openerEnv"></pre>
          </details>
        </div>
      </section>
      <section class="settings-sheet-section" id="voiceCard" data-sheet="voice" data-surface="settings.voice" hidden>
        <p class="card-meta">Click the mic on the add dialog and talk; the words appear on the line as they are heard and settle when you click again. The recording is converted to 16 kHz WAV in the browser, posted to this app, and forwarded to the local LLM hub (<code>voice.transcribe_url</code>), which picks the fleet's transcription model — so the phone needs nothing but this app, and the audio never leaves the house. If the hub is down, the local whisper server (<code>voice.fallback_url</code>) takes over.</p>
        <dl class="status-rows" id="voiceStatus" aria-live="polite">
          <div class="status-row"><dt>Transcription</dt><dd id="statusVoice" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Endpoint</dt><dd id="statusVoiceUrl" class="muted">–</dd></div>
          <div class="status-row"><dt>Wording</dt><dd id="statusEnrich" class="muted">Loading…</dd></div>
        </dl>
      </section>
      <section class="settings-sheet-section" id="aiCard" data-sheet="ai" data-surface="settings.ai-triage" hidden>
        <p class="card-meta">Triage sends Inbox task text, the project tree and people to the local LLM hub in one bounded request. Suggestions stay staged until you accept or reject each one; nothing is auto-applied.</p>
        <dl class="status-rows" aria-live="polite">
          <div class="status-row"><dt>Local AI</dt><dd id="statusAI" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Model</dt><dd id="statusAIModel" class="muted">–</dd></div>
        </dl>
      </section>
      <section class="settings-sheet-section" id="yourNameCard" data-sheet="yourname" data-surface="settings.your-name" hidden></section><!-- body built by js/settings/yourname.js -->
      <section class="settings-sheet-section" id="installCard" data-sheet="install" data-surface="settings.database" hidden>
        <p class="card-meta">Config lives in <code>config/config.json</code> (gitignored; sample committed).</p>
      </section>
      <section class="settings-sheet-section" id="mirrorCard" data-sheet="mirror" data-surface="settings.mirror" hidden>
        <p class="card-meta">One <code>.md</code> per task in <code>mirror.dir</code>; edits there flow back with actor <code>md</code>. A dated <code>.db</code> copy lands in <code>mirror.backup_dir</code> daily at 03:00.</p>
        <dl class="status-rows" id="mirrorStatus" aria-live="polite">
          <div class="status-row"><dt>Mirror</dt><dd id="statusMirror" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Backup</dt><dd id="statusBackup" class="muted">Loading…</dd></div>
          <div class="status-row"><dt>Import conflicts</dt><dd id="statusMirrorEvents" class="muted">Loading…</dd></div>
        </dl>
        <div class="card-actions">
          <button data-track="mirror.clear-conflicts" type="button" id="mirrorEventsClear" class="button-ghost" hidden>Clear import conflicts</button>
        </div>
      </section>
    </div>
    <div class="detail-actions">
      <button data-track="settings-sheet.done" type="button" class="button-primary detail-save-btn settings-sheet-done">Done</button>
    </div>
  </div>`;

/** Fill the `#settingsSheet` shell with its card. */
export function fillSettingsSheet(dialog) {
  dialog.innerHTML = CARD_HTML;
}
