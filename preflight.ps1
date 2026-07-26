# preflight.ps1 - pre-deploy smoke checks for PostgreDataMigrationApp (Windows)
#
# Usage:
#   .\preflight.ps1                       # check everything
#   .\preflight.ps1 -SkipPg               # don't try to connect to PostgreSQL
#   .\preflight.ps1 -Azure                # also check Azure CLI + Docker
#
# Exit codes:
#   0 = all required checks passed
#   1 = at least one required check failed
#   2 = at least one optional check warned (other required passed)
#
# What this catches BEFORE you waste time on a failed deploy:
#   - missing psql / python / git
#   - PG not running, wrong port, wrong password
#   - libpq env vars not set or pointing at wrong server
#   - dirty git tree (uncommitted changes that might not deploy)
#   - on -Azure: missing az CLI or Docker

[CmdletBinding()]
param(
    [switch]$SkipPg,
    [switch]$Azure
)

$ErrorActionPreference = 'Continue'  # keep going after failures so we report ALL of them

$script:Pass     = 0
$script:Warn     = 0
$script:Fail     = 0
$script:Results  = @()

function Test-Check {
    param(
        [string]$Name,
        [scriptblock]$Block,
        [switch]$Optional,
        [string]$FixHint = ''
    )
    Write-Host -NoNewline "  [$Name] ... "
    try {
        $result = & $Block
        if ($result) {
            Write-Host "PASS" -ForegroundColor Green
            $script:Pass++
            $script:Results += [pscustomobject]@{ Name = $Name; Status = 'PASS'; Detail = $result }
        } else {
            if ($Optional) {
                Write-Host "WARN" -ForegroundColor Yellow
                $script:Warn++
                $script:Results += [pscustomobject]@{ Name = $Name; Status = 'WARN'; Detail = $FixHint }
            } else {
                Write-Host "FAIL" -ForegroundColor Red
                $script:Fail++
                $script:Results += [pscustomobject]@{ Name = $Name; Status = 'FAIL'; Detail = $FixHint }
            }
        }
    } catch {
        if ($Optional) {
            Write-Host "WARN ($_)" -ForegroundColor Yellow
            $script:Warn++
            $script:Results += [pscustomobject]@{ Name = $Name; Status = 'WARN'; Detail = "$FixHint`nError: $_" }
        } else {
            Write-Host "FAIL ($_)" -ForegroundColor Red
            $script:Fail++
            $script:Results += [pscustomobject]@{ Name = $Name; Status = 'FAIL'; Detail = "$FixHint`nError: $_" }
        }
    }
}

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " PostgreDataMigrationApp - preflight smoke checks (Windows)" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

# ----- Required tools -----
Write-Host "Tools" -ForegroundColor Cyan

Test-Check 'python on PATH' {
    $v = (& python --version 2>&1) -replace 'Python ', ''
    if ($LASTEXITCODE -ne 0) { return $false }
    $v
} -FixHint 'Install Python 3.10+ from python.org or via winget install Python.Python.3.11'

Test-Check 'python version >= 3.10' {
    $v = (& python --version 2>&1) -replace 'Python ', ''
    $parts = $v.Split('.')
    return ([int]$parts[0] -gt 3) -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)
} -FixHint 'Upgrade Python to 3.10 or later'

Test-Check 'git on PATH' {
    & git --version 2>&1 | Select-String 'git version'
} -FixHint 'Install Git for Windows: winget install Git.Git'

Test-Check 'psql on PATH' {
    & psql --version 2>&1 | Select-String 'psql'
} -Optional -FixHint 'psql not on PATH. Either add C:\Program Files\PostgreSQL\<ver>\bin to PATH OR install PG client'

# ----- Project files -----
Write-Host ""
Write-Host "Project files" -ForegroundColor Cyan

Test-Check 'in project root (build/, tests/, evals/ exist)' {
    (Test-Path build) -and (Test-Path tests) -and (Test-Path evals)
} -FixHint 'cd into the PostgreDataMigrationApp folder before running this script'

Test-Check 'evals/runner.py exists' {
    Test-Path 'evals\runner.py'
}

Test-Check 'build/deploy_all.sh exists' {
    Test-Path 'build\deploy_all.sh'
}

