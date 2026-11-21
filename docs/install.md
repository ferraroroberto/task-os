# Install and update

task-os moves to another Windows PC the way an app does: clone it, run one install, and from then on an update is a plain `git pull` plus a restart. The install never resets what a PC has configured, so it is safe to run again at any time.

## Fresh PC

You need **Git** and **Python 3.14** (from python.org, with the `py` launcher). Node and the Playwright browsers are only for the developer gate, not for running the app.

```powershell
git clone https://github.com/ferraroroberto/task-os <folder>
cd <folder>
.\scripts\install.bat -WhatIf     # optional: list every change, make none
.\scripts\install.bat             # add --startup to also start the tray at sign-in
tray.bat                  # tray icon -> the app on the configured port (8448 by default)
```

`scripts\install.bat` does, in order, and prints one `[status]` line per step:

1. **`.venv`**: created with `py -3.14 -m venv .venv` when missing, `kept` when present.
2. **Requirements**: whatever pip's own resolver says `requirements.txt` still needs, nothing else (`unchanged` when nothing is missing).
3. **Configs**: each ignored `config/<name>.json` is copied from its committed `config/<name>.sample.json` when missing (`created`). See [Settings that already exist](#settings-that-already-exist) for an existing one.
4. **Folder opener** (`taskos://`, per user, no admin): registered when the scheme has no handler, `kept` when it has one. Details: [assets/opener/README.md](../assets/opener/README.md).
5. **Start at sign-in**: only with `--startup`. It adds a `task-os.bat` in your Startup folder that calls this checkout's `tray.bat`. An existing Startup entry for task-os is `kept`.

It ends with a **checklist**, one line each, marked `ok`, `missing` (with the step that fixes it) or `unknown` (it could not be established). It covers the venv, the config (and whether its personal keys still hold the sample's values), your name, the opener, the sign-in start, the shared tray helper `tray.bat --restart` needs, the HTTPS certificate, a sign-in for other devices, and whether the app answers on its port. Then:

- **edit `config/config.json` before the first start.** The sample carries the author's account and synced folders, and Issue sync and the mirror act on them within seconds. The checklist's *config reviewed for this PC* line names each key still holding the sample's value. What to decide for each: [Setup and migration](setup-and-migration.md#set-up-a-new-machine); every key: [Configuration](configuration.md);
- set your name in **Settings → Your name** (comments and activity are signed with it);
- for the phone: a certificate (`scripts/gen_tailscale_cert.py`) and a token or password, see [access.md](access.md).

Walked once in a temp folder: the clone, then `scripts\install.bat -WhatIf` (it reports `would-create` for the venv and configs and writes nothing), then `scripts\install.bat` (`created`), then a second `scripts\install.bat` (`unchanged` everywhere).

## Settings that already exist

The install only ever adds. On a PC that already has a `config/config.json`:

- **Every value it holds stays as it is.**
- **Missing keys are added only when they change nothing.** Each key the sample has and the file lacks is tried through the app's own config reader. It is added only if the app reads the file exactly as before. Before anything is written, the file is copied to `config/backups/config.<date>-<time>.json`, and each added key is printed.
- **Keys whose absence means something are held back.** Examples: no `time.people` means the implicit owner, and the sample's `issues.owner` or `placeholders.onedrive` is someone else's. Adding the sample's value there would change what this PC does, so the key is listed as `held back` and you add it by hand if you want it.
- **A file with no reader holds every missing key back** (for example `config/sharepoint-mapping.json`, which only the one-shot import reads).
- **A config that is not valid JSON is left untouched** and reported `unparseable`; the run exits 1 so you notice. Fix the JSON, then run the install again.

A second run reports `unchanged` and writes nothing, so no new backup either.

## Update an installed PC

```powershell
git pull --ff-only
tray.bat --restart
```

Nothing else is needed:

- **The tree stays clean.** Every file a run writes is gitignored: configs, `data/` (database, logs, backups), `.env`, `mirror/`, `webapp/` (certificates), `tmp/`, the gate's caches. `.venv` is written without a trailing slash, so a junctioned venv matches too. A pull therefore never meets a local edit.
- **No tracked file is rewritten at runtime.** The runtime-write ratchet refuses a write into a code folder.
- **No tracked file holds a machine value.** The port `tray.bat` reclaims is the config's (`launcher.py port`), and the rest is read from the ignored config.
- **Re-running `scripts\install.bat` after a pull is safe** and picks up a new requirement or config key.

## Execution policy

Nothing needs a signature or a policy override, `AllSigned` included:

- **`.bat` files** run in cmd.exe, which no execution policy covers.
- **`tray.bat`** loads the shared tray helper as text and runs it as a ScriptBlock instead of `-File`.
- **The gate** loads its one sibling script the same way. To start the gate itself under `AllSigned`, run `& .\.venv\Scripts\python.exe -m src.ps_script scripts\verify-before-ship.ps1`.

`tests/gates/test_portability.py` checks all three under a process-scope `AllSigned` policy.

## Uninstall

Quit the tray from its icon menu, then remove the `taskos://` scheme:

```powershell
& .\.venv\Scripts\python.exe assets\opener\install_opener.py --uninstall
```

Then delete `task-os.bat` from your Startup folder (`shell:startup`) if you added it, and delete the folder. **`data/` holds the database**: copy `data/tasks.db` (and `config/`) somewhere first if you want to keep them.
