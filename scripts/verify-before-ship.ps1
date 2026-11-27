#Requires -Version 5.1
<#
.SYNOPSIS
    Pre-ship verification gate for task-os. One pass/fail pipeline.

.DESCRIPTION
    Stages, fail-fast:
      1. byte-compile      — every .py under app/ src/ scripts/ tests/ parses (scripts/launcher.py included)
      2. ruff              — lint the whole repo (pyproject.toml owns strictness)
      3. static ratchet    — no new duplicate block (jscpd via npx), unused
                             import/variable (ruff F401,F841) or likely-bug /
                             security pattern (curated ruff B and S codes) beyond
                             .static-ratchet-baseline.json. Whole tree, never
                             routed; exit 3 (a detector could not run) is
                             NOT CONFIRMED and fails, never a pass or a skip.
      4. docs ratchet      — README.md within 40 KiB and no new history marker (issue
                             reference, dated or changelog heading) in README.md or
                             docs/**/*.md beyond .docs-ratchet-baseline.json. Whole
                             tree, never routed; exit 3 (count not established) is
                             NOT CONFIRMED and fails, never a pass or a skip.
      5. structure ratchet — no new file over 1,000 lines, function over 100 lines or
                             directory over 40 modules, no src/ import of app/, and the
                             root folders match `shape` + `extra_roots`, beyond
                             .structure-ratchet-baseline.json. Whole tree, never
                             routed; exit 3 (tree not measured) is NOT CONFIRMED and
                             fails, never a pass or a skip.
      6. instruction ratchet — no new instruction-file lint hit (CLAUDE.md, AGENTS.md,
                             skills) or size-cap breach beyond
                             .instruction-ratchet-baseline.json. Whole tree, never
                             routed; exit 3 (files not measured) is NOT CONFIRMED
                             and fails, never a pass or a skip.
      7. doc-refs ratchet  — no README.md / CLAUDE.md / docs/**/*.md reference to a repo
                             path, python -m module, relative link or loopback port that
                             does not exist, beyond .doc-refs-ratchet-baseline.json.
                             Whole tree, never routed (a code move strands a doc without
                             touching it); exit 3 (docs not read) is NOT CONFIRMED and
                             fails, never a pass or a skip.
      8. dead-code ratchet — no new function, class or method that nothing references,
                             beyond .dead-code-ratchet-baseline.json. Whole tree, never
                             routed (deleting the last caller in one file strands a
                             definition in another); exit 3 (a file not parsed) is NOT
                             CONFIRMED and fails, never a pass or a skip.
      9. conventions ratchet — no rule hit above .conventions-ratchet-baseline.json for
                             no-window (subprocess spawns), logging-not-print (library
                             code) or no-drive-path (hardcoded drive literals). Whole
                             tree, never routed (a new rule must see every file); exit 3
                             (a file not parsed) is NOT CONFIRMED and fails, never a
                             pass or a skip.
     10. comment ratchet   — no new `#NNN` issue reference in a product-code comment
                             (.py, .js, .css, .ps1) beyond .comment-ratchet-baseline.json.
                             Whole tree, never routed (a count needs every file); exit 3
                             (a file not scanned) is NOT CONFIRMED and fails, never a
                             pass or a skip.
     10b. runtime write ratchet — no new write target resolving under a code folder
                             beyond .runtime-write-ratchet-baseline.json, through
                             scripts/runtime_write_ratchet_gate.py. Whole tree, never
                             routed; exit 3 (a new target it cannot resolve) is NOT
                             CONFIRMED and fails, never a pass or a skip.
     10c. usage track ratchet — no file's count of untracked controls, untracked
                             sheets or built ids above .usage-track-ratchet-baseline.json,
                             and the usage log wired, through
                             scripts/usage_track_ratchet_gate.py. Whole tree, never routed;
                             an exit 3 (a file that cannot be read or closed) is NOT
                             CONFIRMED and fails, never a pass or a skip.
     10d. ux surface ratchet — no surface root without a constant data-surface id, no
                             id without an entry in docs/ux-surfaces.yaml, no entry no
                             element carries, no id on two surfaces, no link to an id
                             with no entry, and a docs/ux-surface-map.md page that is
                             what the map generates, beyond
                             .ux-surface-ratchet-baseline.json, through
                             scripts/ux_surface_ratchet_gate.py. Whole tree, never routed;
                             an exit 3 (a file that cannot be read or closed) is NOT
                             CONFIRMED and fails, never a pass or a skip.
     10e. request budget ratchet — no file's count of fixed-rate server polls, polls
                             under 2 s, undeclared fast server loops, directory scans in a
                             request handler or shared-default-pool submits above
                             .request-budget-ratchet-baseline.json, and the request-timing
                             middleware mounted, through
                             scripts/request_budget_ratchet_gate.py. Whole tree, never
                             routed; an exit 3 (a file that cannot be read or parsed) is NOT
                             CONFIRMED and fails, never a pass or a skip.
     10f. windows only ratchet — no file's count of unmarked Windows-only tests (a
                             Windows-only module or API, a Windows-only environment
                             variable read, a planted `.exe` install) above
                             .windows-only-ratchet-baseline.json, through
                             scripts/windows_only_ratchet_gate.py. Whole tree, never
                             routed; an exit 3 (a test module that cannot be listed, read
                             or parsed) is NOT CONFIRMED and fails, never a pass or a skip.
     10g. install standard ratchet — no installer module missing, undeclared or behind the
                             scaffold's, no unparseable [install.migrate] and no missing
                             Install, Update or Migrate section in docs/install.md beyond
                             .ratchets/install-standard.json, through
                             scripts/install_standard_ratchet_gate.py. Whole tree, never
                             routed; an exit 3 (a module or the playbook that cannot be
                             read) is NOT CONFIRMED and fails, never a pass or a skip.
     11. pytest (unit)    — hermetic suite, tests/e2e excluded; a runtime write
                             --snapshot is taken first
     12. pytest (e2e)      — diff-proportionate: the browser slice is routed by
                             scripts/classify_e2e.py against .fleet.toml [e2e]
                             (skip / static / full), fail-safe to full. The
                             suite boots its own disposable webapp on a free
                             port with a temp DB — never the live :8448.
     13. gallery baseline  — whatever shots stage 12 rewrote, compared against
                             the committed ones and then restored, so a
                             verification run neither hides gallery drift nor
                             leaves rewritten PNGs behind. Re-baselining
                             is deliberate: run `pytest tests/e2e` yourself,
                             review what moved, `git add docs/screenshots`.
     14. runtime write probe — scripts/runtime_write_ratchet.py --probe against the
                             stage-11 snapshot: fails on any untracked or ignored
                             file stages 11-13 left under a code folder.

    Anchors to the repo root, so run it from anywhere:
        & .\scripts\verify-before-ship.ps1
    Restarting the live app afterwards is a separate step (CLAUDE.md
    "Restart recipe"): tray.bat --restart, then /api/version git_sha == HEAD.

    Verdict line: the last line on stdout is `GATE-RESULT: PASS` or
    `GATE-RESULT: FAIL`, on every path that can still run code. Never pipe the
    gate when its exit code matters (a pipeline reports its last command's
    status, so `... | tail -40` turns a red run green); a caller that cannot
    avoid a pipe asserts on that line. A run with no such line is not a pass.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# gate-verdict:begin
