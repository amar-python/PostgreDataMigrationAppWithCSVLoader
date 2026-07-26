#!/usr/bin/env bash
# preflight.sh - pre-deploy smoke checks for PostgreDataMigrationApp (Linux/Mac/Git-Bash)
#
# Usage:
#   ./preflight.sh                    # check everything
#   ./preflight.sh --skip-pg          # don't try to connect to PostgreSQL
#   ./preflight.sh --azure            # also check Azure CLI + Docker
#
# Exit codes:
#   0 = all required checks passed
#   1 = at least one required check failed
#   2 = at least one optional check warned (other required passed)

set -u  # don't `set -e` - we want to keep going after failures

SKIP_PG=0
AZURE=0
for arg in "$@"; do
    case "$arg" in
        --skip-pg) SKIP_PG=1 ;;
        --azure)   AZURE=1 ;;
        -h|--help)
            sed -n '1,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 64 ;;
    esac
done

PASS=0
WARN=0
FAIL=0
ISSUES=()

# Terminal colors (no-op if not a TTY)
if [ -t 1 ]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; C=$'\033[36m'; X=$'\033[0m'
else
    R=''; G=''; Y=''; C=''; X=''
fi

# check NAME REQUIRED COMMAND -- COMMAND-TO-EVAL
# Pass status is determined by the eval's exit code (0 = pass, non-zero = fail).
# REQUIRED is "req" or "opt"; opt failures count as warnings.
check() {
    local name="$1"; local req="$2"; local hint="$3"; shift 3
    printf "  [%s] ... " "$name"
    if "$@" >/dev/null 2>&1; then
        printf "%sPASS%s\n" "$G" "$X"
        PASS=$((PASS+1))
    else
        if [ "$req" = "req" ]; then
            printf "%sFAIL%s\n" "$R" "$X"
            FAIL=$((FAIL+1))
            ISSUES+=("FAIL|$name|$hint")
        else
            printf "%sWARN%s\n" "$Y" "$X"
            WARN=$((WARN+1))
            ISSUES+=("WARN|$name|$hint")
        fi
    fi
}

echo
echo "${C}===========================================================${X}"
echo "${C} PostgreDataMigrationApp - preflight smoke checks${X}"
echo "${C}===========================================================${X}"
echo

# ----- Tools -----
echo "${C}Tools${X}"
check 'python3 on PATH'             req 'Install python 3.10+ (apt/brew/winget)' command -v python3
check 'python >= 3.10'              req 'Upgrade python to 3.10 or later' \
      bash -c 'python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"'
check 'git on PATH'                 req 'Install git' command -v git
check 'psql on PATH'                opt 'Add PG client to PATH. brew install postgresql / apt install postgresql-client' \
      command -v psql

# ----- Project files -----
echo
echo "${C}Project files${X}"
check 'in project root (build/ tests/ evals/)' req 'cd into the PostgreDataMigrationApp folder first' \
      bash -c '[ -d build ] && [ -d tests ] && [ -d evals ]'
check 'evals/runner.py exists'      req 'Project files missing/corrupt' test -f evals/runner.py
check 'build/deploy_all.sh exists'  req 'Project files missing/corrupt' test -f build/deploy_all.sh

# ----- Git state -----
echo
echo "${C}Git state${X}"
check 'inside a git repo'           req 'Not a git repo. Did you clone PostgreDataMigrationApp?' \
      git rev-parse --is-inside-work-tree
check 'working tree clean'          opt 'Uncommitted changes. git status; commit or stash before deploying.' \
      bash -c '[ -z "$(git status --porcelain)" ]'
check 'remote origin configured'    opt 'No remote. Add one with `git remote add origin <url>`.' \
      git remote get-url origin

# ----- PostgreSQL -----
if [ "$SKIP_PG" -eq 0 ]; then
    echo
    echo "${C}PostgreSQL${X}"

    check 'PGHOST env var set'      opt 'export PGHOST=localhost (and PGPORT/PGUSER/PGPASSWORD/PGDATABASE)' \
          bash -c '[ -n "${PGHOST:-}" ]'

    HOST="${PGHOST:-localhost}"
    PORT="${PGPORT:-5432}"
    check "port $PORT reachable on $HOST" opt 'PG not listening. Check service is running and listen_addresses.' \
          bash -c "(timeout 3 bash -c '</dev/tcp/$HOST/$PORT') 2>/dev/null"

    if command -v psql >/dev/null 2>&1 && [ -n "${PGPASSWORD:-}" ]; then
        check 'PG accepts the configured credentials' opt 'psql `SELECT 1` failed. Recheck PGUSER/PGPASSWORD/PGDATABASE.' \
              psql -h "$HOST" -p "$PORT" -U "${PGUSER:-postgres}" -d "${PGDATABASE:-postgres}" -c 'SELECT 1'
    fi
fi

# ----- Azure -----
if [ "$AZURE" -eq 1 ]; then
    echo
    echo "${C}Azure${X}"
    check 'az CLI on PATH'          req 'Install Azure CLI. https://aka.ms/installazurecli' command -v az
    check 'az logged in'            req 'Run `az login` first.' az account show
    check 'docker on PATH'          opt 'Docker not installed. For Azure deploy use Cloud Shell + `az acr build` instead.' \
          command -v docker
    check 'terraform on PATH'       opt 'Terraform not installed. Cloud Shell has it pre-installed as a fallback.' \
          command -v terraform
fi

# ----- Summary -----
echo
echo "${C}===========================================================${X}"
echo "${C} Summary: $PASS passed, $WARN warned, $FAIL failed${X}"
echo "${C}===========================================================${X}"

if [ "${#ISSUES[@]}" -gt 0 ]; then
    echo
    echo "${Y}Issues to address:${X}"
    for issue in "${ISSUES[@]}"; do
        IFS='|' read -r status name hint <<< "$issue"
        if [ "$status" = "FAIL" ]; then
            printf "  %s[FAIL]%s %s\n         %s\n" "$R" "$X" "$name" "$hint"
        else
            printf "  %s[WARN]%s %s\n         %s\n" "$Y" "$X" "$name" "$hint"
        fi
    done
fi

echo

[ "$FAIL" -gt 0 ] && exit 1
[ "$WARN" -gt 0 ] && exit 2
exit 0
