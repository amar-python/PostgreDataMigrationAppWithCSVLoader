# start-frontend.ps1 - Terminal 2: run the React frontend on http://localhost:5173
# First run installs node_modules automatically.

$ErrorActionPreference = "Stop"
$feDir = Join-Path $PSScriptRoot "..\frontend"
Set-Location $feDir

if (-not (Test-Path "node_modules")) {
    Write-Host "node_modules missing - running npm install first..." -ForegroundColor Yellow
    npm install
}

Write-Host "Frontend starting on http://localhost:5173" -ForegroundColor Green
npm run dev
