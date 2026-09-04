# task-os folder opener

Why this exists: a browser tab cannot touch the file system, so a web-only click could open a folder only on the machine that runs the server. task-os stores folder refs **unresolved** — `{onedrive}/house/kitchen`, `{user}/code/garden-bot`, `{sharepoint:docs}/plans` — and the folder chip on every task is a link `taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen`. Windows hands that URL to this tiny per-PC handler, which resolves the placeholders from what **this** PC knows and opens **its own** synced copy in Explorer. Same mechanism on the server PC, on a laptop, on any machine where the folder is synced.

## Files

| File | What |
| --- | --- |
| `opener.ps1` | The **launcher** — what the URL scheme is registered to run, wrapped in `conhost.exe --headless` (see *Why headless* below) so nothing is on screen. It takes the URL as an argument, refuses one carrying a quote, and hands it to `opener.cmd` through the environment (`TASKOS_OPENER_URL`); a notice (missing handler, empty URL, a refused quote) shows as a popup, and it captures `opener.cmd`'s own output and pops that up too on a non-zero exit. See *Why a launcher* below; the one job it does itself is `taskos://resume?session=…` (#77): it searches `%USERPROFILE%\.claude\projects\**\*.jsonl` for the transcript carrying that web session id and reopens the session in a terminal (`wt` when installed, else PowerShell) running `claude --resume <local-uuid>` in the repo the transcript records (`"cwd"`); a session this PC never saw opens the conversation on the web instead, with a popup notice. `TASKOS_OPENER_PROJECTS` overrides the transcript root (tests); dry-run prints `resume: <uuid> in <dir>` / `resume-web: <url>` and never pops a window. |
| `opener.cmd` | The handler. Pure `cmd` (no execution policy applies, no Python): URL-decodes the ref, expands `{onedrive}` → `%OneDriveCommercial%` (when set) else `%OneDrive%`, `{user}` → `%USERNAME%`, `{sharepoint:<name>}` → the `<name>=<path>` line in `opener.env`, flips the slashes and runs `start "" explorer "<path>"` (a file opens with its default app). A path that does not exist on this PC shows a notice — *not synced on this PC* — with the resolved path to copy: a popup via the launcher, a visible console (`pause`) on the fallback registration, where it genuinely is a console. On the fallback (`.cmd`-only) registration a `taskos://resume` URL gets a visible *needs the PowerShell opener* notice — resume never degrades silently. |
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

## Why headless (task-os#130)

`powershell.exe` is a console-subsystem executable — `ShellExecute` allocates a console for it before a line of the script runs, and on this PC (Windows 11, Windows Terminal as the default terminal) that console is a full WT window. Measured, not assumed, with a throwaway-scheme probe registering each candidate and polling for new top-level windows during a real invocation:

| Registered `shell\open\command` | Visible window? |
| --- | --- |
| `powershell.exe -File opener.ps1 -Url "%1"` (the old shape) | flashes a Windows Terminal window (~400–900 ms) |
| `powershell.exe -WindowStyle Hidden -File opener.ps1 -Url "%1"` | **still flashes** — the console exists before the flag is honoured, and WT does not collapse it |
| `conhost.exe --headless powershell.exe -File opener.ps1 -Url "%1"` | none observed |

`conhost.exe --headless` wins, at the cost of one thing: the pseudo-console it creates makes the *caller's* stdout capture come back empty (verified with a `subprocess.run(...).stdout` probe) — a process spawned through it still runs to completion and its own children can still capture *its* output normally, but whoever launched `conhost.exe --headless` itself cannot read what came out. That is exactly what `install_opener.py`'s self-test and `install.txt`'s `$ok=` probe need to do (read `TASKOS_OPENER_PS_OK` back), so both keep probing the **bare**, unwrapped `powershell.exe -File opener.ps1 -Url taskos://selftest` form — only the *registered* command gets the `conhost.exe --headless` wrap. The probe only needs to know the script can run at all; it was never checking whether `ShellExecute` would hide the console.

Because nothing is on screen once the launcher runs headless, every notice that used to pause a console (`Read-Host` / `pause`) now shows as a `WScript.Shell` popup instead — `opener.ps1` for its own notices, and by capturing `opener.cmd`'s output and popping it up on a non-zero exit. `TASKOS_OPENER_DRYRUN=1` keeps the old plain-text behaviour and never pops a window, so the test suite stays hermetic. The fallback `.cmd` registration is unaffected — it is a console by construction (`cmd.exe /c "…" "%1"`), out of scope here, and keeps its `pause` lines.

## Install on a PC — 30 s, no admin

Paste the first command from `install.txt` into PowerShell (replace `<base-url>` with your task-os address; the Settings card does that for you). Then click any folder chip: the browser asks once *"Open task-os opener?"* — tick *always allow* — and Explorer opens the folder. Or test without the app: `start taskos://open?ref=%7Bonedrive%7D` in a terminal.

