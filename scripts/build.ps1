# build.ps1 - build the deployable migration runner image (Windows).
#
# Usage:
#   .\scripts\build.ps1                                    # local docker build, tag = dev
#   .\scripts\build.ps1 -Tag dev-1234                      # custom tag
#   .\scripts\build.ps1 -UseAcrBuild                       # build in Azure (no local Docker needed)
#   .\scripts\build.ps1 -Push                              # also push to ACR
#   .\scripts\build.ps1 -UseAcrBuild -Push -Tag $(git rev-parse --short HEAD)
#
# Exit codes:
#   0 = image built successfully (and pushed if -Push)
#   1 = build failed
#   2 = prereq missing (docker / az)

[CmdletBinding()]
param(
    [string]$Tag = "dev",
    [switch]$UseAcrBuild,
    [switch]$Push,
    [string]$AcrName,
    [string]$ResourceGroup
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Push-Location $ProjectRoot

try {
    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host " PostgreDataMigrationApp - build" -ForegroundColor Cyan
    Write-Host " tag         : $Tag" -ForegroundColor Cyan
    Write-Host " mode        : $(if ($UseAcrBuild) {'az acr build (cloud)'} else {'docker build (local)'})" -ForegroundColor Cyan
    Write-Host " push to ACR : $(if ($Push) {'yes'} else {'no'})" -ForegroundColor Cyan
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host ""

    # --- Validate prereqs ---
    if ($UseAcrBuild) {
        if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
            Write-Host "FAIL: az CLI not on PATH. Install with: winget install Microsoft.AzureCLI" -ForegroundColor Red
            exit 2
        }
        if (-not $AcrName) {
            # Try to discover ACR from terraform output
            $tfDir = Join-Path $ProjectRoot 'infra\terraform'
            if (Test-Path $tfDir) {
                Push-Location $tfDir
                try {
                    $AcrName = & terraform output -raw acr_name 2>$null
                    if (-not $ResourceGroup) {
                        $ResourceGroup = & terraform output -raw resource_group_name 2>$null
                    }
                } finally { Pop-Location }
            }
            if (-not $AcrName) {
                Write-Host "FAIL: -AcrName required for -UseAcrBuild (or run terraform apply first)" -ForegroundColor Red
                exit 2
            }
        }
    } else {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Write-Host "FAIL: docker not on PATH. Install Docker Desktop OR use -UseAcrBuild." -ForegroundColor Red
            exit 2
        }
    }

    # --- Validate project files ---
    foreach ($f in @('infra\Dockerfile', 'infra\entrypoint.sh', 'build', 'tests', 'evals')) {
        if (-not (Test-Path $f)) {
            Write-Host "FAIL: missing $f. Run from project root." -ForegroundColor Red
            exit 2
        }
    }

    # --- Build ---
    if ($UseAcrBuild) {
        Write-Host "[acr build] Building $Tag inside Azure..." -ForegroundColor Yellow
        $imageRef = "te-migration:$Tag"
        & az acr build --registry $AcrName --image $imageRef --file infra\Dockerfile .
        if ($LASTEXITCODE -ne 0) { throw "az acr build failed" }
        $FullImage = "$AcrName.azurecr.io/${imageRef}"
        Write-Host "[acr build] OK: $FullImage" -ForegroundColor Green
    } else {
        $LocalImage = "te-migration:$Tag"
        Write-Host "[docker build] Building $LocalImage locally..." -ForegroundColor Yellow
        & docker build -f infra\Dockerfile -t $LocalImage .
        if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
        Write-Host "[docker build] OK: $LocalImage" -ForegroundColor Green

        if ($Push) {
            if (-not $AcrName) {
                Write-Host "FAIL: -Push requires -AcrName" -ForegroundColor Red
                exit 2
            }
            $FullImage = "$AcrName.azurecr.io/${LocalImage}"
            Write-Host "[docker tag+push] $LocalImage -> $FullImage" -ForegroundColor Yellow
            & az acr login --name $AcrName
            & docker tag $LocalImage $FullImage
            & docker push $FullImage
            if ($LASTEXITCODE -ne 0) { throw "docker push failed" }
            Write-Host "[docker push] OK" -ForegroundColor Green
        }
    }

    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Green
    Write-Host " BUILD SUCCESS" -ForegroundColor Green
    Write-Host "===========================================================" -ForegroundColor Green
    Write-Host ""
    exit 0
} catch {
    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Red
    Write-Host " BUILD FAILED: $_" -ForegroundColor Red
    Write-Host "===========================================================" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
