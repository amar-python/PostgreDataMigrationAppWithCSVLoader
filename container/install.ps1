# install.ps1: install the T&E platform from the container bundle on Windows, with no internet
# access (#128, BR-38). macOS and Linux use install.sh and do the same steps.
#
# Needs Docker Desktop or Podman already installed and running. From inside the extracted
# bundle folder (works in Windows PowerShell 5.1 and PowerShell 7):
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 [-TeHost HOST]
# HOST is the name or address people use to reach this machine (default: localhost; with
# the default, only this machine can use the web app).
#
# Environment (all optional):
#   TE_RUNTIME         docker or podman (default: whichever is installed, docker first)
#   TE_TENANT          first tenant (default: main)
#   TE_ADMIN_USER      first tenant admin (default: admin)
#   TE_ADMIN_PASSWORD  its password, 12+ characters (default: generated, and written to
#                      .\te-initial-admin, readable only by you)
#
# Safe to re-run: secrets and data are kept, the first admin is created only once.
param([string]$TeHost = '')

Set-StrictMode -Version Latest
# Not 'Stop': Windows PowerShell 5.1 turns a native command's stderr output into a terminating
# error, and Docker writes progress to stderr. Every native call is checked with Assert-Ok.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$Message) { Write-Host "ERROR: $Message" -ForegroundColor Red; exit 1 }
function Step([string]$Message) { Write-Host "== $Message" }
function Assert-Ok([string]$What) { if ($LASTEXITCODE -ne 0) { Fail "$What failed (exit code $LASTEXITCODE)" } }
function Get-Setting([string]$Name, [string]$Default) {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($v)) { $Default } else { $v }
}
function New-Hex([int]$Bytes) {
    $b = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b); $rng.Dispose()
    -join ($b | ForEach-Object { $_.ToString('x2') })
}
# A file only the current user can read. -Encoding UTF8 would add a BOM, which a .env parser
# reads as part of the first key, so the bytes are written directly.
function Write-Private([string]$Path, [string[]]$Lines) {
    $text = ($Lines -join "`n") + "`n"
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot $Path), $text, (New-Object System.Text.UTF8Encoding($false)))
    & icacls.exe (Join-Path $PSScriptRoot $Path) /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
}

$TeTenant    = Get-Setting 'TE_TENANT' 'main'
$TeAdminUser = Get-Setting 'TE_ADMIN_USER' 'admin'
# The host people use to reach this machine. Given explicitly it wins; on a re-run with none
# given the earlier choice in .env is kept; otherwise localhost.
$HostArg = if ($TeHost) { $TeHost } else { Get-Setting 'TE_HOST' '' }

# ---- container runtime ----------------------------------------------------------------------
$RT = Get-Setting 'TE_RUNTIME' ''
if (-not $RT) {
    if (Get-Command docker -ErrorAction SilentlyContinue) { $RT = 'docker' }
    elseif (Get-Command podman -ErrorAction SilentlyContinue) { $RT = 'podman' }
    else { Fail 'neither docker nor podman is installed. Install one (Podman is free; Docker Desktop needs a paid subscription for larger organisations) and run this again.' }
}
if ($RT -ne 'docker' -and $RT -ne 'podman') { Fail "TE_RUNTIME must be docker or podman (got '$RT')" }
& $RT info *> $null
if ($LASTEXITCODE -ne 0) { Fail "$RT is installed but not running. Start it (Docker Desktop, or 'podman machine start') and run this again." }
& $RT compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "'$RT compose' is not available. Docker needs the Compose plugin; Podman needs 'podman compose' (docker-compose or podman-compose)." }
function Compose { & $RT compose @args }

# ---- 1. verify the bundle -------------------------------------------------------------------
Step '1/6 verify bundle checksums'
foreach ($line in Get-Content -LiteralPath 'SHA256SUMS') {
    if ($line -notmatch '^([0-9a-fA-F]{64}) [ \*](.+)$') { Fail "unreadable line in SHA256SUMS: $line" }
    $expected = $Matches[1]; $file = $Matches[2]
    if (-not (Test-Path -LiteralPath $file)) { Fail "SHA256SUMS lists $file, which is missing from the bundle" }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    if ($actual -ne $expected.ToUpper()) { Fail "checksum mismatch for $file. The bundle is damaged or incomplete; copy it again." }
}
Write-Host 'checksums match'

# ---- 2. load the images for this CPU --------------------------------------------------------
Step '2/6 load the container images (no download)'
$cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
switch ($cpu) {
    'AMD64' { $Arch = 'amd64' }
    'ARM64' { $Arch = 'arm64' }
    default { Fail "unsupported CPU '$cpu'; the bundle has amd64 and arm64 builds" }
}
$ImagesTar = "images-$Arch.tar"
if (-not (Test-Path -LiteralPath $ImagesTar)) {
    Fail "this bundle has no images for $Arch. It holds: $((Get-ChildItem -Filter 'images-*.tar' | ForEach-Object Name) -join ' ')"
}
$TeVersion = (Get-Content -LiteralPath 'VERSION' -TotalCount 1).Trim()
$loadOut = & $RT load -i $ImagesTar 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host ($loadOut | Out-String); Fail "$RT could not load $ImagesTar" }
Write-Host "loaded te-api, te-frontend, te-db ($TeVersion, $Arch)"