`opener.env` (`%LOCALAPPDATA%\task-os\opener.env`) holds the placeholders this PC needs beyond the two Windows already knows — one `name=path` line each, e.g. `docs=C:\Users\me\Tenant\docs - Documents` for `{sharepoint:docs}`; a line named `onedrive=…` or `user=…` overrides the environment-derived value. Values may use `%VARS%`. Settings → *Folder opener* shows a template with the names this install's config uses.

## What was verified (a locked-down PC, 2026-08-17)

- Per-user `HKCU\Software\Classes\<scheme>` registration works through the **registry API** (`New-Item` / `Set-ItemProperty`, Python `winreg`) even where `reg.exe` / regedit are disabled ("Registry editing has been disabled by your administrator").
- A PowerShell machine policy of `AllSigned` blocks `.ps1` **files** but not an inline command pasted into the console — hence one line, no script file.
- A `.cmd` in `%LOCALAPPDATA%` runs, and `start explorer` opens a folder from it.
- Edge hands `scheme://…` to the registered handler after a one-time *open?* prompt.
- `%OneDriveCommercial%` / `%OneDrive%` resolve to the local sync roots.

## What was verified (this PC, 2026-09-04, task-os#130)

- The window-visibility probe table above (`-WindowStyle Hidden` still flashes on Windows Terminal; `conhost.exe --headless` does not).
- A `WScript.Shell` popup shown from a script launched through `conhost.exe --headless` is fully visible and dismissible, and the process exits cleanly afterward — no leftover process waiting on stdin.
- Output piped internally between processes under `conhost.exe --headless` (`$out = & $handler 2>&1`) still captures correctly; only the *caller's* own capture of the headless-wrapped process itself comes back empty, which is why the self-test probe stays unwrapped (see *Why headless* above).
- The real, installed `taskos://` scheme on this PC, invoked the same way a browser does (`ShellExecute`, via `Start-Process taskos://…`): a valid ref opens Explorer with no console at any point; an unresolvable ref pops the notice and leaves no process behind after dismissal. **Not verified this way: the click-through from an actual browser tab.** CDP-driven automation could not complete the native *"Open task-os opener?"* permission dialog (it froze the tab's own screenshot capture once, consistent with a blocking native dialog it cannot see or click) — a known limit of automating a click that leaves the page. See `docs/validation.md`'s story 09 amendment for the full account.

## Caveats

- **First click per browser** shows an *Open task-os opener?* prompt — tick *always allow*. If the opener is not installed, nothing happens; the app shows a one-time hint under the chip pointing at Settings → *Folder opener*.
- **The path must be synced on this PC.** The opener cannot fetch anything; a folder that only exists on another machine gets the visible *not synced* notice with the resolved path.
- **Phone / tablet:** no Explorer to open — the chip shows the resolved path with a *Copy* button (and the web URL when the task carries one).
- Percent sequences beyond the common set (accented letters) hand the whole job to one inline PowerShell command (same placeholder rules, no script file); a `!` inside a path is lost (cmd's delayed expansion) — rename the folder or use the copy fallback.
- **A quote in the link is refused, never opened.** No ref this app builds contains one, so a link carrying a quote (raw or as `%22`) was crafted or mangled elsewhere; the opener stops and says so rather than acting on half a path.
- **Fallback mode on a locked-down PC.** Where a machine policy blocks running a script file outright, the installers cannot register the launcher and fall back to registering `opener.cmd` directly — the shape with the re-parse described above. That install is **not** silent: `install_opener.py` prints `mode: FALLBACK`, the pasted one-liner ends in `FALLBACK mode`, and Settings → *Folder opener* shows a `fallback mode` chip. In that mode, treat a `taskos://` link from anywhere but this app as untrusted.
- **A PC still registered with the pre-#130 shape** (`powershell.exe -File opener.ps1 -Url "%1"`, no `conhost.exe --headless` wrap) still works — it is just as safe against #40's injection — but flashes a console on every open. Settings → *Folder opener* reports it as `launcher mode (old, visible console)` and points at re-running the install command below.
- Uninstall (second line in `install.txt` / `install_opener.py --uninstall`) removes the scheme, `opener.cmd` and `opener.ps1`; your `opener.env` stays.

## Tests

`tests/test_opener.py` runs `opener.cmd` for real through `cmd.exe`, and `opener.ps1` for real through `powershell.exe`, with the environment pointed at a temp tree (`OneDrive`, `USERNAME`, `LOCALAPPDATA`) and `TASKOS_OPENER_DRYRUN=1`, which makes them print `open: <path>` / `missing: <path>` instead of launching anything (and never pops a window): decoding, placeholder expansion, `opener.env`, the missing-path notice, the quote refusal, that both installers prefer the launcher and announce the fallback, that the registered command wraps `conhost.exe --headless` while the self-test probe stays unwrapped, `registration_mode()`'s `launcher` / `launcher-stale` / `fallback` split, and `install_opener.py --dry-run`. Windows-only; skipped elsewhere. The window-visibility and popup-behaviour tables above came from throwaway-scheme probes run by hand — the tests pin the resulting design, they do not re-run the probes, and the "no window" fact itself is verified by a headed walk (`docs/validation.md`), not by the suite.