# The verdict is the last stdout line of every path that can still run code. A
# terminating error under the "Stop" preference above would otherwise print to
# stderr only and exit 1, leaving a piped caller an empty, apparently clean run,
# so the trap reports it on stdout first. Exit codes stay 0 (pass) and 1 (fail).
function Write-GateResult($verdict) {
    Write-Host "GATE-RESULT: $verdict"
}

function Complete-Gate([int]$Code) {
    Write-GateResult $(if ($Code -eq 0) { "PASS" } else { "FAIL" })
    exit $Code
}

trap {
    Write-Host ""
    Write-Host "[FAIL] the gate aborted on an unhandled error:" -ForegroundColor Red
    Write-Host ("       {0}" -f $_.Exception.Message) -ForegroundColor Red
    Complete-Gate 1
}

function Invoke-Stage {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host ">> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        Complete-Gate 1
    }
    Write-Host "[PASS] $Name" -ForegroundColor Green
}
# gate-verdict:end

Set-Location (Join-Path $PSScriptRoot "..")

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "[FAIL] .venv not found at $py" -ForegroundColor Red
    Write-Host "       Create it: py -m venv .venv; then $py -m pip install -r requirements.txt" -ForegroundColor Red
    Complete-Gate 1
}

# Piped/redirected stdout makes Python fall back to cp1252 on Windows and the
# emoji log markers then throw UnicodeEncodeError (global CLAUDE.md gotcha).
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# Loaded as text, not dot-sourced from its file: under an AllSigned execution policy a dot-sourced
# unsigned file is refused, while a ScriptBlock made from its text runs with the policy unchanged.
. ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $PSScriptRoot "box_lock_gate.ps1")))); Enter-BoxLockGate

