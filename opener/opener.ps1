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

# Does this transcript carry the session id, and in which shape? 2 = the
# session-url marker (this is the owning transcript), 1 = a bare mention,
# 0 = neither.
#
# Reading the bytes here rather than shelling out to Select-String -Quiet: for a
# pure "does this file contain the literal" test a raw read measured ~7x faster
# on this PC's corpus, and one pass answers both questions instead of two. Read
# in chunks with an overlap the length of the longest needle so a match
# straddling a chunk boundary is still seen - the largest transcript on this PC
# is 61 MB and pulling one whole into a string would materialise twice that.
# FileShare ReadWrite because a live session holds its own transcript open.
#
# The read buffer is allocated once and reused: a fresh 1 MB char[] per file
# costs 25 GB of allocation churn across this PC's 12k transcripts, and cutting
# it took a full no-hit traversal from 12.1 s to 7.6 s (measured, #227).
$script:TranscriptBuf = $null
function Get-TranscriptMatch {
    param([string]$Path, [string]$Marker, [string]$Bare)
    if ($null -eq $script:TranscriptBuf) { $script:TranscriptBuf = [char[]]::new(1048576) }
    $buf = $script:TranscriptBuf
    $overlap = $Marker.Length - 1
    $found = 0
    try {
        $fs = [System.IO.FileStream]::new($Path, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $sr = $null
            $sr = [System.IO.StreamReader]::new($fs, [System.Text.Encoding]::UTF8)
            $tail = ''
            while (($n = $sr.Read($buf, 0, $buf.Length)) -gt 0) {
                $chunk = $tail + [string]::new($buf, 0, $n)
                # the marker embeds the bare id, so the cheap test rules out both
                # - which is the answer for all but a handful of files
                if ($chunk.Contains($Bare)) {
                    if ($chunk.Contains($Marker)) { return 2 }
                    $found = 1
                }
                $tail = if ($chunk.Length -gt $overlap) { $chunk.Substring($chunk.Length - $overlap) }
                        else { $chunk }
            }
        } finally {
            # the reader owns the stream once it is built, and Dispose is
            # idempotent - so disposing both also covers the StreamReader
            # constructor throwing, where only the stream exists
            if ($null -ne $sr) { $sr.Dispose() }
            $fs.Dispose()
        }
    } catch {
        # unreadable (locked, vanished mid-scan) - it simply is not the hit
        return $found
    }
    return $found
}

# taskos://resume?session=<session_01…> — reopen a Claude Code session in a
# terminal on THIS PC (#77). The web session id is embedded in the local
# transcript (.jsonl) Claude Code wrote, so one recursive search maps it to the
# local session uuid and the project folder it ran in. Unknown here (another
# PC's session, pruned transcripts) -> open the conversation on the web instead.
# Env knobs (tests): TASKOS_OPENER_DRYRUN=1 prints "resume: <uuid> in <dir>"
# plus "resume-exec: <argv>" / "resume-web: <url>" instead of launching;
# TASKOS_OPENER_PROJECTS overrides the transcript root (default
# %USERPROFILE%\.claude\projects); TASKOS_OPENER_WT=1/0 forces the Windows
# Terminal branch on or off instead of probing for wt.
# Browsers normalise the custom scheme to taskos://resume/?session=… (slash
# before the query) — accept both, like opener.cmd does for open/?ref=.
if ($Url -match '^taskos://resume/?\?session=(session_[A-Za-z0-9]+)/?$') {
    $id = $Matches[1]
    $projects = if ($env:TASKOS_OPENER_PROJECTS) { $env:TASKOS_OPENER_PROJECTS }
                else { Join-Path $env:USERPROFILE '.claude\projects' }
    $hit = $null
    if (Test-Path -LiteralPath $projects) {
        # Newest first, and stop at the first owner. The marker sits near the top
        # of a transcript (the line Claude Code writes when the session is
        # bridged), so the owning file is normally the first or second one read.
        # The old shape filtered *then* sorted, and Sort-Object blocks the
        # pipeline - so Select-Object -First 1 could not stop the upstream filter
        # and every one of this PC's 12k transcripts was read on every resume
        # (~170 s), twice over on a miss (#227).
        $files = Get-ChildItem -LiteralPath $projects -Recurse -Filter *.jsonl -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
        # A transcript that merely MENTIONS another session's id (a grep result,
        # a handoff note) must not shadow the owner: the owner carries the id in
        # its own session-url field. Only when no transcript carries that marker
        # fall back to a bare-id match (older transcript shapes) - recorded as we
        # pass it, so a miss costs one traversal rather than two.
        $marker = '"url":"https://claude.ai/code/' + $id + '"'
        $bareHit = $null
        foreach ($f in $files) {
            $m = Get-TranscriptMatch -Path $f.FullName -Marker $marker -Bare $id
            if ($m -eq 2) { $hit = $f; break }
            if ($m -eq 1 -and $null -eq $bareHit) { $bareHit = $f }
        }
        if ($null -eq $hit) { $hit = $bareHit }
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
    # Echo before claude starts: a long transcript takes a while to first
    # paint, and a silent black window reads as a failure. Single-quote the
    # only interpolated path so a quote in it cannot end the string.
    $shown = $dir -replace "'", "''"
    $inner = "Write-Host 'task-os opener - resuming $uuid' -ForegroundColor Cyan; Write-Host 'in $shown - the first paint of a long session can take a minute...'; claude --resume $uuid"
    # Hand that to the terminal as one base64 token. `;` is Windows Terminal's
    # own new-tab delimiter and wt splits on one *before* it considers the
    # quoting of the argument, so a `;`-separated -Command turned one resume
    # into three tabs: a bare prompt, a tab that tried to run `Write-Host` as an
    # executable (0x80070002), and a `claude` that never saw -d and so started
    # in system32 (#227). The base64 alphabet contains no `;`, nothing can
    # split, and -NoExit still applies.
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($inner))
    # -d is the one part of the tab's directory wt reads off its command line,
    # so escape a `;` there too rather than trust that no repo path carries one.
    $wtDir = $dir -replace ';', '\;'
    # TASKOS_OPENER_WT (tests) forces the branch either way; otherwise ask.
    $useWt = if ($env:TASKOS_OPENER_WT) { $env:TASKOS_OPENER_WT -eq '1' }
             else { [bool](Get-Command wt -ErrorAction SilentlyContinue) }
    $argv = if ($useWt) { @('-d', $wtDir, 'powershell', '-NoProfile', '-NoExit', '-EncodedCommand', $encoded) }
            else { @('-NoProfile', '-NoExit', '-EncodedCommand', $encoded) }
    if ($env:TASKOS_OPENER_DRYRUN) {
        "resume: $uuid in $dir"
        # the argv too: TASKOS_OPENER_DRYRUN used to return before the launch
        # code, which is why the three-tab shape shipped with green tests
        $exe = if ($useWt) { 'wt' } else { "powershell -WorkingDirectory $dir" }
        "resume-exec: $exe $($argv -join ' ')"
        exit 0
    }
    # Never let the resumed session inherit a nested-run marker: launched from
    # inside another Claude session (an agent, a launcher-hosted shell), the
    # marker would silently turn transcript saving OFF in the resumed session.
    Remove-Item Env:CLAUDE_CODE_CHILD_SESSION -ErrorAction SilentlyContinue
    if ($useWt) {
        Start-Process wt -ArgumentList $argv
    } else {
        Start-Process powershell -WorkingDirectory $dir -ArgumentList $argv
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
