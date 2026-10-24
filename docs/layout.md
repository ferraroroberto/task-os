# Layout

```
launcher.py               entrypoint: `tray` (default) | `webapp`
tray.bat / webapp.bat     tray lifecycle (from the fleet template) / foreground dev server
tasks.bat                 the `tasks` CLI (→ python -m src.cli)
app/webapp/               FastAPI app: server.py (create_app, CachingStaticFiles, AuthMiddleware, JSON error envelope),
                          event_loop.py, manager.py (adopt-or-spawn uvicorn; cert --check → --ssl-* when a cert exists)
app/webapp/routers/       misc (shell, /healthz, /api/version, /opener/opener.{cmd,ps1}) · auth (/login, /api/login|logout, /api/team…) · tasks
                          (/api/tasks…, /api/activity) · people · views (/api/board, /api/today)
                          · mirror (/api/status — install status incl. https + auth + folders + opener, /api/mirror/export|import,
                          GET/DELETE /api/mirror/events, /api/backup) · folders (/api/resolve, /api/folders/search, /api/folders/reindex)
                          · issues (/api/issues/status|sync, GET/POST /api/tasks/{id}/issue)
                          · capture (/api/capture/email/run — one flagged-email pass now; 409 + the reason when the poller is off)
                          · voice (/api/transcribe — audio → a quick-add line, /api/enrich — the transcript → title + description)
                          · ai (/api/ai/triage, staged suggestion list + individual accept/reject)
                          · archive (/api/archive/run, /api/archive/runs[/{id}], per-item revert|move|accept|retry)
                          · search (/api/search — federated, /api/search/status)
                          · usage (/api/usage/events|summary — the vendored src/usage_log.py, see Usage log)
app/webapp/static/        the PWA: index.html, login.html, styles/ (fleet tokens in base.css, then one sheet per view or shared surface, linked in cascade order by both pages), app.js (state + routing), board.js,
                          today.js, drawer.js (the drawer's composer: open / close / refresh and the `ctx` its parts share; each part is a `js/drawer/<part>.js` taking `ctx` first), quickadd.js, search.js (the Search tab), time.js + time-dialogs.js · time-settings.js · time-format.js (the Time tab, #457),
                          rows.js (the one task row), filters.js (the one filter state + its sheet), journal.js (the done journal),
                          selection.js + bulkbar.js (the one selection + its bulk actions), actions.js (the one table of row actions + their undo), rowmenu.js (the row's ⋯ menu), keys.js (the one keymap), snooze.js (the one date picker),
                          confirm.js + modal.js (the editor-modal card shell and backdrop close), folderpick.js, dueinput.js, voice.js + voice-worklet.js (the mic → 16 kHz mono WAV),
                          archive.js (Settings → Email archiving: the batch run + its report, retry a refused move), settings.js (the Settings pane — the header gear, no tab, #281; inset groups + their sheets, #397),
                          calendar.js (the calendar lane beside Today),
                          recurrence.js (the recurrence vocabulary — the picker's mirror of src/dates.py),
                          palette.js (Ctrl+K), format.js, api.js, toast.js, collapsible.js (the runtime disclosure cards),
                          manifest, icons/, _vendored/
app/tray/                 tray.py + vendored single_instance.py / watchdog.py
src/                      schema.py (versioned migrations) · db.py (get_db, WAL) · tasks/ (domain rules + write hooks: schema · queries · mutations · related) · tasks_repo.py (re-export shim over it)
                          dates.py (natural dates, recurrence) · quick_add.py (one-line parser) · cli.py · config.py
                          hub_probe.py (the cached TCP reachability probe the AI, voice and enrich clients share) · voice.py (voice quick-add: the hub transcribes, local whisper only as fallback) · enrich.py (the
                          spoken sentence → title + description through the hub's light model; dates stay src/dates.py's)
                          clock.py (the one process clock, pinned by TASKOS_CLOCK) · runtime_data.py (resolves where the SQLite
                          file lives) · no_window.py (the one CREATE_NO_WINDOW flag for subprocess spawns)
                          mirror.py (markdown mirror: export / watcher import) · backup.py (dated .db copies, daily job)
                          auth.py (loopback owner · bearer / cookie gate · team sign-in) · team.py (team mode's picked name + avatars) · certs.py (cert pair, auto-renew hook)
                          issues/ (IssueProvider contract + the one CLI runner · github.py via gh · gitlab.py via glab api · fake.py for tests) · issue_sync.py (sync pass + scheduler) · poller.py (the one background-poller base both schedulers share)
                          placeholders.py (folder ref ↔ path) · folder_index.py (roots, index file, search) · opener.py
                          (install command / env template for Settings) · vendor/foldersearcher_core.py (verbatim)
                          search/ (federated search: base.py adapter contract · tasks / folders / emails / issues adapters ·
                          federated.py — concurrent, grouped, unconfigured = visible) · ai/ (Anthropic-compatible hub client +
                          staged Inbox triage validation/application · json_payload.py, the one reply-unwrapping helper) · email_capture.py (flagged mail → Inbox, read-only)
                          archive_batch.py (the archiver's batch CLI as a subprocess: plan → decide → apply → rescan)
                          archive_store.py (the run / item / correction rows — no subprocess, no service state)
                          archive_renumber.py (heals stored .msg paths from the archiver's renumber map)
                          archive_rank.py (the local model picks the folder among the candidates + the correction memory)
                          calendar_lane.py (the Today calendar lane: bounded ICS fetch, last good copy kept) · ics.py (just enough iCalendar
                          to say what is on today) · pooled_http.py (keep-alive outbound HTTP client, vendored verbatim)
                          logger.py · static_versioning.py
opener/                   the per-PC folder opener: opener.ps1 (the registered launcher) · opener.cmd (the handler) · install.txt (one-line PowerShell
                          install / uninstall) · install_opener.py (same via winreg) · README.md
scripts/                  verify-before-ship.ps1, classify_e2e.py, shot_determinism.py, gen_icons.py, import_notion.py (+ .bat), import_time_prototype.py (#457),
                          gen_tailscale_cert.py (copy-to-adapt from the scaffold, not vendor-verbatim), gen_token.py, set_password.py, set_team_password.py,
                          apply_renumber_map.py (heal stored .msg paths from an archiver renumber map)
tests/                    unit (hermetic) + fixtures/seed.py (synthetic dataset) + fixtures/emails_fixture.py (a tiny synthetic
                          email-archiver index) + e2e/ (Playwright, one story test per step; its tests tag every surface they open with
                          the vendored `surface(page, "<tab>.<surface>")` hook, a no-op unless `/design-review measure task-os --e2e` arms it)
.claude/skills/           verify-task-os: the project's launch-and-drive skill (SKILL.md + a features/ map per view), generated by the
                          scaffold's gen_verify_skill.py from `.fleet.toml [verify]` and the e2e `surface()` calls; the rest of .claude/ is ignored
docs/                     validation.md (the story index + phase gates) + validation/ (each story's and UX round's full
                          write-up) + screenshots/ + architecture.mmd
config/                   config.sample.json (committed) → config.json (yours, gitignored)
brand/ assets/            Lucide list-checks master → favicon / touch icons / tray .ico
data/                     tasks.db, folder_index.txt, logs, avatars, backups — gitignored, never committed
webapp/                   certificates/{cert,key}.pem (the Tailscale leaf), watchdog.log, webapp.log (the tray-spawned webapp's stdout/stderr — a boot traceback lands here) — gitignored
```

