# dev-env.ps1 - load the saved PostgreSQL login into THIS PowerShell window, so the other
# scripts (python scripts\reset_password.py, create_app_role.py, create_tenant_admin.py ...)
# need no PGHOST / PGPORT / PGUSER / PGPASSWORD typed first.
#
# Run it by "dot-sourcing" (a dot, a space, then the path), or the variables vanish when it ends:
#     . .\scripts\dev-env.ps1            (the dev environment)
#     . .\scripts\dev-env.ps1 test       (another environment)
#
# Save the login once with:  python scripts\pg_login.py save
# It reads ~\.te-migration\pg-<env>.env and never prints the password.
#
# ASCII-only on purpose (see start-api.ps1). It uses return, never exit: exit would close
# the window it was dot-sourced into.

param([string]$Environment = "dev")

$pgLoginFile = Join-Path $env:USERPROFILE (".te-migration\pg-{0}.env" -f $Environment)
if (-not (Test-Path $pgLoginFile)) {
    Write-Host ("No saved login for '{0}' ({1})." -f $Environment, $pgLoginFile) -ForegroundColor Yellow
    Write-Host ("Save one once with: python scripts\pg_login.py save --env {0}" -f $Environment) -ForegroundColor Yellow
    return
}
foreach ($line in Get-Content $pgLoginFile) {
    $k, $v = $line -split "=", 2
    if ($k -like "PG*") { Set-Item -Path "env:$k" -Value $v }
}
$env:API_ENV = $Environment
Write-Host ("Loaded the {0} PostgreSQL login: {1}@{2}:{3} (password not shown)." -f $Environment, $env:PGUSER, $env:PGHOST, $env:PGPORT) -ForegroundColor Green
