#!/usr/bin/env bash
# scripts/lint_diff.sh — lint only Python files changed on this branch.
# Mirrors: bun run slop:diff (diff-scoped slop-scan in gstack)
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

BASE="${1:-origin/main}"

# Collect changed .py files against the base branch; fall back to HEAD~1.
changed=$(git diff --name-only "${BASE}...HEAD" 2>/dev/null \
          || git diff --name-only HEAD~1 2>/dev/null \
          || true)
py_changed=$(echo "${changed}" | grep '\.py$' || true)

if [ -z "${py_changed}" ]; then
    echo -e "${YELLOW}No changed Python files on this branch — nothing to lint.${NC}"
    exit 0
fi

echo -e "${YELLOW}Changed Python files:${NC}"
echo "${py_changed}" | sed 's/^/  /'
echo ""

echo -e "${YELLOW}=== flake8 (diff) ===${NC}"
# shellcheck disable=SC2086
if python3 -m flake8 ${py_changed} --max-line-length=120 --extend-ignore=E501; then
    echo -e "${GREEN}✓ flake8 clean${NC}"
else
    echo -e "${RED}✗ flake8 issues found${NC}"
    exit 1
fi

echo -e "\n${YELLOW}=== bandit (diff, security) ===${NC}"
# shellcheck disable=SC2086
if python3 -m bandit ${py_changed} -ll -q 2>&1; then
    echo -e "${GREEN}✓ bandit clean${NC}"
else
    echo -e "${RED}✗ bandit issues found${NC}"
    exit 1
fi

echo -e "\n${GREEN}Diff lint passed.${NC}\n"
