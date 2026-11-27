# Install, update and move task-os

task-os moves to another Windows PC the way any app in the toolbox does: clone it and run one `setup.bat`. An update is a pull plus a restart. Neither ever resets or overwrites what a PC has configured, so `setup.bat` is safe to run again at any time.

What `setup.bat` runs is the toolbox's shared installer, `src/installer.py`, driven by the `[install]` table in `.fleet.toml`. The parts that are task-os's own (the config top-up, the folder opener, the sign-in start and the personal checklist items) are the commands in `src/install/`.

## What you need

- Windows 10 or 11, **Git**, and **Python 3.14** (python.org, with the `py` launcher). `setup.bat` needs Python 3.11 or newer to start and builds the `.venv` with the interpreter it finds, so install 3.14 first.
- Optional, by feature: the GitHub CLI `gh` (logged in) or `glab` for issue sync; Tailscale for phone access over HTTPS; a reachable local model hub for voice and AI triage; folder-explorer for folder and email search and Inbox archiving. Node.js and the Playwright browsers are only for the developer gate. Which feature needs what: [Setup and migration](setup-and-migration.md#set-up-a-new-machine).

## Fresh PC

```powershell
git clone https://github.com/ferraroroberto/task-os <folder>
cd <folder>
.\setup.bat -WhatIf     # optional: list every change, make none
.\setup.bat             # add -Startup to also start the tray at log on
```

`setup.bat` does, in order:

1. creates `.venv` when it is missing;
2. installs `requirements.txt`, and later reinstalls only when that file changed (its hash is kept inside `.venv`);
3. runs the dependency step, `python -m src.install apply`: on a PC that already has a `config/config.json` it adds the keys that change nothing (below), and it registers the `taskos://` folder opener for this user when none is registered. It reruns only when `config/config.sample.json` changed;
4. creates `config/config.json` and `config/sharepoint-mapping.json` from their `*.sample.json` when they are missing;
5. ends with two lists: the required items, each `ok`, `missing` or `unknown`, and the optional features, each `available`, `off` or `unknown` with what it unlocks. Setup has succeeded when it ends with `Setup complete` and exits 0; an optional feature that is `off` never changes that.

**Edit `config/config.json` before the first start.** The sample carries the author's account and synced folders, and issue sync and the mirror act on them within seconds of the first start. The checklist's *Config reviewed for this PC* item stays `unknown` until each such key holds a value of yours; `.venv\Scripts\python.exe -m src.install check config-reviewed` lists them. What to decide for each key: [Setup and migration](setup-and-migration.md#set-up-a-new-machine); every key: [Configuration](configuration.md).

Then start it:

```powershell
.\tray.bat          # tray icon -> the app on the configured port (8448 by default)
```

The optional features that may still want you:

- **Your name:** Settings, Your name (comments and activity are signed with it).
- **HTTPS certificate** and **Sign-in for other devices**, for the phone only: `.venv\Scripts\python.exe scripts\gen_tailscale_cert.py`, then `scripts\gen_token.py` or `.venv\Scripts\python.exe -m src.password set` ([Phone access](access.md)). A password file that holds no usable password (empty or corrupt) is `off` even when a token is set, and one that cannot be read is `unknown`.
- **Shared tray helper:** `tray.bat --restart` needs the fleet's `tray_lifecycle.ps1` under `%USERPROFILE%\.claude\tray`. A plain `tray.bat` start works without it.
- **Start at log on:** run `.\setup.bat -Startup`. It adds a `task-os.bat` to your Startup folder that calls this checkout's `tray.bat`.

`.\setup.bat -WhatIf` reports every change as `would ...` and writes nothing. Its dependency step line only says the step would run; the exact keys are listed by the command above, once a `.venv` exists.

## Update

```powershell
git pull --ff-only
.\tray.bat --restart
```

Nothing else is needed:

- **The tree stays clean.** Every file a run writes is gitignored: configs, `data/`, `.env`, `mirror/`, `webapp/` (certificates and logs), the gate's caches. No tracked file is rewritten at runtime or holds a machine value, so a pull never meets a local edit and always fast-forwards.
- **`tray.bat --restart`** reclaims the configured port and starts fresh. Check the build with `GET /api/version`: its `git_sha` equals `git rev-parse --short HEAD`. A schema change migrates itself at startup.
- **After a pull that changed `requirements.txt` or `config/config.sample.json`,** run `.\setup.bat` before the restart. Running it after every pull is safe: a second run reports `unchanged` and writes nothing.

What `setup.bat` does to a PC that already has its settings:

- `config/config.json`: **every value it holds stays as it is.** A key the sample has and the file lacks is added only when the app runs exactly the same with it as without it, and only after the file is copied to `config/backups/config.<date>-<time>.json`. `setup.bat` shows only that the dependency step ran; `.venv\Scripts\python.exe -m src.install apply -WhatIf` lists the key names it would add and hold back (never a value) before you run it.
- **Keys whose absence means something are held back** and listed: no `time.people` means the implicit owner, no `mirror` block means no mirror, and the sample's `issues.owner` or `placeholders.onedrive` belong to someone else. Add those by hand if you want them. This is why the toolbox installer's own top-up, which adds every missing key, is not used for this file.
- `config/sharepoint-mapping.json` (read only by the one-shot import) is the owner's own list: created when missing, never rewritten.
- A config that is not valid JSON is left untouched and reported; the run exits 1 so you notice. Fix the JSON, then run `setup.bat` again.

## Migrate from an existing install

Use this on a PC that already runs an older copy of task-os: one that may not be a git clone, and may live at another path. The old copy keeps running until the new one is verified, and it is deleted only when you say so.

Two things make this different from a copy to a second PC. The old and the new copy on one PC share the same database by default, because it lives outside the checkout, and both default to port 8448. So the old copy is stopped before the new one starts, and the database is not copied at all unless the old copy kept it inside its own folder.

1. **Clone fresh beside it.** `git clone https://github.com/ferraroroberto/task-os <new folder>`; never clone over the old folder.
2. **Copy this PC's own files across.** From the old folder into the new one, keeping relative paths (all are gitignored, so nothing tracked is touched):
   - settings and secrets: `config\config.json` (holds the port, the mirror and backup folders, the `auth` and `alerts` secrets and the service addresses);
   - the sign-in password: `config\app_password.json` when it exists;
   - the one-shot import's column map, only if you will import again: `config\sharepoint-mapping.json`;
   - the Notion import token, only if you will import again: `.env` (keys `NOTION_API_TOKEN` and `NOTION_TASKS_DB_ID`);
   - team avatars, team mode only: `data\avatars\`.
3. **Check where the database is.** It is `tasks.db` (and `usage.sqlite3` beside it) in the runtime-data folder: `TASKOS_DB_PATH` if that environment variable is set, else `<TASK_OS_DATA_DIR>`, else `<FLEET_DATA_ROOT>\task-os`, else `C:\sqlite\task-os`. If the old copy already uses that folder, copy nothing: the new copy opens the same database. If the old copy kept it at `data\tasks.db` inside its own folder, stop the old app first (step 5), then copy `tasks.db` (alone: the `-wal` and `-shm` files next to it are empty after a clean stop) into `C:\sqlite\task-os\`, creating the folder if needed. `tasks backup` makes a consistent copy while the app runs.
4. **Top them up.** In the new folder run `.\setup.bat -WhatIf`, read it, then `.\setup.bat`. `config\config.json` gains only the keys it lacks that change nothing; the values you copied stay as they were. Check that the mirror and backup folders in the copied config exist on this PC.
5. **Stop the old copy.** Tray menu, Quit. If the old copy started at log on, delete its `task-os.bat` from `shell:startup` now: `setup.bat -Startup` keeps any Startup entry that names task-os, and the old one points at the old folder.
6. **Start the new one.** `.\tray.bat`, and `.\setup.bat -Startup` if it should start at log on.
7. **Verify it.** `GET http://127.0.0.1:8448/api/version` shows the new checkout's `git_sha` and a `schema_version`; Today and Board show your tasks and the count matches what you had; Settings shows the mirror and backup rows as you expect. If anything is wrong, quit the new tray and start the old one again: it is untouched.
8. **Retire the old folder, only after you confirm.** Nothing in this playbook or in `setup.bat` deletes the old copy. When you are satisfied, rename it first (for example `<old folder>.retired`), run on the new copy for a while, and delete it yourself once you are sure. An agent working through this playbook asks you before it deletes anything.

**Do not copy:** `.venv\` (recreated), `data\logs\` and `webapp\*.log` (rebuilt), `mirror\` (rebuilt from the database on the first start), and `webapp\certificates\` (issued for one PC's tailnet name: run `scripts\gen_tailscale_cert.py` on the new one). The `taskos://` folder opener is registered per user, not per folder, so it needs no copy and keeps working. The full table of state, and what to edit after copying the config: [Setup and migration](setup-and-migration.md#migrate-from-an-existing-machine).

## Uninstall

1. Quit the tray from its icon menu.
2. Delete `task-os.bat` from your Startup folder (`shell:startup`) if you added it.
3. Remove the `taskos://` scheme: `.venv\Scripts\python.exe assets\opener\install_opener.py --uninstall`.
4. Delete the folder. Keep a copy of `config\` first if you may want it back.

The database is **not** in the folder: it is in the runtime-data folder (`C:\sqlite\task-os` by default), and deleting the checkout leaves it. Delete that folder too only if you want every task gone, and copy `tasks.db` somewhere first if you are unsure. The synced mirror and backup folders are yours and are never touched.

## Execution policy

Nothing needs a signature or a policy override, `AllSigned` included:

- **`.bat` files** (`setup.bat`, `tray.bat`, `tasks.bat`) run in cmd.exe, which no execution policy covers.
- **`tray.bat`** starts the shared tray helper through `src\ps_script.py`, which loads it as a ScriptBlock under `AllSigned` or `Restricted`.
- **The gate** loads its one sibling script the same way. To start the gate itself under `AllSigned`, run `& .\.venv\Scripts\python.exe -m src.ps_script scripts\verify-before-ship.ps1`.

`tests/gates/test_portability.py` checks all three under a process-scope `AllSigned` policy.
