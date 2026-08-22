# Story 09 — Open a folder

**Issue:** #10 (Step 9/13). **Test:** `tests/e2e/test_story_09_folders.py` (one Chromium walk: 1440×900 desktop, then a 390-wide touch context) against a **seeded disposable instance whose `{onedrive}` placeholder points at a temp tree** (so the seed's refs resolve to folders that exist and the folder index has something to index — never a real synced folder). Unit coverage for the gate: `tests/test_placeholders.py` (resolve / to_ref / config flattening / `GET /api/resolve` / `folder_resolved` + `folder_url` on task payloads / `/api/status` folders + opener + placeholders / the public `/opener/opener.cmd`), `tests/test_folder_index.py` (service over a temp tree — reindex, load, background start, not-configured / unresolved / missing roots as visible states — plus the API and `tasks folders` CLI), `tests/test_opener.py` (**runs `opener.cmd` for real through `cmd.exe`** with `OneDrive` / `OneDriveCommercial` / `USERNAME` / `LOCALAPPDATA` pointed at a temp tree and `TASKOS_OPENER_DRYRUN=1`: URL-decoding incl. `%20 %23 %25 %26 %2B %2C %3A %2F %5C %7B %7D` and more, both URL forms, `{onedrive}` / `{user}` / `{sharepoint:name}` from `opener.env` incl. `%VARS%` and overrides, `OneDriveCommercial` precedence, a file ref, an unknown placeholder, the real missing-path notice, `install_opener.py --dry-run` printing the registry plan, `install.txt`'s two lines).

**Steps → expected**

1. The Table shows the *Kitchen* task's folder chip: an `<a class="chip chip-folder">` with `href="taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen"` (same tab, no `target`), tooltip = the path **this server** resolves (`…/od/house/kitchen`, from `folder_resolved` in the payload — the page never resolves a ref itself).
2. Click the chip → the browser hands the URL to the OS (`taskos://` scheme; intercepted in the automated walk, real in the headed one) → the row does **not** open → a popover appears under the chip, once per browser: *Nothing opened? **Install the opener — 30 s*** + the resolved path + **Copy path**. Escape closes it; a second click shows no hint (`localStorage task-os.opener-hint`).
3. The hint's link → **Settings → Folder opener & folder index**: the one-line PowerShell install command from `opener/install.txt` with this instance's address filled in (`…/opener/opener.cmd`, `HKCU:\Software\Classes\taskos`), a Copy button, the uninstall line, the `opener.env` template with this install's placeholders (`# onedrive=…`), the folder-index row (`ready · {onedrive} · N folder(s) · last indexed …`) and **Reindex folders now**.
4. Drawer (`#task/2`): the **Folder** section shows the chip + the resolved path + **Copy path**; typing an **absolute path** (`…\od\admin\car`, backslashes) in the field and pressing Enter stores `{onedrive}/admin/car` (folded onto the placeholder by `GET /api/resolve`), toast *Stored as {onedrive}/admin/car*, the chip's href follows.
5. **Pick from folder index…** → type `kitchen plans` → one hit `plans · {onedrive}/house/kitchen/plans` → Enter attaches it: `folder_ref` = `{onedrive}/house/kitchen/plans`, an `activity` row `folder_ref → …`.
6. Dark theme, same drawer.
7. Phone (390 wide, touch = coarse pointer): tapping the chip does **not** navigate — the popover shows *Folder — path on the server PC*, the resolved path and **Copy path**.
8. **Real opener on PC #1** (headed walk, not automatable): the chip click in a real Chrome hands `taskos://open?ref=%7Bonedrive%7D%2Ftask-os` to `%LOCALAPPDATA%\task-os\opener.cmd` (installed with `python opener\install_opener.py`), which expands `{onedrive}` from `%OneDrive%` and opens **Explorer on `E:\onedrive\task-os`**.

**Screenshots (1440×900 unless noted) — 1–7 saved by the test, 8–9 from the headed walk**

