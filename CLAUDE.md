# Project Instructions — task-os

Claude Code reads this file as project memory; other agents reach it via the `AGENTS.md` pointer.

> Universal dev-workflow directives (plan mode, asking, editing, git, branch/PR, docs) live once in `~/.claude/CLAUDE.md` and are not restated here. Fleet-wide *shape* conventions for a FastAPI + static PWA + tray app (visual identity, vendored components, cache-busting, event-loop pinning, `CREATE_NO_WINDOW`, one `get_db`, tray self-heal, e2e routing) are owned by `project-scaffolding`'s `CLAUDE.md` — this file carries only what is specific to **this** repo. Read `README.md` first for layout and usage.

## This repository

Personal open-source task manager: FastAPI + SQLite + vanilla-JS PWA + pystray tray, PC-first, port **8448**. See `README.md` for setup, layout, config and the step roadmap (issue #1). Every build step is a GitHub issue ("Step N/13") whose user story is proven on screen before it closes.

**Project specifics:**

- **Stack is fixed:** Python 3.14 (`py -m venv .venv`; invoke `& .\.venv\Scripts\python.exe`, never activate), FastAPI + uvicorn, stdlib `sqlite3` (WAL, FTS5, one `get_db()` `Depends` — zero per-handler `sqlite3.connect`), vanilla JS (no bundler/framework), pystray. No Docker. Windows-first.
- **Public repo, personal project.** No employer, workplace, colleague names, internal paths or ID schemes anywhere — code, docs, issues, commits, screenshots, fixtures. Generic wording only ("a second site", "a shared install for a small team", "another machine").
- **Personal data never gets committed.** `data/` (SQLite, avatars, backups, logs), `config/*.json` (real), `.env`, `mirror/`, `webapp/` are gitignored; committed twins are `config/*.sample.json`. Screenshots and e2e fixtures use a **synthetic seed** only, never a real import. Run `git status` before every commit and check nothing private is staged.
- **Visual identity = the fleet's.** Tokens from `~/.claude/design.md` + `design.dark.md` as CSS custom properties (`:root` light, `[data-theme="dark"]` dark, pre-paint stamp in `index.html`, key `task-os.theme`). Components vendored byte-for-byte from `project-scaffolding/app/webapp/static/_vendored/` and recorded in `.fleet.toml [vendored]` — never edit a vendored file per-app; `/propagate-vendored` re-vendors. Lucide sprite inline in `index.html` (per-app trim; glyphs missing from the scaffold sprite are pasted verbatim from lucide-static). **No emoji as UI icons.** The one deliberate deviation: **PC-first, full width** — `main.app` has no 772px cap on desktop (all Board columns side by side, Table full width, drawer as a right-hand panel); the phone is the second, adaptive rendering (bottom pill from the vendored nav).
- **Every step ships its user story with proof** (`docs/validation.md`): (a) hermetic unit tests + **one** Playwright e2e test `tests/e2e/test_story_NN_<slug>.py` walking the story against a disposable instance and saving numbered screenshots to `docs/screenshots/story-NN-<slug>-<n>-{desktop,phone}.png` (1440×900 desktop first, 390×844 phone where relevant, light and dark); (b) a headed / real walk by the agent of the same story; (c) the `docs/validation.md` entry — story · steps · expected · screenshot links · test name · result · date. `[x]` in a PR test plan means "walked and seen". Anything not walked is written **not verified**, never as passed. Keep the e2e suite **under 15 tests total** — one story test per step; delete before adding.
- **Verification — the pre-ship gate is `& .\scripts\verify-before-ship.ps1`** (byte-compile → ruff → pytest → routed e2e). The e2e phase boots its **own disposable webapp** on a free port with `TASKOS_DB_PATH` → temp DB and `TASKOS_CONFIG_PATH` → the sample config; it never touches the live `:8448`. `TASKOS_E2E_LIVE=1` is the one loudly-named opt-in for read-only assertions against the live instance (never a kill). Browser routing is diff-proportionate via `scripts/classify_e2e.py` + `.fleet.toml [e2e]` (static-asset diff → Chromium smoke; backend/docs-only → no browser suite; anything UI/behavioural or unmatched → full). No CI workflow yet — the local gate is the contract.
- **Restart recipe (long-lived process, no hot-reload):** after the gate passes, `tray.bat --restart` — the orphan-proof reclaim-then-start owned by the shared `%USERPROFILE%\.claude\tray\tray_lifecycle.ps1` (fleet-config): kills the tray subtree, reclaims `:8448` by PID scoped to this repo's `.venv`, starts fresh, and fails loud unless the served build matches. Never hand-roll the kill. **The build-identity check is `GET http://127.0.0.1:8448/api/version` → `git_sha == git rev-parse --short HEAD`** (a `/healthz` 200 passes on a stale process; a matching SHA does not) — poll it bounded (≤30 s), report the build line, never hand off "done" over a stale process. Only one long-lived component (the webapp under the tray); nothing is excluded from the restart.
- **Config & secrets:** `config/config.json` (gitignored, sample committed) — `site`, `port`, `issues`, `placeholders`, `mirror`, `search`, `team`. `.env` only for the Notion import token. `src/config.py` falls back to the sample when the real file is missing so a fresh clone boots.
- **Schema versioning:** `src/db.py` stamps `settings.schema_version`; later steps add migrations keyed on it. `TASKOS_DB_PATH` overrides the DB path (tests).

## UX surface
*The design-conformance gate the `/issue-{start,finish,yolo}` skills read (convention: `project-scaffolding#83`). Live, parseable block — the product is the FastAPI + static PWA under `app/webapp/`.*

- design spec applies: yes
- paths:
  - app/webapp/static/**/*.css
  - app/webapp/static/**/*.{js,html}
- key views:
  - /          (Board · Table · Tree · Today · Search · Settings tabs)

## Internal architecture

No `docs/architecture.mmd` yet — the shape is small enough that `README.md`'s layout block is the map. Add the diagram in the same PR as the first material structural change (Step 2's schema/API/CLI split is the natural moment) and keep it current after that.
