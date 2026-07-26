# test.ps1 - run all validation layers (Windows).
#
# Layers:
#   1. pytest -m unit              (Python unit tests, no DB needed)
#   2. SQL test suite              (5 suites against deployed env, needs PG)
#   3. evals/runner.py             (Tier P offline + Tier I/S need PG)
#
# Usage:
#   .\scripts\test.ps1                    # all three layers
#   .\scripts\test.ps1 -SkipSql           # skip SQL suite (no PG)
#   .\scripts\test.ps1 -SkipEvals         # skip evals
#   .\scripts\test.ps1 -OnlyPython        # only pytest
#   .\scripts\test.ps1 -Env dev           # target env for SQL suite (default dev)
#
# Exit codes:
#   0 = all selected layers passed
#   1 = at least one layer failed
#   2 = prereq missing

[CmdletBinding()]
param(
    [string]$Env = "dev",
    [switch]$SkipSql,
    [switch]$SkipEvals,
    [switch]$OnlyPython,
    [switch]$Verbose
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Push-Location $ProjectRoot

$Results = @()
function Record { param([string]$Layer, [bool]$Pass, [string]$Detail = "")
    $script:Results += [pscustomobject]@{ Layer = $Layer; Pass = $Pass; Detail = $Detail }
}

try {
    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host " PostgreDataMigrationApp - test" -ForegroundColor Cyan
    Write-Host " env         : $Env" -ForegroundColor Cyan
    Write-Host " python      : $(if ($SkipSql -or $SkipEvals -or $OnlyPython) {'yes'} else {'yes'})" -ForegroundColor Cyan
    Write-Host " sql suite   : $(if ($SkipSql -or $OnlyPython) {'SKIP'} else {'yes'})" -ForegroundColor Cyan
    Write-Host " evals       : $(if ($SkipEvals -or $OnlyPython) {'SKIP'} else {'yes'})" -ForegroundColor Cyan
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host ""

    # --- Layer 1: Python unit tests ---
    Write-Host "[layer 1] pytest -m unit" -ForegroundColor Yellow
    if (Get-Command pytest -ErrorAction SilentlyContinue) {
        & pytest -m unit --tb=short 2>&1 | Tee-Object -Variable PytestOutput
        $pass = $LASTEXITCODE -eq 0
        Record -Layer 'pytest unit' -Pass $pass -Detail "exit=$LASTEXITCODE"
        Write-Host "[layer 1] $(if ($pass) {'PASS'} else {'FAIL'})" -ForegroundColor $(if ($pass) {'Green'} else {'Red'})
    } else {
        Write-Host "[layer 1] FAIL: pytest not installed" -ForegroundColor Red
        Write-Host "    Run: pip install -r requirements-dev.txt" -ForegroundColor Yellow
        Record -Layer 'pytest unit' -Pass $false -Detail 'pytest missing — pip install -r requirements-dev.txt'
    }

    # --- Layer 2: SQL test suite ---
    if (-not ($SkipSql -or $OnlyPython)) {
        Write-Host ""
        Write-Host "[layer 2] SQL test suite (env=$Env)" -ForegroundColor Yellow
        if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
            Write-Host "[layer 2] SKIP: psql not on PATH" -ForegroundColor Yellow
            Record -Layer 'sql suite' -Pass $true -Detail 'skipped: psql missing'
        } elseif (-not $env:PGPASSWORD) {
            Write-Host "[layer 2] SKIP: PGPASSWORD not set" -ForegroundColor Yellow
            Record -Layer 'sql suite' -Pass $true -Detail 'skipped: env vars'
        } else {
            $TestRunner = Join-Path $ProjectRoot 'tests\run_tests.sh'
            if (Test-Path $TestRunner) {
                & bash tests/run_tests.sh $Env
                $pass = $LASTEXITCODE -eq 0
                Record -Layer 'sql suite' -Pass $pass -Detail "exit=$LASTEXITCODE"
                Write-Host "[layer 2] $(if ($pass) {'PASS'} else {'FAIL'})" -ForegroundColor $(if ($pass) {'Green'} else {'Red'})
            } else {
                Write-Host "[layer 2] SKIP: tests/run_tests.sh not found" -ForegroundColor Yellow
                Record -Layer 'sql suite' -Pass $true -Detail 'skipped: runner missing'
            }
        }
    }

    # --- Layer 3: evals ---
    if (-not ($SkipEvals -or $OnlyPython)) {
        Write-Host ""
        Write-Host "[layer 3] evals/runner.py" -ForegroundColor Yellow
        $Runner = Join-Path $ProjectRoot 'evals\runner.py'
        if (Test-Path $Runner) {
            $tiers = if ($env:PGHOST -and $env:PGPASSWORD) { 'p,i,s' } else { 'p' }
            & python evals\runner.py --tiers $tiers
            $pass = $LASTEXITCODE -eq 0
            Record -Layer "evals ($tiers)" -Pass $pass -Detail "exit=$LASTEXITCODE"
            Write-Host "[layer 3] $(if ($pass) {'PASS'} else {'FAIL'})" -ForegroundColor $(if ($pass) {'Green'} else {'Red'})
        } else {
            Write-Host "[layer 3] SKIP: evals/runner.py not found" -ForegroundColor Yellow
            Record -Layer 'evals' -Pass $true -Detail 'skipped: runner missing'
        }
    }

    # --- Summary ---
    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host " Summary" -ForegroundColor Cyan
    Write-Host "===========================================================" -ForegroundColor Cyan
    $Results | ForEach-Object {
        $sym = if ($_.Pass) { 'PASS' } else { 'FAIL' }
        $color = if ($_.Pass) { 'Green' } else { 'Red' }
        Write-Host ("  {0,-20} {1}  {2}" -f $_.Layer, $sym, $_.Detail) -ForegroundColor $color
    }
    Write-Host ""

    $failed = ($Results | Where-Object { -not $_.Pass } | Measure-Object).Count
    if ($failed -eq 0) {
        Write-Host "All layers passed." -ForegroundColor Green
        exit 0
    } else {
        Write-Host "$failed layer(s) failed." -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}
