# Setup and migration

How to run task-os on another computer from the same repository, with no fork, and how to move an existing install's state across. The code is identical on every machine; only the machine-local files below and Settings → Available features differ.

The lists here come from the code's own read and write paths (`src/config.py`, `src/db.py`, `src/runtime_data.py`, `src/logger.py`, `src/certs.py`, `src/password.py`, `src/team.py`, `src/mirror.py`, `src/backup.py`, `src/opener.py`, `scripts/import_notion.py`) and the gitignore rules, not from memory. If a path moves, this page moves with it.

## Set up a new machine

**Prerequisites**

- Windows, Python 3.14 (`py -m venv` must work) and `git`.
- Optional, by feature: the GitHub CLI `gh` (logged in) or `glab` for issue sync; Tailscale for phone access over HTTPS; a reachable local model hub for voice and AI triage; folder-explorer for folder and email search, flagged-mail capture and Inbox archiving. A feature whose dependency is missing is switched off (below), not worked around.
- Node.js only if you run the verification gate.

**Install**

```powershell
git clone https://github.com/ferraroroberto/task-os <checkout>
cd <checkout>
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config\config.sample.json config\config.json
```

Edit `config\config.json` **before the first run** (the keys are in [Configuration](configuration.md)). The sample carries the author's values, so each of these needs a decision on this machine:

- `port`, `your_name`.
- `placeholders` (what `{onedrive}` and friends expand to here), `mirror.dir` and `mirror.backup_dir`. The sample points them at a synced folder of the author's. The mirror and the daily backup switch on as soon as the folder's parent exists, so a folder that exists here and belongs to another install is written into on the first start.
- `issues.owner`. The sample names the author's account, and Issue sync runs its first pass seconds after the first start: with `gh` or `glab` logged in, it turns the open issues it can see for that owner into tasks. Set your own account or group, or switch Issue sync off (below).
- Any service address (`search.folder_explorer_url`, `voice`, `enrich`, `ai.base_url`, `calendar.ics_url`) that is not on this machine.

Without a `config.json` the app boots on the committed sample with the mirror and backup off, and Settings cannot save anything.

**Where the database goes.** The database defaults to `C:\sqlite\task-os\tasks.db` (see the table below for the full order), a per-machine folder, not the checkout. Two checkouts on one machine therefore open the same database. For a trial clone beside a running install, set `TASK_OS_DATA_DIR` (a folder) or `TASKOS_DB_PATH` (a file) for that clone's process; with `TASKOS_DB_PATH` set, the mirror and backup only run in the database's own folder.

**Switch off what cannot run here, before the first start.** Nothing is detected automatically: a block is on until this machine's `config.json` says otherwise, and its background work (Issue sync, flagged-mail capture) starts within seconds of the first run. To keep a block from ever starting, add a `features` object to `config\config.json` now:

```json
"features": { "email": false, "ai": false, "calendar": false }
```

