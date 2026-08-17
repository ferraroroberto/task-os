# task-os folder opener

Why this exists: a browser tab cannot touch the file system, so a web-only click could open a folder only on the machine that runs the server. task-os stores folder refs **unresolved** — `{onedrive}/house/kitchen`, `{user}/code/garden-bot`, `{sharepoint:docs}/plans` — and the folder chip on every task is a link `taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen`. Windows hands that URL to this tiny per-PC handler, which resolves the placeholders from what **this** PC knows and opens **its own** synced copy in Explorer. Same mechanism on the server PC, on a laptop, on any machine where the folder is synced.

## Files

| File | What |
| --- | --- |
| `opener.cmd` | The handler. Pure `cmd` (no execution policy applies, no Python): URL-decodes the ref, expands `{onedrive}` → `%OneDriveCommercial%` (when set) else `%OneDrive%`, `{user}` → `%USERNAME%`, `{sharepoint:<name>}` → the `<name>=<path>` line in `opener.env`, flips the slashes and runs `start "" explorer "<path>"` (a file opens with its default app). A path that does not exist on this PC shows a visible console notice — *not synced on this PC* — with the resolved path to copy. |
| `install.txt` | The **one inline PowerShell command** to paste (copies `opener.cmd` to `%LOCALAPPDATA%\task-os\`, creates `opener.env`, registers `HKCU\Software\Classes\taskos` via `New-Item` / `Set-ItemProperty`) and the matching uninstall line. Settings → *Folder opener* in the app shows it with this server's address filled in. |
| `install_opener.py` | The same install through `winreg` for a PC that has Python: `--dry-run` prints the registry plan, `--uninstall` removes it. |

## Install on a PC — 30 s, no admin

Paste the first command from `install.txt` into PowerShell (replace `<base-url>` with your task-os address; the Settings card does that for you). Then click any folder chip: the browser asks once *"Open task-os opener?"* — tick *always allow* — and Explorer opens the folder. Or test without the app: `start taskos://open?ref=%7Bonedrive%7D` in a terminal.

`opener.env` (`%LOCALAPPDATA%\task-os\opener.env`) holds the placeholders this PC needs beyond the two Windows already knows — one `name=path` line each, e.g. `docs=C:\Users\me\Tenant\docs - Documents` for `{sharepoint:docs}`; a line named `onedrive=…` or `user=…` overrides the environment-derived value. Values may use `%VARS%`. Settings → *Folder opener* shows a template with the names this install's config uses.

## What was verified (a locked-down PC, 2026-08-17)

- Per-user `HKCU\Software\Classes\<scheme>` registration works through the **registry API** (`New-Item` / `Set-ItemProperty`, Python `winreg`) even where `reg.exe` / regedit are disabled ("Registry editing has been disabled by your administrator").
- A PowerShell machine policy of `AllSigned` blocks `.ps1` **files** but not an inline command pasted into the console — hence one line, no script file.
- A `.cmd` in `%LOCALAPPDATA%` runs, and `start explorer` opens a folder from it.
- Edge hands `scheme://…` to the registered handler after a one-time *open?* prompt.
- `%OneDriveCommercial%` / `%OneDrive%` resolve to the local sync roots.

## Caveats

- **First click per browser** shows an *Open task-os opener?* prompt — tick *always allow*. If the opener is not installed, nothing happens; the app shows a one-time hint under the chip pointing at Settings → *Folder opener*.
- **The path must be synced on this PC.** The opener cannot fetch anything; a folder that only exists on another machine gets the visible *not synced* notice with the resolved path.
- **Phone / tablet:** no Explorer to open — the chip shows the resolved path with a *Copy* button (and the web URL when the task carries one).
- Percent sequences beyond the common set (accented letters) hand the whole job to one inline PowerShell command (same placeholder rules, no script file); a `!` inside a path is lost (cmd's delayed expansion) — rename the folder or use the copy fallback.
- Uninstall (second line in `install.txt` / `install_opener.py --uninstall`) removes the scheme and `opener.cmd`; your `opener.env` stays.

## Tests

`tests/test_opener.py` runs `opener.cmd` for real through `cmd.exe` with the environment pointed at a temp tree (`OneDrive`, `USERNAME`, `LOCALAPPDATA`) and `TASKOS_OPENER_DRYRUN=1`, which makes the script print `open: <path>` / `missing: <path>` instead of launching anything: decoding, placeholder expansion, `opener.env`, the missing-path notice, and `install_opener.py --dry-run`. Windows-only; skipped elsewhere.
