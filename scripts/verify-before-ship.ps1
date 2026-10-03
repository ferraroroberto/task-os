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
      5. gallery baseline  — whatever shots stage 4 rewrote, compared against
                             the committed ones and then restored, so a
                             verification run neither hides gallery drift nor
                             leaves rewritten PNGs behind (#225). Re-baselining
                             is deliberate: run `pytest tests/e2e` yourself,
                             review what moved, `git add docs/screenshots`.

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

Invoke-Stage "byte-compile"            { & $py -m compileall -q app src scripts tests opener launcher.py }
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
    # The classifier space-joins several targets (a diff touching two e2e modules);
    # one pytest argument holding a space is "file or directory not found" (#277).
    $e2eArgs = @($e2eTarget -split '\s+' | Where-Object { $_ })
    foreach ($b in ($e2eBrowsers -split ',' | Where-Object { $_ })) {
        $e2eArgs += @("--browser", $b)
    }
    # Per-test seconds for /e2e-audit (`.fleet.toml [e2e] junit_xml`); data/ is gitignored.
    $e2eArgs += @("--junitxml", "data/e2e-junit.xml")
    $label = if ($e2eBrowsers) { $e2eBrowsers } else { "suite-default" }
    # The full tier runs on pytest-xdist workers (#288): --dist loadfile keeps a
    # story module (and its module-scoped instance) on one worker, the
    # controller alone holds the work-root lock, and instance boots are
    # serialised. Four, because the evidence run (CLAUDE.md "Runtime contract")
    # found 6 and 8 buy 10 s more at the cost of a loaded box. The narrower
    # tiers are one or two files and stay serial. TASKOS_E2E_WORKERS=1 is the
    # serial control; any other number overrides the four.
    $workers = 4
    if ($env:TASKOS_E2E_WORKERS) { $workers = [int]$env:TASKOS_E2E_WORKERS }
    if ($tier -eq "full" -and $workers -gt 1) {
        $e2eArgs += @("-n", "$workers", "--dist", "loadfile")
        $label = "$label, -n $workers"
    }
    Invoke-Stage "pytest e2e (${tier}: $e2eTarget, $label)" { & $py -m pytest @e2eArgs }
}

# ------------------------------------------------- gallery baseline (#225)
# Runs on every tier, including `skip`: with no shot rewritten it is a no-op
# that costs a `git diff`. It is what makes docs/screenshots/ a baseline rather
# than a folder of pictures — two fresh runs agreeing proves only that the
# capture is stable, never that the gallery still matches the code.
Invoke-Stage "gallery baseline (committed vs regenerated)" { & $py -m scripts.shot_determinism --check-tree }

Write-Host ""
Write-Host "[PASS] all checks green - safe to ship." -ForegroundColor Green
