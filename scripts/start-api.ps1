# start-api.ps1 - Terminal 1: run the FastAPI backend on http://localhost:8000
# First run: pip install -r ..\api\requirements.txt
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-parses non-ASCII characters
# like em-dashes when the file lacks a UTF-8 BOM, which turns strings after the
# em-dash into unquoted command calls (see BUG-021 in docs/BUG_REPORT.md).

$ErrorActionPreference = "Stop"
$apiDir = Join-Path $PSScriptRoot "..\api"

# Postgres owner login (local PG 18 dev instance). Each value comes from, in this order:
# this window's own PG* variables, then the login saved by `python scripts\pg_login.py save`
# (~\.te-migration\pg-<env>.env), then the defaults below, then asking.
# API_ENV names the environment, matching api\config.py's own default of "dev".
if (-not $env:API_ENV) { $env:API_ENV = "dev" }
$pgLoginFile = Join-Path $env:USERPROFILE (".te-migration\pg-{0}.env" -f $env:API_ENV)
$pgPasswordFrom = $null
if ($env:PGPASSWORD) { $pgPasswordFrom = "this window" }
if (Test-Path $pgLoginFile) {
    foreach ($line in Get-Content $pgLoginFile) {
        $k, $v = $line -split "=", 2
        if (($k -like "PG*") -and (-not (Test-Path "env:$k"))) { Set-Item -Path "env:$k" -Value $v }
    }
    if ((-not $pgPasswordFrom) -and $env:PGPASSWORD) { $pgPasswordFrom = "the saved login ($pgLoginFile)" }
}
if (-not $env:PGHOST)     { $env:PGHOST     = "localhost" }
if (-not $env:PGPORT)     { $env:PGPORT     = "5433" }
if (-not $env:PGUSER)     { $env:PGUSER     = "postgres" }
if (-not $env:PGDATABASE) { $env:PGDATABASE = "te_mgmt_dev" }

# First, is PostgreSQL there at all? Ask before asking for a password: with the server down or on
# another port, no password can work, so there is nothing to type. `pg_login.py check --server-only`
# uses no password and exits 0 when the server accepts connections, 3 when it does not.
$pgLogin = Join-Path $PSScriptRoot "pg_login.py"
python $pgLogin check --server-only
if ($LASTEXITCODE -ne 0) { exit 1 }

if (-not $env:PGPASSWORD) {
    Write-Host "PGPASSWORD not set - enter it now (input hidden):" -ForegroundColor Yellow
    $sec = Read-Host -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    $pgPasswordFrom = "what you typed"
}

# M3d (#107): requests use the runtime role made by scripts\create_app_role.py,
# which can't change the audit log. The owner above is only used at startup.
#
# RV-S3 (#173): the role and its credential file are per environment
# (te_app_<env>, app-db-<env>.env), so two environments sharing one PostgreSQL
# cluster - the usual dev-PC setup - no longer rotate each other's password.
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

# #298: the shared API key is retired; data endpoints need a signed-in session. Local dev may opt in to
# anonymous access with $env:API_ALLOW_ANONYMOUS = "1" (only with API_ENV=dev; the API refuses to start otherwise).
if ($env:API_ALLOW_ANONYMOUS) {
    Write-Host "API_ALLOW_ANONYMOUS is set - data endpoints answer without sign-in (local dev only)." -ForegroundColor Yellow
}
if ($env:API_KEY) {
    Write-Host "API_KEY is set but no longer used: sign in instead (the shared key was retired, #298)." -ForegroundColor Yellow
}

# The server is there (checked above); now test the owner login before starting. A wrong password
# then costs one clear message here and a chance to type it again, not a failed start.
# `pg_login.py check` exits 0 when the login works, 2 when PostgreSQL refused it (waiting will not
# help), 3 when the server went away in the meantime.
$pgTries = 0
while ($true) {
    python $pgLogin check
    $pgCode = $LASTEXITCODE
    if ($pgCode -eq 0) { break }
    if ($pgCode -ne 2) { exit 1 }
    $pgTries++
    if ($pgTries -ge 3) {
        Write-Host "Giving up after 3 refused passwords. To store a working login: python scripts\pg_login.py save" -ForegroundColor Red
        exit 1
    }
    Write-Host ("The password from {0} was refused. Enter the PostgreSQL password again (input hidden), or press Ctrl+C to stop:" -f $pgPasswordFrom) -ForegroundColor Yellow
    $sec = Read-Host -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    $pgPasswordFrom = "what you typed"
}
if ($pgPasswordFrom -eq "what you typed") {
    $pgSave = Read-Host "Save this login so you are not asked again? (y/N)"
    if ($pgSave -match "^[Yy]") { python $pgLogin save --env $env:API_ENV --from-env }
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
