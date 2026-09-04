<#
task-os opener - the launcher Windows runs for a taskos:// URL.

Why a launcher at all, when opener.cmd does the work: a URL scheme registered
straight onto a .cmd reaches it as a *command line*, and cmd re-parses that
string before the handler ever starts. A quote inside the URL closes the
argument and everything after it becomes a second command. Measured on Windows
11 (task-os#40): every cmd-based registration shape - wrapped, bare, /s,
unquoted %1, caret-escaped - injects at some quote count, and the attacker
picks the count. An executable that takes argv does not: PowerShell binds -Url
to one argument and no command interpreter ever sees the string.

So this file is the registered command; it hands the URL to opener.cmd through
the environment, which cmd's delayed expansion never re-tokenises:

    conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File opener.ps1 -Url "%1"

The conhost.exe --headless wrap is task-os#130: ShellExecute allocates a
console for any console-subsystem exe before a line of the script runs, and on
this PC (Windows Terminal as default terminal) even `-WindowStyle Hidden`
still flashes that console — measured, not assumed. The headless pseudo-
console conhost.exe creates does not. It also means nothing is ever on screen
to read this script's own console text, so every notice below shows as a
popup (WScript.Shell) instead of pausing a console for Read-Host, and this
file captures opener.cmd's output and pops it up on a non-zero exit too (see
the tail). TASKOS_OPENER_DRYRUN=1 keeps the old plain-text behaviour and never
pops a window, so tests/test_opener.py stays hermetic.

install_opener.py / install.txt register this shape when the PC can run it and
fall back to the plain .cmd registration when a machine policy blocks script
files - a fallback that is reported, never silent, because it is the shape that
carries the risk above.

    -Url taskos://selftest   prints TASKOS_OPENER_PS_OK and exits (the probe
                             the installers use to pick the shape - deliberately
                             run unwrapped, bare powershell.exe: conhost.exe
                             --headless swallows the caller's stdout capture,
                             so the probe only needs to know the script runs)
#>
param([string]$Url)

$SelfTest = 'taskos://selftest'

if ($Url -eq $SelfTest) { 'TASKOS_OPENER_PS_OK'; exit 0 }

function Show-Notice {
    param([string[]]$Lines)
    if ($env:TASKOS_OPENER_DRYRUN) {
        Write-Host ''
        Write-Host '  task-os opener'
        Write-Host ''
        foreach ($l in $Lines) { Write-Host "  $l" }
        Write-Host ''
        return
    }
    # Headless (see the header) - nothing is on screen to pause, so pop a modal
    # the user can read and dismiss instead of Read-Host on an invisible console.
    $body = "task-os opener`n`n" + (($Lines | ForEach-Object { "  $_" }) -join "`n")
    (New-Object -ComObject WScript.Shell).Popup($body, 0, 'task-os opener', 0x0) | Out-Null
}

if ([string]::IsNullOrWhiteSpace($Url)) {
    Show-Notice @('No URL given. Usage: opener.ps1 -Url "taskos://open?ref=%7Bonedrive%7D%2Ffolder"')
    exit 2
}

# Every ref this app builds is percent-encoded (src/placeholders.py::opener_url
# uses quote(safe='')), so a literal quote never arrives from task-os itself. One
# that arrives anyway means the link was crafted or mangled somewhere else: stop
# and say so, rather than acting on half of a path.
if ($Url.Contains('"')) {
    Show-Notice @(
        'This link carries a quote character, which the app never sends.',
        'Nothing was opened.'
    )
    exit 3
}