# ----- Git state -----
Write-Host ""
Write-Host "Git state" -ForegroundColor Cyan

Test-Check 'inside a git repo' {
    & git rev-parse --is-inside-work-tree 2>&1 | Select-String 'true'
}

Test-Check 'working tree clean (no uncommitted changes)' {
    $status = & git status --porcelain
    return [string]::IsNullOrEmpty($status)
} -Optional -FixHint 'Uncommitted local changes. Run `git status` then commit or stash before deploying.'

Test-Check 'remote `origin` configured' {
    & git remote get-url origin 2>$null
}

# ----- PostgreSQL connectivity (skip with -SkipPg) -----
if (-not $SkipPg) {
    Write-Host ""
    Write-Host "PostgreSQL" -ForegroundColor Cyan

    Test-Check 'PG service detected (Windows service)' {
        $svc = Get-Service postgresql* -ErrorAction SilentlyContinue | Where-Object Status -eq 'Running'
        if ($svc) { $svc.Name } else { $false }
    } -Optional -FixHint 'No running postgresql* service. Start it from services.msc or run `net start postgresql-x64-17`.'

    Test-Check 'PGHOST env var set' {
        if ($env:PGHOST) { $env:PGHOST } else { $false }
    } -Optional -FixHint 'Run `$env:PGHOST = "localhost"` (and PGPORT, PGUSER, PGPASSWORD, PGDATABASE) before connecting'

    Test-Check 'port 5432 reachable' {
        $r = Test-NetConnection -ComputerName ($env:PGHOST ?? 'localhost') -Port ($env:PGPORT ?? 5432) -WarningAction SilentlyContinue
        $r.TcpTestSucceeded
    } -Optional -FixHint 'PG not listening on the expected host:port. Check service is running and listen_addresses includes your client.'

    if ((Get-Command psql -ErrorAction SilentlyContinue) -and $env:PGPASSWORD) {
        Test-Check 'PG accepts the configured credentials' {
            $output = & psql -h ($env:PGHOST ?? 'localhost') -p ($env:PGPORT ?? 5432) -U ($env:PGUSER ?? 'postgres') -d ($env:PGDATABASE ?? 'postgres') -c "SELECT 1" 2>&1
            $LASTEXITCODE -eq 0
        } -Optional -FixHint 'psql `SELECT 1` failed. Recheck PGUSER/PGPASSWORD/PGDATABASE.'
    }
}

# ----- Azure (only with -Azure) -----
if ($Azure) {
    Write-Host ""
    Write-Host "Azure" -ForegroundColor Cyan

    Test-Check 'az CLI on PATH' {
        & az version 2>&1 | Select-String 'azure-cli'
    } -FixHint 'Install Azure CLI: winget install Microsoft.AzureCLI'

    Test-Check 'az logged in' {
        $out = & az account show 2>&1
        $LASTEXITCODE -eq 0
    } -FixHint 'Run `az login` to authenticate.'

    Test-Check 'docker on PATH' {
        & docker --version 2>&1 | Select-String 'Docker version'
    } -Optional -FixHint 'Docker not installed. For Azure deploy you can use Cloud Shell + `az acr build` instead (see AZURE_DEPLOY.md).'

    Test-Check 'terraform on PATH' {
        & terraform version 2>&1 | Select-String 'Terraform'
    } -Optional -FixHint 'Terraform not installed. For Azure deploy you can use Cloud Shell instead.'
}

# ----- Summary -----
Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " Summary: $script:Pass passed, $script:Warn warned, $script:Fail failed" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan

if ($script:Fail -gt 0 -or $script:Warn -gt 0) {
    Write-Host ""
    Write-Host "Issues to address:" -ForegroundColor Yellow
    $script:Results | Where-Object Status -in 'FAIL', 'WARN' | ForEach-Object {
        $color = if ($_.Status -eq 'FAIL') { 'Red' } else { 'Yellow' }
        Write-Host ""
        Write-Host "  [$($_.Status)] $($_.Name)" -ForegroundColor $color
        if ($_.Detail) { Write-Host "         $($_.Detail)" }
    }
}

Write-Host ""

if ($script:Fail -gt 0) { exit 1 }
if ($script:Warn -gt 0) { exit 2 }
exit 0
