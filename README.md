# task-os

A personal, open-source task manager: one master list for everything, self-hosted on your own PC. Nested tasks that become projects by having children, comments with clickable links, an activity log, local-folder links that resolve per machine, GitHub/GitLab issues as first-class tasks, and one search box over tasks, folders, emails and issues. PC-first and full-width; the phone gets the same views as an installable PWA over Tailscale; an LLM reaches it through a CLI, a JSON API and a markdown mirror.

Built step by step — each step is a GitHub issue with a user story that is proven on screen before it closes ([`docs/validation.md`](docs/validation.md)). This is **Step 1**: the shell.

## Stack

Python 3.14 · FastAPI + uvicorn · stdlib `sqlite3` (WAL, FTS5) · vanilla-JS static PWA (no bundler, no framework) · pystray tray · Windows-first, no Docker. Visual identity and UI components come from the fleet design system (`project-scaffolding`'s vendored components, byte-for-byte — see `.fleet.toml` `[vendored]`).

## Quick start (Windows)

```powershell
git clone https://github.com/ferraroroberto/task-os E:\automation\task-os
cd E:\automation\task-os
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config\config.sample.json config\config.json      # then edit paths for this machine

tray.bat            # tray icon → owns the webapp on http://127.0.0.1:8448
```

Left-click the tray icon (or **Open task-os**) to open the app. `tray.bat` is idempotent — a second run is a no-op while a tray is up. Without the tray: `webapp.bat` runs uvicorn in the foreground.

Playwright browsers for the e2e suite: `& .\.venv\Scripts\python.exe -m playwright install chromium webkit` (once).

## Layout

```
launcher.py               entrypoint: `tray` (default) | `webapp`
tray.bat / webapp.bat     tray lifecycle (from the fleet template) / foreground dev server
app/webapp/               FastAPI app: server.py (create_app, CachingStaticFiles), routers/, event_loop.py, manager.py
app/webapp/static/        the PWA: index.html, styles.css (fleet tokens), app.js, manifest, icons/, _vendored/
app/tray/                 tray.py + vendored single_instance.py / watchdog.py
src/                      config.py, db.py (get_db, WAL), logger.py, static_versioning.py, no_window.py
scripts/                  verify-before-ship.ps1, classify_e2e.py, gen_icons.py
tests/                    unit (hermetic) + e2e/ (Playwright, one story test per step)
docs/                     validation.md (the story record) + screenshots/
config/                   config.sample.json (committed) → config.json (yours, gitignored)
brand/ assets/            Lucide list-checks master → favicon / touch icons / tray .ico
data/                     tasks.db, logs, avatars, backups — gitignored, never committed
```

## Configuration — `config/config.json`

| Key | Meaning |
| --- | --- |
| `site` | `home` or a second site name — selects nothing yet; later steps key providers on it |
| `port` | webapp port (default **8448**) |
| `issues` | `provider` (`github`/`gitlab`), `owner`, `assignee`, `sync_minutes` — Step 8 |
| `placeholders` | `{onedrive}`, `{user}`, … expanded in folder refs per machine — Step 9 |
| `mirror` | markdown mirror dir + nightly backup dir — Step 6 |
| `search` | folder roots + email index path for federated search — Step 10 |
| `team` | shared install for a small team: `enabled`, `people` — Step 12 |

Secrets (a Notion token for the one-shot import) go in `.env`, never in config. `TASKOS_CONFIG_PATH` / `TASKOS_DB_PATH` env vars override the config/db location (the test harness uses them for isolation).

## Endpoints (Step 1)

`GET /` shell · `GET /healthz` liveness · `GET /api/version` `{git_sha, built_at, asset_hash, schema_version}` — the build-identity contract the restart recipe checks.

## Verify, restart, prove

```powershell
& .\scripts\verify-before-ship.ps1     # byte-compile → ruff → pytest → routed e2e (disposable instance)
tray.bat --restart                     # orphan-proof reclaim-then-start; verifies /api/version git_sha == HEAD
```

The e2e suite boots its own disposable webapp on a free port with a temp DB; it never touches the live `:8448`. `TASKOS_E2E_LIVE=1` runs it read-only against the live instance instead. Screenshots the story tests save under `docs/screenshots/` are the on-screen proof linked from `docs/validation.md`.

## Phone / PWA

Arrives with Step 7: Tailscale HTTPS certificate (`gen_tailscale_cert.py`), Add-to-Home-Screen install, phone-tuned Board carousel. Until then the app is plain HTTP on the LAN/loopback; the manifest + icons already ship.

## Roadmap

Issue #1 in this repo lists the 13 steps (home v1 → integrations → a second site with a small team). Each step closes with its automated story test, on-screen screenshots and a `docs/validation.md` entry.