Invoke-Stage "byte-compile"            { & $py -m compileall -q app src scripts tests assets }
Invoke-Stage "ruff"                    { & $py -m ruff check . }
# The wrapper maps the script's exit 3 to NOT CONFIRMED (tests/gates/test_static_ratchet_gate.py
# pins it); call it, never scripts/static_ratchet.py directly.
Invoke-Stage "static ratchet"          { & $py -m scripts.static_ratchet_gate }
# Same wrapper shape: it maps the docs script's exit 3 to NOT CONFIRMED
# (tests/gates/test_docs_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "docs ratchet"            { & $py -m scripts.docs_ratchet_gate }
# Same wrapper shape: it maps the layout script's exit 3 to NOT CONFIRMED
# (tests/gates/test_structure_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "structure ratchet"       { & $py -m scripts.structure_ratchet_gate }
# Same wrapper shape: it maps the instruction script's exit 3 to NOT CONFIRMED
# (tests/gates/test_instruction_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "instruction ratchet"     { & $py -m scripts.instruction_ratchet_gate }
# Same wrapper shape: it maps the doc-refs script's exit 3 to NOT CONFIRMED
# (tests/gates/test_doc_refs_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "doc-refs ratchet"        { & $py -m scripts.doc_refs_ratchet_gate }
# Same wrapper shape: it maps the dead-code script's exit 3 to NOT CONFIRMED
# (tests/gates/test_dead_code_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "dead-code ratchet"       { & $py -m scripts.dead_code_ratchet_gate }
# Same wrapper shape: it maps the conventions script's exit 3 to NOT CONFIRMED
# (tests/gates/test_conventions_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "conventions ratchet"     { & $py -m scripts.conventions_ratchet_gate }
# Same wrapper shape: it maps the comment script's exit 3 to NOT CONFIRMED
# (tests/gates/test_comment_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "comment ratchet"         { & $py -m scripts.comment_ratchet_gate }
# Same wrapper shape: it maps the runtime write script's exit 3 to NOT CONFIRMED
# (tests/gates/test_runtime_write_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "runtime write ratchet"   { & $py -m scripts.runtime_write_ratchet_gate }
# Same wrapper shape: it maps the usage track script's exit 3 to NOT CONFIRMED
# (tests/gates/test_usage_track_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "usage track ratchet"     { & $py -m scripts.usage_track_ratchet_gate }
# Same wrapper shape: it maps the UX surface script's exit 3 to NOT CONFIRMED
# (tests/gates/test_ux_surface_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "ux surface ratchet"      { & $py -m scripts.ux_surface_ratchet_gate }
# Same wrapper shape: it maps the request budget script's exit 3 to NOT CONFIRMED
# (tests/gates/test_request_budget_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "request budget ratchet"  { & $py -m scripts.request_budget_ratchet_gate }
# Same wrapper shape: it maps the windows-only script's exit 3 to NOT CONFIRMED
# (tests/gates/test_windows_only_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "windows only ratchet"    { & $py -m scripts.windows_only_ratchet_gate }
# Same wrapper shape: it maps the install standard script's exit 3 to NOT CONFIRMED
# (tests/gates/test_install_standard_ratchet_gate.py pins it). Whole tree, never routed.
Invoke-Stage "install standard ratchet" { & $py -m scripts.install_standard_ratchet_gate }
# Runtime write probe, first half: what already sits untracked or ignored under
# the code folders, so the probe after the tests names only what they wrote.
$runtimeSnapshot = Join-Path ([IO.Path]::GetTempPath()) "runtime-write-snapshot-$PID.json"
Invoke-Stage "runtime write probe (snapshot)" { & $py "scripts/runtime_write_ratchet.py" --snapshot $runtimeSnapshot }
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
    # one pytest argument holding a space is "file or directory not found".
    $e2eArgs = @($e2eTarget -split '\s+' | Where-Object { $_ })
    foreach ($b in ($e2eBrowsers -split ',' | Where-Object { $_ })) {
        $e2eArgs += @("--browser", $b)
    }
    # Per-test seconds for /e2e-audit (`.fleet.toml [e2e] junit_xml`). Only a
    # full-tier run is the suite's record: a slice would replace it with a few
    # nodes. data/ is gitignored, so scripts/e2e_record_path.py names the file in
    # the primary checkout; a worktree's own copy would go with the worktree.
    if ($tier -eq "full") {
        $junit = ""
        foreach ($line in (& $py "scripts/e2e_record_path.py")) {
            if ($line -match '^E2E_JUNIT=(.+)$') { $junit = $matches[1] }
            elseif ($line -match '^E2E_JUNIT_NOTE=(.+)$') { Write-Host "   timing record: $($matches[1])" -ForegroundColor Yellow }
        }
        if ($junit) {
            $e2eArgs += @("--junitxml", $junit)
            Write-Host "   timing record: $junit" -ForegroundColor DarkGray
        } else {
            Write-Host "   timing record: NOT CONFIRMED - no path was named, this run records none" -ForegroundColor Yellow
        }
    }
    $label = if ($e2eBrowsers) { $e2eBrowsers } else { "suite-default" }
    # The full tier runs on pytest-xdist workers: --dist loadfile keeps a
    # story module (and its module-scoped instance) on one worker, the
    # controller alone names the run's work root, and instance boots are
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