# ---- 3. secrets -----------------------------------------------------------------------------
Step '3/6 secrets and configuration'
$FirstRun = -not (Test-Path -LiteralPath '.env')
if ($FirstRun) {
    $Secrets = @{
        POSTGRES_PASSWORD   = New-Hex 24
        TE_DB_PASSWORD      = New-Hex 24
        TE_RUNTIME_PASSWORD = New-Hex 24
        API_KEY             = New-Hex 24
    }
    $TeHostFinal = if ($HostArg) { $HostArg } else { 'localhost' }
    Write-Host 'generated new secrets'
} else {
    # Keep the existing secrets: the database volume was initialised with them.
    $old = @{}
    foreach ($l in Get-Content -LiteralPath '.env') { if ($l -match '^([A-Z_]+)=(.*)$') { $old[$Matches[1]] = $Matches[2] } }
    foreach ($k in 'POSTGRES_PASSWORD', 'TE_DB_PASSWORD', 'TE_RUNTIME_PASSWORD', 'API_KEY') {
        if (-not $old.ContainsKey($k)) { Fail ".env has no $k; delete .env only if you also remove the data volume (compose down -v)" }
    }
    $Secrets = @{
        POSTGRES_PASSWORD   = $old['POSTGRES_PASSWORD']
        TE_DB_PASSWORD      = $old['TE_DB_PASSWORD']
        TE_RUNTIME_PASSWORD = $old['TE_RUNTIME_PASSWORD']
        API_KEY             = $old['API_KEY']
    }
    $TeHostFinal = if ($HostArg) { $HostArg } elseif ($old.ContainsKey('TE_HOST')) { $old['TE_HOST'] } else { 'localhost' }
    Write-Host 'keeping the secrets in .env'
}
Write-Private '.env' @(
    "TE_VERSION=$TeVersion",
    "TE_HOST=$TeHostFinal",
    "POSTGRES_PASSWORD=$($Secrets.POSTGRES_PASSWORD)",
    "TE_DB_PASSWORD=$($Secrets.TE_DB_PASSWORD)",
    "TE_RUNTIME_PASSWORD=$($Secrets.TE_RUNTIME_PASSWORD)",
    "API_KEY=$($Secrets.API_KEY)"
)
$env:TE_VERSION = $TeVersion; $env:TE_HOST = $TeHostFinal

# ---- 4. start -------------------------------------------------------------------------------
Step '4/6 start the database, API and web app'
Compose up -d
if ($LASTEXITCODE -ne 0) {
    $hint = if ($RT -eq 'podman') { " With Podman, 'podman compose' needs a compose provider: install podman-compose, or install docker-compose and make sure Podman's API socket is running." } else { '' }
    Fail "'$RT compose up' failed.$hint"
}
# The API container starts only once the database is healthy (first start deploys the schema,
# which takes a few seconds), then runs its own migrations; wait for it to answer.
$probe = "import urllib.request as u; u.urlopen('http://localhost:8000/api/health', timeout=3)"
$tries = 0
while ($true) {
    Compose exec -T api python -c $probe *> $null
    if ($LASTEXITCODE -eq 0) { break }
    $tries++
    if ($tries -gt 120) { Fail "the API did not become healthy in 4 minutes. Look at: $RT compose logs" }
    Start-Sleep -Seconds 2
}
Write-Host 'API is up'

# ---- 5. first tenant admin ------------------------------------------------------------------
Step '5/6 first tenant admin'
$AdminPassword = Get-Setting 'TE_ADMIN_PASSWORD' ''
if ($FirstRun) {
    if (-not $AdminPassword) {
        $AdminPassword = New-Hex 18
        Write-Private 'te-initial-admin' @("tenant=$TeTenant", "username=$TeAdminUser", "password=$AdminPassword")
        Write-Host "The admin's password is in .\te-initial-admin (readable only by you). Change it after first sign-in."
    }
    $env:TE_ADMIN_PASSWORD = $AdminPassword
    Compose exec -T -e TE_ADMIN_PASSWORD api python scripts/create_tenant_admin.py --tenant $TeTenant --name $TeTenant --username $TeAdminUser
    Assert-Ok 'creating the first tenant admin'
} else {
    Write-Host 'already installed; keeping the existing admin'
    if (-not $AdminPassword -and (Test-Path -LiteralPath 'te-initial-admin')) {
        $line = Get-Content -LiteralPath 'te-initial-admin' | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
        if ($line) { $AdminPassword = $line.Substring('password='.Length) }
    }
}

# ---- 6. smoke test --------------------------------------------------------------------------
Step '6/6 smoke test'
$env:API_KEY = $Secrets.API_KEY; $env:SMOKE_TENANT = $TeTenant; $env:SMOKE_USER = $TeAdminUser; $env:SMOKE_PASSWORD = $AdminPassword
Compose exec -T -e API_KEY -e SMOKE_TENANT -e SMOKE_USER -e SMOKE_PASSWORD api python smoke_test.py
$smokeOk = ($LASTEXITCODE -eq 0)
try {
    # The smoke test runs inside the containers; this checks the ports are published to the host.
    Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8000/api/health' | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8080/' | Out-Null
    Write-Host 'PASS  ports 8000 and 8080 answer on this machine'
} catch {
    Write-Host 'FAIL  ports 8000 and 8080 do not answer on this machine'; $smokeOk = $false
}
if (-not $smokeOk) { Fail "the smoke test failed; the stack is running, so look at: $RT compose logs" }

Write-Host ''
Write-Host "Installed. Open http://${TeHostFinal}:8080 and sign in as tenant '$TeTenant', user '$TeAdminUser'."
Write-Host "Stop:  $RT compose down        Start again:  $RT compose up -d        (the data is kept in a volume)"