## Stylesheets

One stylesheet per view or shared surface under `app/webapp/static/styles/`, none over 1,000 lines (the structure ratchet's file cap, pinned by `tests/test_smoke.py`). `base.css` holds the tokens, the base rules, the layout and the cards; every other sheet opens with one comment saying what it owns. `index.html` and `login.html` link the same set in the same order, because rule order is the cascade: a later sheet overrides an earlier one, so a rule moves between sheets only with its order kept. A new view adds a sheet and a `<link>` in both pages (the content-hash `?v=` stamp is added at serve time).

## Structure ratchet

The tree above is held to the fleet's `webapp-tray` shape by the structure ratchet (`scripts/structure_ratchet.py`, vendored byte-for-byte from the scaffold, never edited here; the gate runs it through `scripts/structure_ratchet_gate.py`, which fails exit 3 as NOT CONFIRMED). It checks five things:

- **File size**: a file over 1,000 lines does not grow; code, stylesheets, markup and tests alike.
- **Function length**: a Python or JS function over 100 lines does not grow. A nested function counts inside its outer one, so a view's `mount<View>()` closure is held as a whole.
- **Flat directory**: a directory past 40 modules (`.py`, `.js`, `.mjs`, `.css`; `__init__.py` aside) takes no new module.
- **Layer contract**: `src/` never imports `app/`; a helper both need lives in `src/`.
- **Root layout**: the tracked root folders match the shape plus the declared extras below. This one is not baselined.

Every offender that existed on adoption is recorded in `.structure-ratchet-baseline.json` at its size that day, with nothing excluded. A baselined entry may shrink but never grow, and a new offender fails by name. After splitting or shortening one, lower the baseline with `scripts/structure_ratchet.py --update-baseline`; only `--allow-additions` raises it, and that shows in review.

### Root folders

| Folder | Why it is there |
|---|---|
| `app/` · `src/` · `tests/` · `docs/` | the shape's required folders: the UI and tray, the logic, the suites, the reference |
| `scripts/` · `config/` · `assets/` · `brand/` | allowed by the shape: ops CLIs, committed config and its samples, static files the app ships, the icon masters |
| `opener/` | the declared exception (`extra_roots` in `.fleet.toml`): the per-PC folder opener, a native install helper (PowerShell, a command handler, an installer) that a user runs on another machine, so it belongs to neither the app nor the logic |

`data/` and `webapp/` are gitignored runtime output and never tracked, so the check does not see them.

### Where new code goes

- A new endpoint: `app/webapp/routers/<concern>.py`, parsing the request and returning the response; the rule lives in `src/` (domain rules in `src/tasks/` — a read in `queries.py`, a task write in `mutations.py`, a comment / link / issue-ref / person write in `related.py`; callers import through the `src/tasks_repo.py` shim — time-tracker rules in `src/time_repo.py`).
- A new view: its own stylesheet under `app/webapp/static/styles/` linked from both `index.html` and `login.html`, and its own script beside the other views' scripts. Never a new block in `base.css` or another view's sheet.
- A new logic module: `src/` is flat past the cap, so a new module goes in a domain subpackage (`src/<domain>/`, as `src/search/`, `src/ai/` and `src/issues/` already are), not beside the flat ones.
- A new test: `tests/` is flat past the cap and takes no new module, so a new file goes in a subfolder named for its subject (`tests/gates/` for the gate wrappers' tests, `tests/e2e/` for stories), with an `__init__.py`.
- A new ops script: `scripts/`; a helper the app imports belongs in `src/`.

### Baselined offenders and their way out

The baseline holds 12 files over 1,000 lines (the app and archive scripts, `index.html`, four `src/` modules, three e2e files and two unit test files), 46 functions over 100 lines (the view-mount closures `mountArchive` and `mountTime` the longest) and the flat `tests/` directory. Splitting each is its own change; the drawer is the one already split.
