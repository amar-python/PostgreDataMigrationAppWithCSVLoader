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
)

PY_TESTS=(
    tests/test_csv_validator.py
    tests/test_evals_runner.py
    tests/test_api.py
    tests/test_issue_04_multi_file_upload.py
    tests/test_issue_05_import_summary.py
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
