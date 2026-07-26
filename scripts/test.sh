#!/usr/bin/env bash
# test.sh - run all validation layers (Linux/Mac/Cloud Shell).
#
# Layers:
#   1. pytest -m unit              (Python unit tests)
#   2. SQL test suite              (5 suites, needs PG)
#   3. evals/runner.py             (Tier P offline + Tier I/S need PG)
#
# Usage:
#   ./scripts/test.sh                       # all three
#   ./scripts/test.sh --skip-sql            # skip SQL suite
#   ./scripts/test.sh --skip-evals          # skip evals
#   ./scripts/test.sh --only-python         # only pytest
#   ./scripts/test.sh -e dev                # target env for SQL suite

set -uo pipefail

ENV_TARGET="dev"
SKIP_SQL=0
SKIP_EVALS=0
ONLY_PYTHON=0

while [ $# -gt 0 ]; do
    case "$1" in
        -e|--env)         ENV_TARGET="$2"; shift 2 ;;
        --skip-sql)       SKIP_SQL=1; shift ;;
        --skip-evals)     SKIP_EVALS=1; shift ;;
        --only-python)    ONLY_PYTHON=1; shift ;;
        -h|--help)        sed -n '1,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)                echo "unknown arg: $1" >&2; exit 64 ;;
    esac
done

cd "$(dirname "$0")/.."

if [ -t 1 ]; then R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; C=$'\033[36m'; X=$'\033[0m'
else R=''; G=''; Y=''; C=''; X=''; fi

RESULTS=()
PASS_COUNT=0
FAIL_COUNT=0

record() {
    local name="$1" pass="$2" detail="$3"
    RESULTS+=("$pass|$name|$detail")
    [ "$pass" = "PASS" ] && PASS_COUNT=$((PASS_COUNT+1)) || FAIL_COUNT=$((FAIL_COUNT+1))
}

echo
echo "${C}===========================================================${X}"
echo "${C} PostgreDataMigrationApp - test${X}"
echo "${C} env         : $ENV_TARGET${X}"
echo "${C} python      : yes${X}"
echo "${C} sql suite   : $([ "$SKIP_SQL" -eq 1 ] || [ "$ONLY_PYTHON" -eq 1 ] && echo SKIP || echo yes)${X}"
echo "${C} evals       : $([ "$SKIP_EVALS" -eq 1 ] || [ "$ONLY_PYTHON" -eq 1 ] && echo SKIP || echo yes)${X}"
echo "${C}===========================================================${X}"
echo

# --- Layer 1: pytest ---
echo "${Y}[layer 1] pytest -m unit${X}"
if command -v pytest >/dev/null 2>&1; then
    if pytest -m unit --tb=short; then
        echo "${G}[layer 1] PASS${X}"
        record "pytest unit" PASS "exit=0"
    else
        echo "${R}[layer 1] FAIL${X}"
        record "pytest unit" FAIL "exit=$?"
    fi
else
    echo "${R}[layer 1] FAIL: pytest not installed${X}"
    echo "${Y}    Run: pip install -r requirements-dev.txt${X}"
    record "pytest unit" FAIL "pytest missing — pip install -r requirements-dev.txt"
fi

# --- Layer 2: SQL suite ---
if [ "$SKIP_SQL" -eq 0 ] && [ "$ONLY_PYTHON" -eq 0 ]; then
    echo
    echo "${Y}[layer 2] SQL test suite (env=$ENV_TARGET)${X}"
    if ! command -v psql >/dev/null 2>&1; then
        echo "${Y}[layer 2] SKIP: psql not on PATH${X}"
        record "sql suite" PASS "skipped: psql missing"
    elif [ -z "${PGPASSWORD:-}" ]; then
        echo "${Y}[layer 2] SKIP: PGPASSWORD not set${X}"
        record "sql suite" PASS "skipped: env vars"
    elif [ ! -f tests/run_tests.sh ]; then
        echo "${Y}[layer 2] SKIP: tests/run_tests.sh missing${X}"
        record "sql suite" PASS "skipped: runner missing"
    else
        if bash tests/run_tests.sh "$ENV_TARGET"; then
            echo "${G}[layer 2] PASS${X}"
            record "sql suite" PASS "exit=0"
        else
            echo "${R}[layer 2] FAIL${X}"
            record "sql suite" FAIL "exit=$?"
        fi
    fi
fi

# --- Layer 3: evals ---
if [ "$SKIP_EVALS" -eq 0 ] && [ "$ONLY_PYTHON" -eq 0 ]; then
    echo
    echo "${Y}[layer 3] evals/runner.py${X}"
    if [ ! -f evals/runner.py ]; then
        echo "${Y}[layer 3] SKIP: evals/runner.py missing${X}"
        record "evals" PASS "skipped: runner missing"
    else
        TIERS="p"
        if [ -n "${PGHOST:-}" ] && [ -n "${PGPASSWORD:-}" ]; then
            TIERS="p,i,s"
        fi
        if python3 evals/runner.py --tiers "$TIERS"; then
            echo "${G}[layer 3] PASS${X}"
            record "evals ($TIERS)" PASS "exit=0"
        else
            echo "${R}[layer 3] FAIL${X}"
            record "evals ($TIERS)" FAIL "exit=$?"
        fi
    fi
fi

# --- Summary ---
echo
echo "${C}===========================================================${X}"
echo "${C} Summary: $PASS_COUNT pass, $FAIL_COUNT fail${X}"
echo "${C}===========================================================${X}"
for r in "${RESULTS[@]}"; do
    IFS='|' read -r status name detail <<< "$r"
    if [ "$status" = "PASS" ]; then
        printf "  ${G}%-20s PASS${X}  %s\n" "$name" "$detail"
    else
        printf "  ${R}%-20s FAIL${X}  %s\n" "$name" "$detail"
    fi
done
echo

[ "$FAIL_COUNT" -eq 0 ] && exit 0 || exit 1
