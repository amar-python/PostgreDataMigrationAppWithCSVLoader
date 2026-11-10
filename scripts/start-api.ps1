# start-api.ps1 - Terminal 1: run the FastAPI backend on http://localhost:8000
# First run: pip install -r ..\api\requirements.txt
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-parses non-ASCII characters
# like em-dashes when the file lacks a UTF-8 BOM, which turns strings after the
# em-dash into unquoted command calls (see BUG-021 in docs/BUG_REPORT.md).

$ErrorActionPreference = "Stop"
$apiDir = Join-Path $PSScriptRoot "..\api"

# Postgres connection (local PG 18 dev instance)
if (-not $env:PGHOST)     { $env:PGHOST     = "localhost" }
if (-not $env:PGPORT)     { $env:PGPORT     = "5433" }
if (-not $env:PGUSER)     { $env:PGUSER     = "postgres" }
if (-not $env:PGDATABASE) { $env:PGDATABASE = "te_mgmt_dev" }
if (-not $env:PGPASSWORD) {
    Write-Host "PGPASSWORD not set - enter it now (input hidden):" -ForegroundColor Yellow
    $sec = Read-Host -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

# M3d (#107): requests use the runtime role made by scripts\create_app_role.py,
# which can't change the audit log. The owner above is only used at startup.
#
# RV-S3 (#173): the role and its credential file are per environment
# (te_app_<env>, app-db-<env>.env), so two environments sharing one PostgreSQL
# cluster - the usual dev-PC setup - no longer rotate each other's password.
# API_ENV names the environment, matching api\config.py's own default of "dev".
if (-not $env:API_ENV) { $env:API_ENV = "dev" }
$appDbEnv = Join-Path $env:USERPROFILE (".te-migration\app-db-{0}.env" -f $env:API_ENV)
$legacyAppDbEnv = Join-Path $env:USERPROFILE ".te-migration\app-db.env"
if ((-not $env:APP_DB_USER) -and (Test-Path $appDbEnv)) {
    foreach ($line in Get-Content $appDbEnv) {
        $k, $v = $line -split "=", 2
        if ($k) { Set-Item -Path "env:$k" -Value $v }
    }
}
if ((-not $env:APP_DB_USER) -and (Test-Path $legacyAppDbEnv)) {
    # Pre-#173 file, from before the role was per environment. Honoured so an
    # existing dev PC still starts, but it holds the cluster-wide te_app role,
    # whose password any other environment's provisioning run will have reset.
    Write-Host ("Using the pre-#173 credential file {0}. It holds the shared te_app role, which another environment's setup can invalidate. Re-provision with: python scripts\create_app_role.py --env {1}" -f $legacyAppDbEnv, $env:API_ENV) -ForegroundColor Yellow
    foreach ($line in Get-Content $legacyAppDbEnv) {
        $k, $v = $line -split "=", 2
        if ($k) { Set-Item -Path "env:$k" -Value $v }
    }
}
if (-not $env:APP_DB_USER) {
    Write-Host ("APP_DB_USER not set - requests run as the owner. Run once: python scripts\create_app_role.py --env {0}" -f $env:API_ENV) -ForegroundColor Yellow
}

if (-not $env:API_KEY) {
    Write-Host "API_KEY not set - every endpoint is unauthenticated (fine for local dev)." -ForegroundColor Yellow
}

# #118: refuse to start a second API. Uvicorn can print "running" even when an
# older API already holds the port, and then every request goes to the old one.
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    foreach ($b in $busy) {
        $p = Get-Process -Id $b.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("Port 8000 is already in use by PID {0} ({1}, started {2})." -f $b.OwningProcess, $p.ProcessName, $p.StartTime) -ForegroundColor Red
    }
    Write-Host "Another API is probably still running. Close its window, or stop it with:" -ForegroundColor Red
    Write-Host ("    taskkill /PID {0} /T /F" -f $busy[0].OwningProcess) -ForegroundColor Red
    exit 1
}

Set-Location (Join-Path $PSScriptRoot "..")
$host.UI.RawUI.WindowTitle = "API (port 8000)"
Write-Host "API starting on http://localhost:8000  (docs: /docs)" -ForegroundColor Green
# #118: watch only api/ for code changes. Watching the whole repo meant a OneDrive
# sync anywhere in the folder could restart (or stop) the API.
python -m uvicorn api.main:app --reload --reload-dir api --port 8000
