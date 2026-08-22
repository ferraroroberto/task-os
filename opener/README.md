# task-os folder opener

Why this exists: a browser tab cannot touch the file system, so a web-only click could open a folder only on the machine that runs the server. task-os stores folder refs **unresolved** — `{onedrive}/house/kitchen`, `{user}/code/garden-bot`, `{sharepoint:docs}/plans` — and the folder chip on every task is a link `taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen`. Windows hands that URL to this tiny per-PC handler, which resolves the placeholders from what **this** PC knows and opens **its own** synced copy in Explorer. Same mechanism on the server PC, on a laptop, on any machine where the folder is synced.

## Files

| File | What |
| --- | --- |
| `opener.ps1` | The **launcher** — what the URL scheme is registered to run. It takes the URL as an argument, refuses one carrying a quote, and hands it to `opener.cmd` through the environment (`TASKOS_OPENER_URL`). See *Why a launcher* below; it does no path work of its own. |
| `opener.cmd` | The handler. Pure `cmd` (no execution policy applies, no Python): URL-decodes the ref, expands `{onedrive}` → `%OneDriveCommercial%` (when set) else `%OneDrive%`, `{user}` → `%USERNAME%`, `{sharepoint:<name>}` → the `<name>=<path>` line in `opener.env`, flips the slashes and runs `start "" explorer "<path>"` (a file opens with its default app). A path that does not exist on this PC shows a visible console notice — *not synced on this PC* — with the resolved path to copy. |
| `install.txt` | The **one inline PowerShell command** to paste (downloads `opener.cmd` + `opener.ps1` to `%LOCALAPPDATA%\task-os\`, creates `opener.env`, probes whether the launcher runs, registers `HKCU\Software\Classes\taskos` via `New-Item` / `Set-ItemProperty`) and the matching uninstall line. Settings → *Folder opener* in the app shows it with this server's address filled in. |
| `install_opener.py` | The same install through `winreg` for a PC that has Python: `--dry-run` prints the registry plan, `--uninstall` removes it, `--scheme` registers a throwaway scheme (the tests). |

## Why a launcher, and not the handler directly

A URL scheme registered straight onto a `.cmd` reaches it as a **command-interpreter string**, and that string is re-parsed before the handler starts: a quote inside the URL ends the argument, and whatever follows becomes a second command. Measured on Windows 11 for task-os#40, against a throwaway scheme and a harmless payload:

| Registered `shell\open\command` | URL carries a raw `"` | URL carries `%22` |
| --- | --- | --- |
| `cmd.exe /c ""opener.cmd" "%1""` | **runs the injected command** | inert |
| `"opener.cmd" "%1"` (no wrapper) | **runs the injected command** | inert |
| either, plus `UseOriginalUrlEncoding=1` | **runs the injected command** | inert |
| `cmd /s /c …`, unquoted `%1`, `^"%1^"` | **runs the injected command** | inert |
| `powershell.exe -File opener.ps1 -Url "%1"` | safe | safe |

Read it as two facts. **No `cmd`-based shape is safe** — each of them injects at *some* number of quotes in the URL, and the caller picks that number; `UseOriginalUrlEncoding` changes nothing. **An executable that takes the URL as an argument is safe** at every quote count, because no command interpreter ever parses the string. That is why `opener.ps1` is the registered command and the `.cmd` is reached through the environment, where `cmd`'s delayed expansion (`!VAR!`) never re-tokenises the value.

Percent-encoded input is inert in every shape, which is what keeps ordinary use safe: browsers percent-encode, and every ref this app builds goes through `quote(ref, safe='')` (`src/placeholders.py::opener_url`). The exposure the launcher closes is a `taskos://` URL that did **not** come from task-os and was handed to `ShellExecute` unencoded — a `.url`/`.lnk` file, or another app relaying it raw.

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
- **A quote in the link is refused, never opened.** No ref this app builds contains one, so a link carrying a quote (raw or as `%22`) was crafted or mangled elsewhere; the opener stops and says so rather than acting on half a path.
- **Fallback mode on a locked-down PC.** Where a machine policy blocks running a script file outright, the installers cannot register the launcher and fall back to registering `opener.cmd` directly — the shape with the re-parse described above. That install is **not** silent: `install_opener.py` prints `mode: FALLBACK`, the pasted one-liner ends in `FALLBACK mode`, and Settings → *Folder opener* shows a `fallback mode` chip. In that mode, treat a `taskos://` link from anywhere but this app as untrusted.
- Uninstall (second line in `install.txt` / `install_opener.py --uninstall`) removes the scheme, `opener.cmd` and `opener.ps1`; your `opener.env` stays.

## Tests

`tests/test_opener.py` runs `opener.cmd` for real through `cmd.exe`, and `opener.ps1` for real through `powershell.exe`, with the environment pointed at a temp tree (`OneDrive`, `USERNAME`, `LOCALAPPDATA`) and `TASKOS_OPENER_DRYRUN=1`, which makes them print `open: <path>` / `missing: <path>` instead of launching anything: decoding, placeholder expansion, `opener.env`, the missing-path notice, the quote refusal, that both installers prefer the launcher and announce the fallback, and `install_opener.py --dry-run`. Windows-only; skipped elsewhere. The registration table above came from a throwaway-scheme probe run by hand — the tests pin the resulting design, they do not re-run the probe.