| Step | Shot |
| --- | --- |
| 1 Table: folder chips are `taskos://` links | [story-09-folders-1-desktop.png](../screenshots/story-09-folders-1-desktop.png) |
| 2 the one-time hint under the chip | [story-09-folders-2-desktop.png](../screenshots/story-09-folders-2-desktop.png) |
| 3 Settings: Folder opener card + install command + `opener.env` template | [story-09-folders-3-desktop.png](../screenshots/story-09-folders-3-desktop.png) |
| 4 drawer: absolute path → `{onedrive}/…` ref | [story-09-folders-4-desktop.png](../screenshots/story-09-folders-4-desktop.png) |
| 5 drawer: folder-index picker with the hit | [story-09-folders-5-desktop.png](../screenshots/story-09-folders-5-desktop.png) |
| 6 drawer after the pick (dark) | [story-09-folders-6-desktop.png](../screenshots/story-09-folders-6-desktop.png) |
| 7 phone: copy popover with the resolved path (390×844) | [story-09-folders-7-phone.png](../screenshots/story-09-folders-7-phone.png) |
| 8 **real Chrome on PC #1**: the page right after the click (chip `{onedrive}/task-os`, hint shown) | [story-09-folders-8-desktop.png](../screenshots/story-09-folders-8-desktop.png) |
| 9 **the Explorer window the opener opened** — `E:\onedrive\task-os` (navigation pane cropped away) | [story-09-folders-9-desktop.png](../screenshots/story-09-folders-9-desktop.png) |

**Result — 2026-08-17: verified on PC #1 (browser → opener → Explorer); second PC not verified.**