The keys are the blocks in [Available features](#available-features); only an explicit `false` switches one off. After the first run the same switches are in Settings → Available features, and the choice is made once per machine.

**First run**

```powershell
tray.bat                      # tray icon owning the webapp on the configured port
```

Left-click the tray icon to open the app. A fresh install opens on an empty Today. `webapp.bat` runs the same server in the foreground instead. On a machine without the other fleet repos, `tray.bat` prints a note and starts the tray on its own; only `tray.bat --restart` needs the shared helper (see Update).

**Optional, per machine**

- Phone access: `scripts\gen_tailscale_cert.py`, `scripts\gen_token.py`, `python -m src.password set` — see [Phone access, sign-in and team mode](access.md).
- The folder opener for `taskos://` links: the install command is in Settings → Folder opener; it registers a per-user handler and an `opener.env` of this machine's placeholders.
- The `tasks` CLI: put `tasks.bat` on `PATH`.

**Update**

```powershell
git pull
tray.bat --restart            # reclaims the port, starts fresh, checks the served build against HEAD
```

`GET /api/version` reports the served `git_sha`; it must equal `git rev-parse --short HEAD` after a restart. A schema change migrates itself at startup.

`tray.bat --restart` needs the shared tray helper that the author's other repos install under `%USERPROFILE%\.claude\tray`; without it the command stops with an error rather than start over a stale build. On a machine without it, choose Quit from the tray menu, run `git pull`, then `tray.bat`, and check `/api/version` the same way.

## Migrate from an existing machine

Stop the app on the old machine first (tray menu → Quit), so the database is checkpointed and no file is mid-write. Then copy, relative to the old checkout unless a path says otherwise.

| What | Where it lives | Needed? |
| --- | --- | --- |
| Settings | `config/config.json` | Required. Holds the machine-local choices, including the secrets below. Copy it, then edit it (next section). |
| Sign-in password hash | `config/app_password.json` | Optional. Without it, set a password again with `python -m src.password set`. Never commit it. |
| The database | `tasks.db` in the runtime-data folder: `TASKOS_DB_PATH` if set, else `<TASK_OS_DATA_DIR>`, else `<FLEET_DATA_ROOT>\task-os`, else `C:\sqlite\task-os` on Windows | Required. This is all your tasks, comments and activity. Copy `tasks.db` alone: the `-wal` and `-shm` files next to it are empty after a clean stop. `tasks backup` makes a consistent copy while the app runs. |
| The usage log | `usage.sqlite3` beside the database | Optional. Local view and tap counts only. |
| Dated database copies | the folder `mirror.backup_dir` names | Optional. Already on a synced folder, they are not copied; the new machine points at the same folder. |
| The markdown mirror | the folder `mirror.dir` names | Do not copy. It is rebuilt from the database on the first start, and a folder another install wrote into is treated as foreign edits. Point the new machine's `mirror.dir` at the same synced folder, or at an empty one. |
| Team avatars | `data/avatars/` | Optional, team mode only. |
| HTTPS certificate | `webapp/certificates/{cert,key}.pem` | Do not copy. It is issued for one machine's tailnet name; run `scripts\gen_tailscale_cert.py` on the new one. |
| Folder opener | `%LOCALAPPDATA%` task-os folder and a per-user registry entry | Do not copy. Reinstall it from Settings → Folder opener; it is per machine. |
| Notion import token | `.env` keys `NOTION_API_TOKEN` and `NOTION_TASKS_DB_ID` | Only if you re-run the one-shot Notion import. Create `.env` by hand on the new machine; its values never travel through the repository. |
| SharePoint column map | `config/sharepoint-mapping.json` | Only if you re-run the one-shot SharePoint import. |

**Rebuildable, never copied:** `.venv/` (recreate it), `data/logs/` (the webapp's and the tray's rotating logs), `webapp/watchdog.log`, `webapp/webapp.log`, and everything under `mirror/` in the checkout.

**Edit after copying `config/config.json`:**

- `port`, if the new machine already uses the old one.
- `placeholders` and `web_roots`: the paths that `{onedrive}` and the other tokens expand to on this machine.
- `mirror.dir` and `mirror.backup_dir`: this machine's synced folders (the parent folder must exist).
- `search.folder_explorer_url`, `voice`, `enrich`, `ai.base_url`, `calendar.ics_url`: hosts and addresses as they are reached from here.
- `issues.provider`, `issues.owner`, `issues.host`: the forge this machine's CLI is logged in to.
- `auth` and `alerts`: the secrets. Keep them only if the same people sign in; otherwise rotate with `scripts\gen_token.py --force` and sign every device in again.
- `features`: the switched-off blocks of the old machine. Review them for this one.

**Check that the copy worked**

1. `tray.bat` starts, and `GET /api/version` shows the current `git_sha` and a `schema_version`.
2. Today and Board show your tasks; the task count matches the old machine.
3. Settings: the mirror and backup rows say `on` (or `off` with the reason you expect), and every block in Available features is as you intended.
4. `tasks mirror status` and `tasks issues status` report what Settings reports.
5. On a phone, the Settings → Phone access row reads `https` and signed in.

## Available features

Settings → Available features lists the coarse blocks of the app that sit on one source or primitive. Every block is on by default except one opt-in block (below). Switching one off hides its screens, stops its background work and polling, and makes its backend routes answer `409 feature_off`; switching it on restores all three with no restart. A block that is on but has nothing to run on here (no address configured, the CLI missing) says why on its row instead of failing silently.

| Block | Covers |
| --- | --- |
| Time tracker | The Time tab and its Settings rows; `/api/time/*`. |
| Calendar lane | The calendar beside Today and its refresh; no feed is fetched. |
| Issue sync | The forge sync poller, the drawer's issue panel, the issues group of Search; the Sync commands. |
| Email and folders | Everything that reads through folder-explorer: the folders and emails groups of Search, the folder picker's search, the flagged-mail capture poller and Inbox archiving. |
| Local AI | Everything that reads through the local model hub: voice quick-add, spoken-line enrichment and AI Inbox triage. |
| Mirror and backups | The markdown mirror and its watcher, and the daily database copy. |
| Publish host address | **Off by default.** Writes this PC's address to a shared-folder file at startup; see below. It owns no screen and no route. |

The state is the `features` block of `config/config.json`, one `false` per switched-off block (and `true` for the opt-in block when it is on), so it is machine-local, gitignored and survives a restart. It is written by Settings only: a hand edit is read at startup. The app writes it only to a real `config.json`, never to the committed sample.

### Publishing the host address

Another computer can reach this install through a small launcher kept in a shared folder: the launcher reads the host's address from a text file next to it. The host's address changes from time to time, so the **Publish host address** switch keeps that file current. It only writes the file: no port is opened, no login or firewall rule changes, and the password and bearer gate stays the only way in.

1. Set `network_sharing.host_ip_file` in `config\config.json` to the file's path (a UNC path, or a drive letter mapped to the share).
2. Turn the switch on in Settings → Available features. It publishes once at once; after that, at every start, through both the tray and `webapp.bat`.

The row shows the last outcome: *Published* (the address was written), *Unchanged* (the file already held it, and was left alone), *Unavailable* with the reason (a blank or unusable path, a file that is not on a share, an ambiguous route, a server that is this computer) or *Failed* with the reason (the share could not be read or written). Turning the switch off stops future writes and leaves the file as it is. There is no watcher: an address that changes while the app is running is published at the next start. A slow or missing share never delays startup: the write runs on its own thread.
