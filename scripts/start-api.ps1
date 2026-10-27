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
python -m uvicorn api.main:app --reload --port 8000
