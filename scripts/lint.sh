#!/usr/bin/env bash
# scripts/lint.sh — full flake8 + bandit scan over all Python source.
# Mirrors: bun run slop (full slop-scan report in gstack)
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

PY_SRC=(
    build/csv/validator.py
    evals/runner.py
    evals/gap_report.py
    api/main.py
    api/ratelimit.py
    api/services/audit.py
    api/db.py
    alembic/env.py
    alembic/versions/0001_baseline.py
    alembic/versions/0002_registry_unique.py
    alembic/versions/0003_import_counts.py
    alembic/versions/0004_control_schema.py
    alembic/versions/0005_login_lockout.py
    api/auth.py
    api/services/accounts.py
    api/routers/auth_routes.py
    api/tenancy.py
    scripts/create_tenant_admin.py
)

PY_TESTS=(
    tests/test_csv_validator.py
    tests/test_evals_runner.py
    tests/test_api_unit.py
    tests/test_api_integration.py
    tests/test_issue_04_multi_file_upload.py
    tests/test_issue_05_import_summary.py
    tests/test_api_hardening.py
    tests/test_evals_tier_e_x.py
    tests/test_migrations.py
    tests/test_import_counts.py
    tests/test_accounts.py
    tests/test_tenant_isolation.py
    tests/test_roles.py
)

# Collect scripts/*.py dynamically
mapfile -t PY_SCRIPTS < <(ls scripts/*.py 2>/dev/null || true)

ALL_PY=("${PY_SRC[@]}" "${PY_TESTS[@]}" "${PY_SCRIPTS[@]}")

echo -e "\n${YELLOW}=== flake8 (style + logic) ===${NC}"
if python3 -m flake8 "${ALL_PY[@]}" \
        --max-line-length=120 \
        --extend-ignore=E501,E221,E272; then
    echo -e "${GREEN}✓ flake8 clean${NC}"
else
    echo -e "${RED}✗ flake8 found issues — fix before merging${NC}"
    exit 1
fi

echo -e "\n${YELLOW}=== bandit (security) ===${NC}"
if python3 -m bandit "${PY_SRC[@]}" -ll -q 2>&1; then
    echo -e "${GREEN}✓ bandit clean${NC}"
else
    echo -e "${RED}✗ bandit found security issues${NC}"
    exit 1
fi

echo -e "\n${GREEN}All lint checks passed.${NC}\n"
