#!/usr/bin/env bash
# scripts/lint.sh — flake8 + bandit over every tracked Python file.
# Mirrors: bun run slop (full slop-scan report in gstack)
#
# Scope is discovered from git, not listed by hand (#322). A hand-kept list had fallen behind twice: it named 14 of
# the 38 test files (#167) and then 19 of the 74 source files, so the routers, most services, the Streamlit app,
# e2e/ and the later migrations were never checked and "lint clean" said nothing about the code that changes most.
#
#   flake8  every tracked .py file
#   bandit  every tracked .py file except test code (tests/, e2e/), where its findings are about fixtures and asserts
#
# LINT_EXCLUDE below skips exact paths from BOTH tools. Give each entry a reason. It is empty today, and
# tests/unit/test_lint_scope.py fails if a tracked file is outside the scope and not named here.
#
#   scripts/lint.sh                        run the lint
#   scripts/lint.sh --list-files           print the files flake8 checks, one per line, and stop
#   scripts/lint.sh --list-security-files  print the files bandit scans
#   scripts/lint.sh --list-excluded        print the excluded files
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

LINT_EXCLUDE=()

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "lint.sh finds its files with 'git ls-files', so it must run inside a git checkout." >&2
    exit 2
fi

is_excluded() {
    local path="$1" skip
    for skip in ${LINT_EXCLUDE[@]+"${LINT_EXCLUDE[@]}"}; do
        [[ "$path" == "$skip" ]] && return 0
    done
    return 1
}

LINT_FILES=()
SECURITY_FILES=()
while IFS= read -r path; do
    [[ -f "$path" ]] || continue            # tracked, but deleted in the working tree
    is_excluded "$path" && continue
    LINT_FILES+=("$path")
    case "$path" in
        tests/*|e2e/*) ;;
        *) SECURITY_FILES+=("$path") ;;
    esac
done < <(git ls-files '*.py' | LC_ALL=C sort)

case "${1:-}" in
    --list-files)          [ "${#LINT_FILES[@]}" -eq 0 ] || printf '%s\n' "${LINT_FILES[@]}"; exit 0 ;;
    --list-security-files) [ "${#SECURITY_FILES[@]}" -eq 0 ] || printf '%s\n' "${SECURITY_FILES[@]}"; exit 0 ;;
    --list-excluded)       [ "${#LINT_EXCLUDE[@]}" -eq 0 ] || printf '%s\n' "${LINT_EXCLUDE[@]}"; exit 0 ;;
    "") ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
esac

if [ "${#LINT_FILES[@]}" -eq 0 ]; then
    echo -e "${RED}✗ no tracked Python files found; refusing to report a clean lint over nothing${NC}"
    exit 1
fi

echo -e "\n${YELLOW}=== flake8 (style + logic): ${#LINT_FILES[@]} files ===${NC}"
if python3 -m flake8 "${LINT_FILES[@]}" \
        --max-line-length=120 \
        --extend-ignore=E501,E221,E272; then
    echo -e "${GREEN}✓ flake8 clean${NC}"
else
    echo -e "${RED}✗ flake8 found issues — fix before merging${NC}"
    exit 1
fi

echo -e "\n${YELLOW}=== bandit (security): ${#SECURITY_FILES[@]} files ===${NC}"
if [ "${#SECURITY_FILES[@]}" -eq 0 ]; then
    echo -e "${GREEN}✓ bandit: no non-test Python files to scan${NC}"
elif python3 -m bandit "${SECURITY_FILES[@]}" -ll -q 2>&1; then
    echo -e "${GREEN}✓ bandit clean${NC}"
else
    echo -e "${RED}✗ bandit found security issues${NC}"
    exit 1
fi

echo -e "\n${GREEN}All lint checks passed.${NC}\n"
