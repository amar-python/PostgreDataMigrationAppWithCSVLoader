#!/usr/bin/env bash
# =============================================================================
# adapters/adapter_sqlite.sh — SQLite 3 Deployment Adapter
# =============================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓ SQLITE]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠ SQLITE]${NC} $*"; }
error() { echo -e "${RED}[✗ SQLITE]${NC} $*" >&2; }

ENVS=("$@")
SCHEMA_FILE="${SCRIPT_DIR}/schema/sqlite/te_core_schema.sql"
SEED_FILE="${SCRIPT_DIR}/schema/sqlite/te_seed_data.sql"

[[ ! -f "$SCHEMA_FILE" ]] && { error "Schema not found: $SCHEMA_FILE"; exit 1; }
command -v sqlite3 &>/dev/null || { error "sqlite3 not found on PATH."; exit 1; }

mkdir -p "${SQLITE_DIR}"
SUCCEEDED=(); FAILED=()

for env in "${ENVS[@]}"; do
   E="${env^^}"
   db_file="${SQLITE_DIR}/$(eval echo "\$SQLITE_DB_${E}")"
   seed="$(eval echo "\$SEED_${E}")"

   echo ""
   warn "Deploying SQLite ${E}: file=${db_file}  seed=${seed}"

   if sed \
      -e "s|{{TBL_ORGANISATIONS}}|${TBL_ORGANISATIONS}|g" \
      -e "s|{{TBL_PERSONNEL}}|${TBL_PERSONNEL}|g" \
      -e "s|{{TBL_TEST_PROGRAMS}}|${TBL_TEST_PROGRAMS}|g" \
      -e "s|{{TBL_TEMP_DOCUMENTS}}|${TBL_TEMP_DOCUMENTS}|g" \
      -e "s|{{TBL_TEST_PHASES}}|${TBL_TEST_PHASES}|g" \
      -e "s|{{TBL_REQUIREMENTS}}|${TBL_REQUIREMENTS}|g" \
      -e "s|{{TBL_TEST_CASES}}|${TBL_TEST_CASES}|g" \
      -e "s|{{TBL_VCRM_ENTRIES}}|${TBL_VCRM_ENTRIES}|g" \
      -e "s|{{TBL_TEST_EVENTS}}|${TBL_TEST_EVENTS}|g" \
      -e "s|{{TBL_TEST_RESULTS}}|${TBL_TEST_RESULTS}|g" \
      -e "s|{{TBL_DEFECT_REPORTS}}|${TBL_DEFECT_REPORTS}|g" \
      -e "s|{{TBL_EVIDENCE_ARTIFACTS}}|${TBL_EVIDENCE_ARTIFACTS}|g" \
      "$SCHEMA_FILE" | sqlite3 "$db_file" 2>&1; then
      log "${E} schema deployed: ${db_file}"

      if [[ "$seed" == "true" && -f "$SEED_FILE" ]]; then
         sqlite3 "$db_file" < "$SEED_FILE" 2>&1 \
            && log "${E} seed data loaded." \
            || warn "${E} seed data failed."
      fi
      SUCCEEDED+=("$env")
   else
      error "${E} deployment FAILED."
      FAILED+=("$env")
   fi
done

[[ ${#SUCCEEDED[@]} -gt 0 ]] && echo -e "${GREEN}[✓]${NC} Succeeded: ${SUCCEEDED[*]}"
[[ ${#FAILED[@]}    -gt 0 ]] && { echo -e "${RED}[✗]${NC} Failed: ${FAILED[*]}"; exit 1; }