- [x] Automated: `verify-before-ship.ps1` green — byte-compile (incl. `opener/`), ruff, the unit suite (incl. `test_placeholders`, `test_folder_index`, `test_opener` — the last one drives `cmd.exe` on the real handler), the routed e2e (full tier: smoke + stories 01, 04, 05, 06, 07, 09).
- [x] Opener installed for real on this PC: `python opener\install_opener.py --dry-run` printed the plan, then the real run wrote `%LOCALAPPDATA%\task-os\opener.cmd` + `opener.env` and `HKCU\Software\Classes\taskos` (`URL Protocol`, `DefaultIcon`, `shell\open\command = cmd.exe /c ""…\opener.cmd" "%1""`), all read back with `Get-ItemProperty`. `Start-Process taskos://open?ref=%7Bonedrive%7D%2Ftask-os` (the ShellExecute path) opened Explorer on `E:\onedrive\task-os` (`Shell.Application.Windows()` → `file:///E:/onedrive/task-os`). **Superseded 2026-08-20** — the registered command is now the launcher (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File …\opener.ps1 -Url "%1"`); see the amendment at the end of this file.
- [x] Browser → opener on PC #1: a disposable seeded instance of this build on `:8459` (`{onedrive}` = `E:/onedrive`, the *Kitchen* task's ref set to `{onedrive}/task-os` — an existing folder holding only the mirror/backup subfolders, nothing personal), opened in **real Google Chrome** (a fresh temporary profile whose Preferences pre-allowed the `taskos` scheme for that origin — the equivalent of ticking *always allow* on the first-time prompt) → click on the folder chip → **Explorer opened `E:\onedrive\task-os`** (shots 8–9), the hint popover appeared under the chip once. Nothing else on the page changed; the row did not open.
- [x] Folder index on the real config: `tasks --local folders reindex` over `{onedrive}/Documentos` → **11979 folders in 2.0 s** → `data/folder_index.txt`; `tasks folders` reports the roots, the count and the timestamp. (Real content stays off screen; the e2e index is the temp tree.)
- [x] `opener.cmd` edge cases by hand (dry-run) beyond the tests: `taskos://open/{onedrive}/…` path form, an already-absolute `E:\…` ref, `%25` last so `100%25` decodes once, `café` through the inline PowerShell fallback, the `not synced on this PC` console notice with `pause`.
- [ ] **Not verified — needs a second PC.** The story's second leg: install the opener on another machine and click from there → **its own** synced copy opens. Exact steps for the owner, on any other Windows PC that syncs the same folder:
  1. Open task-os from that PC (over the tailnet: `https://<host>.ts.net:8448`, sign in) → Settings → **Folder opener & folder index** → **Copy command** → paste into PowerShell (Win+X → Terminal), Enter → expect `task-os opener installed: C:\Users\<you>\AppData\Local\task-os\opener.cmd — placeholders in …\opener.env`. On a locked-down PC (script files blocked, `reg.exe` disabled) this is the route that was probe-verified on 2026-08-17; nothing here needs admin.
  2. If that PC's OneDrive is signed in with a second account, `%OneDriveCommercial%` wins over `%OneDrive%` automatically; if a ref uses `{sharepoint:<name>}`, add `name=<that PC's synced path>` to `opener.env` (the Settings card shows the template).
  3. Click a folder chip → the browser asks *Open task-os opener?* once (tick *always allow*) → **Explorer opens the folder in that PC's synced copy**. Screenshot pair to keep on the private issue: the page + the Explorer window.
  4. Negative check: click a chip whose folder is not synced there → the black console *task-os opener — This folder is not synced on this PC* with the resolved path, waiting on a key.
  5. Phone: tap a chip → the copy popover (already verified in the browser at 390 wide; the real device is the same leg story 07 left open).
- Not verified in this step, by design: the first-time *Open task-os opener?* prompt itself (a native browser dialog — Chrome's Preferences were pre-seeded to skip it; Edge showed the same prompt on the probe PC and handed the URL over after *always allow*); Windows-only handler (no macOS/Linux opener — the copy popover is the fallback there); a `!` inside a folder name (lost by cmd's delayed expansion — documented in `opener/README.md`).
- Incidental: `tests/test_mirror.py::test_appended_comment_lines_become_md_comments` carried a fixed `2026-08-17T12:00:00+02:00` timestamp that started sorting *before* "now" at noon today; the line now uses now + 1 h (same intent, no date-bomb).

---

## Amendment — 2026-08-20: the URL scheme is registered to a launcher (#40)

The story is unchanged (click a folder chip → Explorer opens **this** PC's synced copy); what changed is *what Windows runs* when the chip is clicked, and why.

**Reproduction, run for real on this machine before any code changed.** A throwaway scheme (`taskosprobe`, `HKCU` only, deleted afterwards, real `taskos` key read back unchanged before and after) registered against a probe handler that records its arguments, fired through `Start-Process`, `[Diagnostics.Process]::Start` and `cmd /c start`, with a harmless payload (`echo` into a temp file):

| Registered `shell\open\command` | URL with a raw `"` | URL with `%22` |
| --- | --- | --- |
| `cmd.exe /c ""probe.cmd" "%1""` (the shape story 09 shipped) | payload ran | inert, handler saw the URL still encoded |
| `"probe.cmd" "%1"` | payload ran | inert |
| both of the above `+ UseOriginalUrlEncoding=1` | payload ran | inert |
| `cmd /s /c …` · unquoted `%1` · `^"%1^"` | payload ran (at some quote count) | — |
| `powershell.exe -File probe.ps1 -Url "%1"` | **nothing ran**, handler got the URL | **nothing ran** |

Two results, both measured, not reasoned: **percent-encoded input is inert in every shape** (so browsers, and every ref this app builds via `quote(ref, safe='')`, are safe), and **no `cmd`-based shape survives a raw quote** — each injects at some quote count and the caller picks the count, so five shapes were tried against three counts and all five broke. Only an executable taking the URL as an argument held at every count.

**What shipped.** `opener/opener.ps1` is now the registered command; it refuses a URL containing a quote and passes the rest to `opener.cmd` in `TASKOS_OPENER_URL`, which `cmd`'s delayed expansion never re-tokenises. Where a machine policy blocks running a script file, both installers fall back to the old `.cmd` registration and **say so** — `mode: FALLBACK` from `install_opener.py`, `FALLBACK mode` at the end of the pasted one-liner, a `fallback mode` chip in Settings → *Folder opener*.

- [x] Automated: `verify-before-ship.ps1` green — byte-compile, ruff, the unit suite (`test_opener` now drives `opener.ps1` through `powershell.exe` as well as `opener.cmd` through `cmd.exe`), routed e2e.
- [x] The three new tests were run against the pre-fix tree (`git stash push -u`, tests restored on top) and **all three failed**; they pass on the fixed tree. Note honestly what each proves: they pin the fixed *design* (launcher registered, quote refused, fallback announced). The injection itself is reproduced by the probe above, not by the suite — the suite does not register schemes or ShellExecute.
- [x] Handler behaviour unchanged through the new path, by hand and in dry-run: `{onedrive}/house/kitchen (2024)` → `open: …`, `{sharepoint:docs}/plans` → `open: …`, `café` through the inline-PowerShell branch → `missing: …`, and a link carrying a quote → the refusal notice with nothing opened, raw **and** as `%22` (the encoded one used to reach `[uri]::UnescapeDataString` and die on a raw `Test-Path` exception — an exception is not a state, so it refuses now too).
- [x] Installed for real on this PC with the new installer: `mode: launcher`, `HKCU\Software\Classes\taskos\shell\open\command` read back as `powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\<me>\AppData\Local\task-os\opener.ps1 -Url "%1"`, then `Start-Process taskos://open?ref=%7Bonedrive%7D%2Ftask-os` opened Explorer on the same folder as before.
- [ ] **Not verified — needs the locked-down second PC.** That the fallback branch is the one taken where script files are blocked, and that it prints `FALLBACK mode` there. The probe on 2026-08-17 established that such a PC blocks `.ps1` **files** while allowing an inline pasted command, which is exactly the case the fallback exists for — but the branch itself has only been exercised here by forcing it, not by a real policy.