# ------------------------------------------------- gallery baseline
# Runs on every tier, including `skip`: with no shot rewritten it is a no-op
# that costs a `git diff`. It is what makes docs/screenshots/ a baseline rather
# than a folder of pictures — two fresh runs agreeing proves only that the
# capture is stable, never that the gallery still matches the code.
Invoke-Stage "gallery baseline (committed vs regenerated)" { & $py -m scripts.shot_determinism --check-tree }

# After the gallery baseline, never before it: the one budget test lives inside
# the open story, and WebKit renders its shots differently from the committed
# Chromium ones, which the baseline would read as drift. The rerun saves its
# shots to a scratch folder (TASKOS_SHOTS_DIR) so the tracked gallery is never
# written: a restore afterwards would destroy a deliberate re-baseline and leave
# the tree dirty, and so unable to carry gate evidence, whenever the run is cut short.
if ($tier -eq "skip") {
    Write-Host "[SKIP] request budget on webkit - no e2e surface touched" -ForegroundColor DarkGray
} elseif ($tier -eq "static") {
    Write-Host "[SKIP] request budget on webkit - an inert-asset diff runs only the smoke target" -ForegroundColor DarkGray
} else {
    # The Mac nightly runs the request-budget tests on WebKit, which the Chromium
    # slice above never does. 0 passed; 4 (WebKit not installed) and 5 (the repo
    # has no budget test) are "not run", printed as such and never as a pass;
    # anything else, 3 (not confirmed) included, fails the gate.
    Write-Host ""
    Write-Host ">> request budget on webkit" -ForegroundColor Cyan
    $galleryBefore = (& git status --porcelain -- docs/screenshots) -join "`n"
    $webkitShots = Join-Path ([IO.Path]::GetTempPath()) "taskos-webkit-shots-$PID"
    $env:TASKOS_SHOTS_DIR = $webkitShots
    try {
        & $py "scripts/tools/webkit_budget_check.py"
        $webkitBudget = $LASTEXITCODE
    } finally {
        Remove-Item Env:TASKOS_SHOTS_DIR -ErrorAction SilentlyContinue
        if (Test-Path $webkitShots) { Remove-Item -Recurse -Force $webkitShots }
    }
    $galleryAfter = (& git status --porcelain -- docs/screenshots) -join "`n"
    if ($galleryAfter -ne $galleryBefore) {
        Write-Host "[FAIL] request budget on webkit: the run changed docs/screenshots" -ForegroundColor Red
        Complete-Gate 1
    }
    if ($webkitBudget -eq 0) {
        Write-Host "[PASS] request budget on webkit" -ForegroundColor Green
    } elseif ($webkitBudget -eq 4) {
        Write-Host "[NOT RUN] request budget on webkit - WebKit is not installed here, so the nightly's engine was not checked" -ForegroundColor Yellow
    } elseif ($webkitBudget -eq 5) {
        Write-Host "[NOT RUN] request budget on webkit - no request-budget test in this repo" -ForegroundColor Yellow
    } else {
        Write-Host "[FAIL] request budget on webkit (exit $webkitBudget)" -ForegroundColor Red
        Complete-Gate 1
    }
}

# Runtime write probe, second half: any file the unit and e2e runs left under a
# code folder (the snapshot was taken before stage 11).
Invoke-Stage "runtime write probe" { & $py "scripts/runtime_write_ratchet.py" --probe $runtimeSnapshot }

Write-Host ""
Write-Host "[PASS] all checks green - safe to ship." -ForegroundColor Green
Complete-Gate 0
