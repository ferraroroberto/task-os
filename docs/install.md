# Install, update and migrate task-os

task-os installs, updates and migrates the way any app in the toolbox does: clone it and run one `setup.bat`. An update is a pull plus a restart. A migration, onto a fresh clone beside an older copy or in its place, is one `setup.bat` call. None of them ever resets or overwrites what a PC has configured.

What `setup.bat` runs is the toolbox's shared installer, `src/installer.py`, driven by the `[install]` table in `.fleet.toml`. The parts that are task-os's own (the config top-up, the folder opener, the sign-in start and the personal checklist items) are the commands in `src/install/`.

## Install

You need Windows 10 or 11, **Git**, and **Python 3.14** (python.org, with the `py` launcher). `setup.bat` needs Python 3.11 or newer to start and builds the `.venv` with the interpreter it finds, so install 3.14 first. Optional, by feature: the GitHub CLI `gh` (logged in) or `glab` for issue sync; Tailscale for phone access over HTTPS; a reachable local model hub for voice and AI triage; folder-explorer for folder and email search and Inbox archiving. Node.js and the Playwright browsers are only for the developer gate. Which feature needs what: [Setup and migration](setup-and-migration.md#set-up-a-new-machine).

```powershell
git clone https://github.com/ferraroroberto/task-os <folder>
cd <folder>
.\setup.bat -WhatIf     # optional: list every change, make none
.\setup.bat             # add -Startup to also start the tray at log on
```

`setup.bat` does, in order:

1. creates `.venv` when it is missing;
2. installs `requirements.txt`, and later reinstalls only when that file changed (its hash is kept inside `.venv`);
3. runs the dependency step, `python -m src.install apply`: on a PC that already has a `config/config.json` it adds the keys that change nothing (under [Update](#update)), and it registers the `taskos://` folder opener for this user when none is registered. It reruns only when `config/config.sample.json` changed;
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

`.\setup.bat -WhatIf` reports every change as `would ...` and writes nothing. Its dependency step line only says the step would run; the exact keys are listed by `.venv\Scripts\python.exe -m src.install apply -WhatIf`, once a `.venv` exists.

### Uninstall

1. Quit the tray from its icon menu.
2. Delete `task-os.bat` from your Startup folder (`shell:startup`) if you added it.
3. Remove the `taskos://` scheme: `.venv\Scripts\python.exe assets\opener\install_opener.py --uninstall`.
4. Delete the folder. Keep a copy of the files listed under [Migrate](#migrate) first if you may want them back.

The database is **not** in the folder: it is in the runtime-data folder (`C:\sqlite\task-os` by default), and deleting the checkout leaves it. Delete that folder too only if you want every task gone, and copy `tasks.db` somewhere first if you are unsure. The synced mirror and backup folders are yours and are never touched.

## Update

```powershell
git pull --ff-only
.\setup.bat             # needed when requirements.txt or config.sample.json changed; safe every time
.\tray.bat --restart
```

- **The tree stays clean.** Every file a run writes is gitignored: configs, `data/`, `.env`, `mirror/`, `webapp/` (certificates and logs), the gate's caches. No tracked file is rewritten at runtime or holds a machine value, so a pull never meets a local edit and always fast-forwards.
- **`tray.bat --restart`** reclaims the configured port and starts fresh. Check the build with `GET /api/version`: its `git_sha` equals `git rev-parse --short HEAD`. A schema change migrates itself at startup. Without the shared tray helper, choose Quit from the tray menu and run `.\tray.bat`.
- A second `setup.bat` run reports `unchanged` and writes nothing.

What `setup.bat` does to a PC that already has its settings:

- `config/config.json`: **every value it holds stays as it is.** A key the sample has and the file lacks is added only when the app runs exactly the same with it as without it, and only after the file is copied to `config/backups/config.<date>-<time>.json`. `setup.bat` shows only that the dependency step ran; `.venv\Scripts\python.exe -m src.install apply -WhatIf` lists the key names it would add and hold back (never a value) before you run it.
- **Keys whose absence means something are held back** and listed: no `time.people` means the implicit owner, no `mirror` block means no mirror, and the sample's `issues.owner` or `placeholders.onedrive` belong to someone else. Add those by hand if you want them. This is why the toolbox installer's own top-up, which adds every missing key, is not used for this file.
- `config/sharepoint-mapping.json` (read only by the one-shot import) is the owner's own list: created when missing, never rewritten.
- A config that is not valid JSON is left untouched and reported; the run exits 1 so you notice. Fix the JSON, then run `setup.bat` again.

## Migrate

For a PC that already runs a copy of task-os. What moves is declared in `[install.migrate]` of `.fleet.toml`, and each item is copied only when the old copy has it and the new one does not:

| Copied | What it is |
| --- | --- |
| `config/config.json` | Settings, including the port, the mirror and backup folders and the sign-in secrets. |
| `config/app_password.json` | The sign-in password hash. |
| `config/sharepoint-mapping.json` | The column map of the one-shot import. |
| `.env` | The Notion import token. |
| `data/avatars/` | Team avatars, team mode only. |
| `webapp/certificates/` | The HTTPS certificate pair, so phone access keeps working. |

The secrets among them are compared by hash, never printed. The database and the usage log are in the `task-os` runtime-data folder (`C:\sqlite\task-os` by default): they stay where they are and both copies open the same ones. `.venv`, the logs, `mirror/` and `config/backups/` are not carried. The installer does the whole move; nothing here or in `setup.bat` deletes the old copy.

**Reinstall in the same folder (the usual case).** It needs the folder to be a git clone with an `origin`. Close any terminal or editor whose current folder is inside it, then from a terminal outside the app:

```powershell
cd <parent folder>
.\<folder>\setup.bat -InPlace -WhatIf    # read the backup name and every step; nothing changes
.\<folder>\setup.bat -InPlace
```

It stops the app, keeps the replaced copy as `<folder>.bak-YYYYMMDD-N`, clones the remote's default branch into the same path, installs, starts the tray and passes only when the new clone serves its own commit. The app is down while the new `.venv` is built. The path is unchanged, so the Startup entry and anything else that stores it need no edit.

**Beside it (another folder, or an old copy that is not a git clone):**

```powershell
git clone https://github.com/ferraroroberto/task-os <new folder>
cd <new folder>
.\setup.bat -MigrateFrom <old folder> -StopOld
```

Pass `-StopOld` on the same PC: both copies bind the same port and share one tray lock, so the new one cannot start beside a running old one. `-WhatIf` lists every step and every file first. A path in the copied config that points into the old folder is rewritten to the new one.

Only you can do these steps:

- **Before an in-place reinstall,** push or write down anything else in the old folder that you want in the new one: local branches, stashes, linked worktrees and files outside the table above stay in the backup.
- **A database inside the old folder** (`data\tasks.db`, from before the runtime-data folder) is not carried. Quit the tray from its menu first, then copy `tasks.db` into `C:\sqlite\task-os\`.
- **Repoint** whatever stores the old path, after a `-MigrateFrom` into another folder: the run lists what still points at it. For a start at log on, delete the old `task-os.bat` from `shell:startup`, then run `.\setup.bat -Startup` in the new folder.
- **Check it:** Today and Board show your tasks, and Settings shows the mirror and backup rows as you expect.
- **Fall back** if verify fails (the report names the step): quit the new tray, rename the new folder away and the backup to the original name, and start it with `.\tray.bat`; it is untouched.
- **Retire the backup** once you are sure the new copy works, by deleting it yourself. An agent working through this playbook asks you before it deletes anything.

Moving to **another PC** is not this section: the old folder has to be reachable here, the database is not in it, and a certificate is issued for one PC's tailnet name, so reissue it there. The full table of state: [Setup and migration](setup-and-migration.md#migrate-from-an-existing-machine).

## Execution policy

Nothing needs a signature or a policy override, `AllSigned` included:

- **`.bat` files** (`setup.bat`, `tray.bat`, `tasks.bat`) run in cmd.exe, which no execution policy covers.
- **`tray.bat`** starts the shared tray helper through `src\ps_script.py`, which loads it as a ScriptBlock under `AllSigned` or `Restricted`.
- **The gate** loads its one sibling script the same way. To start the gate itself under `AllSigned`, run `& .\.venv\Scripts\python.exe -m src.ps_script scripts\verify-before-ship.ps1`.

`tests/gates/test_portability.py` checks all three under a process-scope `AllSigned` policy.
