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

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File opener.ps1 -Url "%1"

install_opener.py / install.txt register this shape when the PC can run it and
fall back to the plain .cmd registration when a machine policy blocks script
files - a fallback that is reported, never silent, because it is the shape that
carries the risk above.

    -Url taskos://selftest   prints TASKOS_OPENER_PS_OK and exits (the probe
                             the installers use to pick the shape)
#>
param([string]$Url)

$SelfTest = 'taskos://selftest'

if ($Url -eq $SelfTest) { 'TASKOS_OPENER_PS_OK'; exit 0 }

function Show-Notice {
    param([string[]]$Lines)
    Write-Host ''
    Write-Host '  task-os opener'
    Write-Host ''
    foreach ($l in $Lines) { Write-Host "  $l" }
    Write-Host ''
    if (-not $env:TASKOS_OPENER_DRYRUN) { Read-Host 'Press Enter to close' | Out-Null }
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

$handler = Join-Path $PSScriptRoot 'opener.cmd'
if (-not (Test-Path -LiteralPath $handler)) {
    Show-Notice @("The handler is missing: $handler", 'Re-run the install command from Settings -> Folder opener.')
    exit 4
}

# The URL travels in the environment, never on a command line - see the header.
$env:TASKOS_OPENER_URL = $Url
& $handler
exit $LASTEXITCODE