# taskos://resume?session=<session_01…> — reopen a Claude Code session in a
# terminal on THIS PC (#77). The web session id is embedded in the local
# transcript (.jsonl) Claude Code wrote, so one recursive search maps it to the
# local session uuid and the project folder it ran in. Unknown here (another
# PC's session, pruned transcripts) -> open the conversation on the web instead.
# Env knobs (tests): TASKOS_OPENER_DRYRUN=1 prints "resume: <uuid> in <dir>" /
# "resume-web: <url>" instead of launching; TASKOS_OPENER_PROJECTS overrides
# the transcript root (default %USERPROFILE%\.claude\projects).
# Browsers normalise the custom scheme to taskos://resume/?session=… (slash
# before the query) — accept both, like opener.cmd does for open/?ref=.
if ($Url -match '^taskos://resume/?\?session=(session_[A-Za-z0-9]+)/?$') {
    $id = $Matches[1]
    $projects = if ($env:TASKOS_OPENER_PROJECTS) { $env:TASKOS_OPENER_PROJECTS }
                else { Join-Path $env:USERPROFILE '.claude\projects' }
    $hit = $null
    if (Test-Path -LiteralPath $projects) {
        $files = Get-ChildItem -LiteralPath $projects -Recurse -Filter *.jsonl -File -ErrorAction SilentlyContinue
        # A transcript that merely MENTIONS another session's id (a grep result,
        # a handoff note) must not shadow the owner: the owner carries the id in
        # its own session-url field. Only when no transcript carries that marker
        # fall back to a bare-id match (older transcript shapes).
        $marker = '"url":"https://claude.ai/code/' + $id + '"'
        $hit = $files |
            Where-Object { Select-String -LiteralPath $_.FullName -Pattern $marker -SimpleMatch -Quiet } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -eq $hit) {
            $hit = $files |
                Where-Object { Select-String -LiteralPath $_.FullName -Pattern $id -SimpleMatch -Quiet } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
        }
    }
    if ($null -eq $hit) {
        $web = "https://claude.ai/code/$id"
        if ($env:TASKOS_OPENER_DRYRUN) { "resume-web: $web"; exit 0 }
        Start-Process $web
        Show-Notice @("This PC has no local transcript for $id.", 'Opened the conversation on the web instead.')
        exit 0
    }
    $uuid = $hit.BaseName
    # the transcript records the repo it ran in ("cwd") - resume from there
    $dir = $env:USERPROFILE
    $line = Select-String -LiteralPath $hit.FullName -Pattern '"cwd":"((?:[^"\\]|\\.)*)"' | Select-Object -First 1
    if ($line -and $line.Matches[0].Groups[1].Value) {
        $raw = $line.Matches[0].Groups[1].Value -replace '\\\\', '\'
        if (Test-Path -LiteralPath $raw) { $dir = $raw }
    }
    if ($env:TASKOS_OPENER_DRYRUN) { "resume: $uuid in $dir"; exit 0 }
    # Never let the resumed session inherit a nested-run marker: launched from
    # inside another Claude session (an agent, a launcher-hosted shell), the
    # marker would silently turn transcript saving OFF in the resumed session.
    Remove-Item Env:CLAUDE_CODE_CHILD_SESSION -ErrorAction SilentlyContinue
    # Echo before claude starts: a long transcript takes a while to first
    # paint, and a silent black window reads as a failure.
    $inner = "Write-Host 'task-os opener - resuming $uuid' -ForegroundColor Cyan; Write-Host 'in $dir - the first paint of a long session can take a minute...'; claude --resume $uuid"
    if (Get-Command wt -ErrorAction SilentlyContinue) {
        Start-Process wt -ArgumentList '-d', $dir, 'powershell', '-NoProfile', '-NoExit', '-Command', $inner
    } else {
        Start-Process powershell -WorkingDirectory $dir -ArgumentList '-NoProfile', '-NoExit', '-Command', $inner
    }
    exit 0
}

$handler = Join-Path $PSScriptRoot 'opener.cmd'
if (-not (Test-Path -LiteralPath $handler)) {
    Show-Notice @("The handler is missing: $handler", 'Re-run the install command from Settings -> Folder opener.')
    exit 4
}

# The URL travels in the environment, never on a command line - see the header.
$env:TASKOS_OPENER_URL = $Url
if ($env:TASKOS_OPENER_DRYRUN) {
    # dry run: let the handler's own "open: <path>" / "missing: <path>" line
    # reach stdout untouched - tests read it directly, no popup involved
    & $handler
    exit $LASTEXITCODE
}
# Headless now (see the header): capture the handler's output instead of
# letting it print to a console nobody can see, and pop it up on failure.
$out = ((& $handler 2>&1) | Out-String).TrimEnd()
$code = $LASTEXITCODE
if ($code -ne 0 -and $out) {
    (New-Object -ComObject WScript.Shell).Popup($out, 0, 'task-os opener', 0x0) | Out-Null
}
exit $code
