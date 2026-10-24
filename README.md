# task-os

A personal, open-source task manager: one master list for everything, self-hosted on your own PC. Nested tasks that become projects by having children, comments with clickable links, an activity log, local-folder links that resolve per machine, GitHub/GitLab issues as first-class tasks, and one search box over tasks, folders, emails and issues. PC-first, with width following the shape of each view (the two-dimensional views span the window, Search and Settings keep the 772px measure); the phone gets the same views as an installable PWA over Tailscale; an LLM reaches it through a CLI, a JSON API and a markdown mirror.

Built step by step: each step is a GitHub issue with a user story that is proven on screen before it closes ([`docs/validation.md`](docs/validation.md)); the step list is the roadmap issue. Internal map: [`docs/architecture.mmd`](docs/architecture.mmd).

## Stack

Python 3.14 · FastAPI + uvicorn · stdlib `sqlite3` (WAL, FTS5) · vanilla-JS static PWA (no bundler, no framework) · pystray tray · Windows-first, no Docker. Visual identity and UI components come from the fleet design system (`project-scaffolding`'s vendored components, byte-for-byte — see `.fleet.toml` `[vendored]`).

## Quick start (Windows)

```powershell
git clone https://github.com/ferraroroberto/task-os E:\automation\task-os
cd E:\automation\task-os
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config\config.sample.json config\config.json      # then edit paths for this machine

tray.bat            # tray icon → owns the webapp on :8448 (HTTPS once a cert exists — see docs/access.md)
```

Left-click the tray icon (or **Open task-os**) to open the app; **Copy URL** puts the same address on the clipboard for the phone. `tray.bat` is idempotent — a second run is a no-op while a tray is up. Without the tray: `webapp.bat` runs uvicorn in the foreground (a thin wrapper over `launcher.py webapp`, so it serves on the configured `port`, not a hardcoded one).

From a terminal, `tasks.bat` (put the repo on `PATH` or alias it) is the CLI — it works whether or not the app is running:

```powershell
tasks add "Renew passport" --due fri
tasks add "Book appointment" --parent 1
tasks comment 2 "called the office"
tasks tree
tasks due 2 2026-09-01
tasks show 2            # activity log shows due: ∅ → 2026-09-01
tasks triage            # stage one AI suggestion per Inbox task; y/n/q reviews them
tasks mirror status     # markdown mirror + backup: enabled? where? last export / import
tasks issues sync       # my open GitHub issues → coding tasks in To do; closed ones → done
tasks folders search kitchen   # the folder index (search.folder_roots) — refs you can paste on a task
```

Playwright browsers for the e2e suite: `& .\.venv\Scripts\python.exe -m playwright install chromium webkit` (once).

## Features

One line each; the full reference for a feature is the page it links to.

| Feature | In short |
| --- | --- |
| [Views](docs/views.md) | Today, Board, Time, Search and Settings: the task row, filters, the drawer, quick-add; PC-first, with the phone as an adaptive second rendering |
| [Task workflow](docs/task-workflow.md) | Start dates and snooze, blocked-by dependencies, the read-only calendar lane beside Today, keyboard triage |
| [Inbox](docs/inbox.md) | New arrivals land in Inbox by themselves (flagged emails, marked messages); one-press AI triage through the local LLM hub |
| [Archive the Inbox](docs/inbox-archive.md) | Settings → Email archiving files the whole Outlook Inbox through email-archiver and reports each row for review |
| [Voice quick-add](docs/voice.md) | Dictate a task from the add dialog; transcription goes browser → task-os → local LLM hub, nothing leaves the house |
| [Time tracking](docs/time-tracking.md) | The Time tab: a per-person timer and a household comparison of who spends time on what |
| [Issues as tasks](docs/issues-as-tasks.md) | GitHub/GitLab issues assigned to you sync in as coding tasks; the sync is read-mostly |
| [Folders](docs/folders.md) | Folder links stored as portable refs and opened on any PC by the `taskos://` opener |
| [AI conversation links](docs/ai-conversation-links.md) | A pasted AI-session URL becomes a bot chip on the row; an agent attaches one with `tasks link` |
| [Search](docs/search.md) | One box over tasks, folders, emails and issues, grouped by kind |
| [Markdown mirror and backups](docs/mirror-and-backups.md) | One `.md` file per task for editors and LLMs, a nightly database backup, the usage log |
| [CLI](docs/cli.md) | `tasks.bat`: the whole app from a terminal, over HTTP when the app is up and directly on the database when it is not |
| [API](docs/api.md) | The JSON API under `/api/`, one error envelope everywhere |
| [Phone access, sign-in and team mode](docs/access.md) | Tailscale HTTPS, token / password sign-in, the installable PWA, and a shared install for a small team |
| [Importing from Notion](docs/import-notion.md) | The one-shot, idempotent Notion importer |

## Reference

| Page | Holds |
| --- | --- |
| [Layout](docs/layout.md) | The repository tree, the structure ratchet and where new code goes |
| [Configuration](docs/configuration.md) | Every key of `config/config.json` |
| [Data model](docs/data-model.md) | The SQLite tables, the schema version and the rules the repo layer enforces |
| [Validation](docs/validation.md) | Each step's user story, its steps, screenshots and result |
| [Architecture](docs/architecture.mmd) | Mermaid map of clients, routes, repo layer and tables |

## Fixture data

`tests/fixtures/seed.py` is the **only** dataset allowed in tests, e2e runs and screenshots (the repo is public): a deterministic synthetic set — four projects nested to depth 3, ~40 tasks, three people, comments with web / folder / issue links, activity, recurring, done and cancelled tasks, one `coding` task. `python -m tests.fixtures.seed --db E:/tmp/tasks.db --reset [--anchor YYYY-MM-DD]` seeds a file; point `TASKOS_DB_PATH` at it (or `TASKOS_URL` at a disposable instance) to drive the CLI or the app against it. Never a real import.

## Verify, restart, prove

```powershell
& .\scripts\verify-before-ship.ps1     # byte-compile → ruff → static ratchet (needs Node) → docs ratchet → structure ratchet → instruction ratchet → pytest → routed e2e (disposable instance) → gallery baseline
tray.bat --restart                     # orphan-proof reclaim-then-start; verifies /api/version git_sha == HEAD
```

The e2e suite boots its own disposable webapp on a free port with a temp DB; it never touches the live `:8448`. `TASKOS_E2E_LIVE=1` runs it read-only against the live instance instead. Screenshots the story tests save under `docs/screenshots/` are the on-screen proof linked from `docs/validation.md` — captured through the conftest's `shot()`, on a frozen clock, so two runs of one commit produce the same files and a run months from now still produces the ones in the repo. `python -m scripts.shot_determinism` runs the suite twice and proves the capture is stable; `--check-tree` compares what a run rewrote against the committed gallery and restores it (the gate's last stage). `docs/validation.md` states the five capture rules a new story inherits.

### Project skill: `verify-task-os`

`.claude/skills/verify-task-os/` (scope: this repository) is the committed launch-and-drive skill: how to boot a disposable instance from an empty data directory, a read-only Doctor, one pytest node per feature, evidence rules and cleanup, plus `features/` with one file per view. Claude Code loads it natively from that path. For Codex or Pi, link it once per checkout (ignored, never committed): `New-Item -ItemType Junction -Path .agents\skills\verify-task-os -Target .claude\skills\verify-task-os` (after `New-Item -ItemType Directory -Force .agents\skills`).

The skill is generated, not hand-written: run project-scaffolding's `scripts/gen_verify_skill.py --repo <this checkout>` after a `surface()` call, a `[[design.review.extra_steps]]` entry or `.fleet.toml [verify]` changes, and `--check` (add `--live-url` and `--junit` for the live half) reports `STATIC` / `MAINTAIN` `clean | changed | blocked`. Only the `## Gotchas` sections are hand-written.

## Roadmap

The roadmap issue in this repo lists the 13 steps (home v1 → integrations → a second site with a small team). Each step closes with its automated story test, on-screen screenshots and a `docs/validation.md` entry.
