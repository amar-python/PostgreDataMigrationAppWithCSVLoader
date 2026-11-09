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
    alembic/versions/0009_types_provenance.py
    api/auth.py
    api/services/accounts.py
    api/routers/auth_routes.py
    api/tenancy.py
    api/oidc.py
    scripts/create_tenant_admin.py
)

# #167: every Python test file in the repo, so a new test cannot land unlinted.
# Collected dynamically — the category folders (tests/unit, tests/system, …)
# made the old hand-maintained list drift the moment a test was added.
mapfile -t PY_TESTS < <(find tests -name '*.py' | sort)

# Collect scripts/*.py dynamically
mapfile -t PY_SCRIPTS < <(ls scripts/*.py 2>/dev/null || true)

SRC_PY=("${PY_SRC[@]}" "${PY_SCRIPTS[@]}")

echo -e "\n${YELLOW}=== flake8 — source (${#SRC_PY[@]} files) ===${NC}"
if python3 -m flake8 "${SRC_PY[@]}" \
        --max-line-length=120 \
        --extend-ignore=E501,E221,E272; then
    echo -e "${GREEN}✓ flake8 clean${NC}"
else
    echo -e "${RED}✗ flake8 found issues — fix before merging${NC}"
    exit 1
fi

# Tests use a deliberately compact table style — one-line class attribute
# blocks (`ENV = "dev"; DB = "te_mgmt_dev"`) and aligned continuations — that
# reads better as a fixture declaration than as PEP 8 prose. E702/E401/E128 are
# allowed there and nowhere else; every other check applies as above.
echo -e "\n${YELLOW}=== flake8 — tests (${#PY_TESTS[@]} files) ===${NC}"
if python3 -m flake8 "${PY_TESTS[@]}" \
        --max-line-length=120 \
        --extend-ignore=E501,E221,E272,E702,E401,E128; then
    echo -e "${GREEN}✓ flake8 clean${NC}"
else
    echo -e "${RED}✗ flake8 found issues in tests — fix before merging${NC}"
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
