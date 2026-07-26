#!/usr/bin/env bash
# =============================================================================
# run_tests.sh — Run the T&E test suite against one or more environments
#
# Usage:
#   ./tests/run_tests.sh                    # run against all 4 environments
#   ./tests/run_tests.sh dev                # dev only
#   ./tests/run_tests.sh dev test           # dev and test
#   PGHOST=myserver ./tests/run_tests.sh staging
#
# Prerequisites:
#   - psql on PATH
#   - The target database(s) must already be deployed (run deploy_all.sh first)
#   - Run from the te_database_setup/ directory
# =============================================================================

set -euo pipefail

# ── PostgreSQL connection ──────────────────────────────────────────────────────
PG_USER="${PGUSER:-postgres}"
PG_HOST="${PGHOST:-localhost}"
PG_PORT="${PGPORT:-5432}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Colour codes ───────────────────────────────────────────────────────────────
GREEN='\033[0;32m';  RED='\033[0;31m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()       { echo -e "${GREEN}[✓]${NC} $*"; }
warn()      { echo -e "${YELLOW}[⚠]${NC} $*"; }
error()     { echo -e "${RED}[✗]${NC} $*" >&2; }
info()      { echo -e "${CYAN}[i]${NC} $*"; }
separator() { echo "────────────────────────────────────────────────────────────"; }

# ── Environment → DB/schema/table mapping ─────────────────────────────────────
declare -A ENV_DB=(
   [dev]="te_mgmt_dev"
   [test]="te_mgmt_test"
   [staging]="te_mgmt_staging"
   [prod]="te_mgmt_prod"
)
declare -A ENV_SCHEMA=(
   [dev]="te_dev"
   [test]="te_test"
   [staging]="te_staging"
   [prod]="te_prod"
)
declare -A ENV_APP_USER=(
   [dev]="te_dev_user"
   [test]="te_test_user"
   [staging]="te_stg_user"
   [prod]="te_prod_user"
)
declare -A ENV_CONN_LIMIT=(
   [dev]="10"
   [test]="15"
   [staging]="20"
   [prod]="50"
)

ALL_ENVS=(dev test staging prod)
TABLE_VARS=(
   "tbl_organisations=organisations"
   "tbl_personnel=personnel"
   "tbl_test_programs=test_programs"
   "tbl_temp_documents=temp_documents"
   "tbl_test_phases=test_phases"
   "tbl_requirements=requirements"
   "tbl_test_cases=test_cases"
   "tbl_vcrm_entries=vcrm_entries"
   "tbl_test_events=test_events"
   "tbl_test_results=test_results"
   "tbl_defect_reports=defect_reports"
   "tbl_evidence_artifacts=evidence_artifacts"
)

# ── Helpers ────────────────────────────────────────────────────────────────────
build_psql_vars() {
   local env="$1"
   local schema="${ENV_SCHEMA[$env]}"
   local vars="--set schema_name=${schema}"
   vars+=" --set app_user=${ENV_APP_USER[$env]}"
   vars+=" --set conn_limit=${ENV_CONN_LIMIT[$env]}"
   for kv in "${TABLE_VARS[@]}"; do
      vars+=" --set ${kv}"
   done
   echo "${vars}"
}

run_suite() {
   local env="$1"
   local db="${ENV_DB[$env]}"
   local schema="${ENV_SCHEMA[$env]}"
   local vars
   vars=$(build_psql_vars "${env}")

   separator
   info "Running tests against: ${env^^}  (db=${db}  schema=${schema})"
   separator

   local outfile
   outfile=$(mktemp /tmp/te_test_${env}_XXXXXX.out)

   if psql \
         -U "${PG_USER}" \
         -h "${PG_HOST}" \
         -p "${PG_PORT}" \
         -d "${db}" \
         ${vars} \
         --set=ON_ERROR_STOP=1 \
         --file="${SCRIPT_DIR}/tests/run_all_tests.sql" \
         2>&1 | tee "${outfile}"; then
      log "Test run for ${env^^} completed."
   else
      error "Test run FAILED for ${env^^} — check output above."
      FAILED_ENVS+=("${env}")
   fi

   # Extract overall result line from psql output for the summary table
   local overall
   overall=$(grep -E '(ALL TESTS PASSED|TEST\(S\) FAILED)' "${outfile}" \
             | tail -1 | xargs || echo "unknown")
   RESULTS["${env}"]="${overall}"

   rm -f "${outfile}"
}

# ── Parse arguments ────────────────────────────────────────────────────────────
ENVS_TO_TEST=("${@:-${ALL_ENVS[@]}}")

for env in "${ENVS_TO_TEST[@]}"; do
   if [[ -z "${ENV_DB[$env]+_}" ]]; then
      error "Unknown environment '${env}'. Valid: ${ALL_ENVS[*]}"
      exit 1
   fi
done

# ── Main ───────────────────────────────────────────────────────────────────────
separator
echo "  Defence T&E — Test Suite Runner"
echo "  Host     : ${PG_HOST}:${PG_PORT}"
echo "  User     : ${PG_USER}"
echo "  Targets  : ${ENVS_TO_TEST[*]}"
separator

declare -A RESULTS
FAILED_ENVS=()

for env in "${ENVS_TO_TEST[@]}"; do
   run_suite "${env}"
done

# ── Final summary ──────────────────────────────────────────────────────────────
echo ""
separator
echo "  OVERALL TEST SUMMARY"
separator
printf "  %-12s  %s\n" "Environment" "Result"
printf "  %-12s  %s\n" "-----------" "------"
for env in "${ENVS_TO_TEST[@]}"; do
   result="${RESULTS[$env]:-no output}"
   if echo "${result}" | grep -q "ALL TESTS PASSED"; then
      printf "  ${GREEN}%-12s${NC}  ${GREEN}%s${NC}\n" "${env^^}" "${result}"
   else
      printf "  ${RED}%-12s${NC}  ${RED}%s${NC}\n" "${env^^}" "${result}"
   fi
done
separator

if [[ ${#FAILED_ENVS[@]} -gt 0 ]]; then
   error "Failures in: ${FAILED_ENVS[*]}"
   exit 1
else
   log "All test runs completed successfully."
fi
