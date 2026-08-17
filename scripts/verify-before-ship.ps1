#Requires -Version 5.1
<#
.SYNOPSIS
    Pre-ship verification gate for task-os. One pass/fail pipeline.

.DESCRIPTION
    Stages, fail-fast:
      1. byte-compile      — every .py under app/ src/ scripts/ tests/ + launcher.py parses
      2. ruff              — lint the whole repo (pyproject.toml owns strictness)
      3. pytest (unit)     — hermetic suite, tests/e2e excluded
      4. pytest (e2e)      — diff-proportionate: the browser slice is routed by
                             scripts/classify_e2e.py against .fleet.toml [e2e]
                             (skip / static / full), fail-safe to full. The
                             suite boots its own disposable webapp on a free
                             port with a temp DB — never the live :8448.

    Anchors to the repo root, so run it from anywhere:
        & .\scripts\verify-before-ship.ps1
    Restarting the live app afterwards is a separate step (CLAUDE.md
    "Restart recipe"): tray.bat --restart, then /api/version git_sha == HEAD.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "[FAIL] .venv not found at $py" -ForegroundColor Red
    Write-Host "       Create it: py -m venv .venv; then $py -m pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

# Piped/redirected stdout makes Python fall back to cp1252 on Windows and the
# emoji log markers then throw UnicodeEncodeError (global CLAUDE.md gotcha).
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Stage {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host ">> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Write-Host "[PASS] $Name" -ForegroundColor Green
}

Invoke-Stage "byte-compile"            { & $py -m compileall -q app src scripts tests launcher.py }
Invoke-Stage "ruff"                    { & $py -m ruff check . }
Invoke-Stage "pytest (unit, non-e2e)"  { & $py -m pytest --ignore=tests/e2e }

# ---------------------------------------------------------------- e2e routing
$tier = "full"; $e2eTarget = "tests/e2e"; $e2eBrowsers = ""; $routeReason = ""
if ($env:CI -eq "true") {
    $routeReason = "CI always runs the full e2e suite"
} else {
    $classifyOut = & $py "scripts/classify_e2e.py"
    $kv = @{}
    foreach ($line in $classifyOut) {
        if ($line -match '^(E2E_[A-Z_]+)=(.*)$') { $kv[$matches[1]] = $matches[2] }
    }
    if ($kv.ContainsKey("E2E_TIER") -and $kv["E2E_TIER"]) {
        $tier = $kv["E2E_TIER"]
        $e2eTarget = $kv["E2E_PYTEST_TARGET"]
        $e2eBrowsers = $kv["E2E_BROWSERS"]
        $routeReason = $kv["E2E_REASON"]
    } else {
        $routeReason = "classifier gave no verdict -- defaulting to full (fail-safe)"
    }
}

if ($tier -eq "skip") {
    Write-Host ""
    Write-Host ">> e2e routing: SKIP browser suite (no e2e surface touched)" -ForegroundColor Cyan
    Write-Host "   reason: $routeReason" -ForegroundColor DarkGray
    Write-Host "[PASS] pytest (e2e) - skipped, diff touches no e2e surface" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host ">> e2e routing: $tier" -ForegroundColor Cyan
    Write-Host "   reason: $routeReason" -ForegroundColor DarkGray
    $e2eArgs = @($e2eTarget)
    foreach ($b in ($e2eBrowsers -split ',' | Where-Object { $_ })) {
        $e2eArgs += @("--browser", $b)
    }
    $label = if ($e2eBrowsers) { $e2eBrowsers } else { "suite-default" }
    Invoke-Stage "pytest e2e (${tier}: $e2eTarget, $label)" { & $py -m pytest @e2eArgs }
}

Write-Host ""
Write-Host "[PASS] all checks green - safe to ship." -ForegroundColor Green
