#!/usr/bin/env bash
# =============================================================================
# adapters/adapter_postgresql.sh — PostgreSQL 15 Deployment Adapter
# Called by deploy_all.sh — do not run directly.
# =============================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓ PG]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠ PG]${NC} $*"; }
error() { echo -e "${RED}[✗ PG]${NC} $*" >&2; }

ENVS=("$@")
SCHEMA_FILE="${SCRIPT_DIR}/schema/postgresql/te_core_schema.sql"

[[ ! -f "$SCHEMA_FILE" ]] && { error "Schema not found: $SCHEMA_FILE"; exit 1; }

PSQL_OPTS="-h ${PG_HOST} -p ${PG_PORT} -U ${PG_SUPERUSER}"
[[ -n "${PG_SUPERUSER_PASSWORD:-}" ]] && export PGPASSWORD="${PG_SUPERUSER_PASSWORD}"

get() { local E="${1^^}"; eval echo "\${PG_${2}_${E}}"; }

SUCCEEDED=(); FAILED=()

for env in "${ENVS[@]}"; do
   E="${env^^}"
   db="$(get "$env" DB)"
   schema="$(get "$env" SCHEMA)"
   app_user="$(get "$env" APP_USER)"
   app_pw="$(get "$env" APP_PASSWORD)"
   conn_limit="$(get "$env" CONN_LIMIT)"
   seed="$(eval echo "\$SEED_${E}")"

   echo ""
   warn "Deploying PostgreSQL ${E}: db=${db}  schema=${schema}  seed=${seed}"

   if psql $PSQL_OPTS --set=ON_ERROR_STOP=1 \
      --set env_label="${E}" \
      --set db_name="${db}" \
      --set db_owner="${PG_SUPERUSER}" \
      --set schema_name="${schema}" \
      --set app_user="${app_user}" \
      --set app_password="${app_pw}" \
      --set conn_limit="${conn_limit}" \
      --set include_seed_data="${seed}" \
      --set tbl_organisations="${TBL_ORGANISATIONS}" \
      --set tbl_personnel="${TBL_PERSONNEL}" \
      --set tbl_test_programs="${TBL_TEST_PROGRAMS}" \
      --set tbl_temp_documents="${TBL_TEMP_DOCUMENTS}" \
      --set tbl_test_phases="${TBL_TEST_PHASES}" \
      --set tbl_requirements="${TBL_REQUIREMENTS}" \
      --set tbl_test_cases="${TBL_TEST_CASES}" \
      --set tbl_vcrm_entries="${TBL_VCRM_ENTRIES}" \
      --set tbl_test_events="${TBL_TEST_EVENTS}" \
      --set tbl_test_results="${TBL_TEST_RESULTS}" \
      --set tbl_defect_reports="${TBL_DEFECT_REPORTS}" \
      --set tbl_evidence_artifacts="${TBL_EVIDENCE_ARTIFACTS}" \
      --file="${SCHEMA_FILE}" 2>&1; then
      log "${E} deployed successfully."
      SUCCEEDED+=("$env")
   else
      error "${E} deployment FAILED."
      FAILED+=("$env")
   fi
done

unset PGPASSWORD
[[ ${#SUCCEEDED[@]} -gt 0 ]] && echo -e "${GREEN}[✓]${NC} Succeeded: ${SUCCEEDED[*]}"
[[ ${#FAILED[@]}    -gt 0 ]] && { echo -e "${RED}[✗]${NC} Failed: ${FAILED[*]}"; exit 1; }
