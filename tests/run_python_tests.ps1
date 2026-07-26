param(
    [string]$TestPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($TestPath)) {
    # Database-backed markers are excluded here: they require PostgreSQL and,
    # by design, FAIL rather than skip when it is unavailable. Run them with
    # scripts/provision_full_test_env.sh + the full suite.
    python -m pytest -m "unit or regression or security or snapshot" -v
} else {
    python -m unittest -v $TestPath
}
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

exit 0
