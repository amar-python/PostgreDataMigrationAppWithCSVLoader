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

Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "API starting on http://localhost:8000  (docs: /docs)" -ForegroundColor Green
python -m uvicorn api.main:app --reload --port 8000
