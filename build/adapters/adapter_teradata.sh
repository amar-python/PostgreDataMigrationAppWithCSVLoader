#!/usr/bin/env bash
# =============================================================================
# adapters/adapter_teradata.sh — Teradata Vantage Deployment Adapter
#
# Uses BTEQ (Basic Teradata Query) to execute DDL and DML.
# Requires: bteq installed and on PATH (part of Teradata Tools and Utilities)
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓ TD]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠ TD]${NC} $*"; }
error() { echo -e "${RED}[✗ TD]${NC} $*" >&2; }

ENVS=("$@")
SCHEMA_FILE="${SCRIPT_DIR}/schema/teradata/te_core_schema.sql"
SEED_FILE="${SCRIPT_DIR}/schema/teradata/te_seed_data.sql"

[[ ! -f "$SCHEMA_FILE" ]] && { error "Schema not found: $SCHEMA_FILE"; exit 1; }
command -v bteq &>/dev/null || { error "bteq not found. Install Teradata Tools and Utilities (TTU)."; exit 1; }

SUCCEEDED=(); FAILED=()

for env in "${ENVS[@]}"; do
   E="${env^^}"
   _db_var="TD_DB_${E}";           db="${!_db_var:-}"
   _user_var="TD_APP_USER_${E}";   app_user="${!_user_var:-}"
   _pw_var="TD_APP_PASSWORD_${E}"; app_pw="${!_pw_var:-}"
   _seed_var="SEED_${E}";          seed="${!_seed_var:-}"

   echo ""
   warn "Deploying Teradata ${E}: db=${db}  user=${app_user}  seed=${seed}"

   # Substitute placeholders, then run via BTEQ
   BTEQ_SCRIPT=$(mktemp /tmp/te_td_${env}_XXXXXX.btq)
   # BTEQ_SCRIPT holds a cleartext .LOGON password below; the explicit
   # `rm -f` at the end of this iteration handles normal completion, but a
   # crash/kill mid-iteration would otherwise leave the password on disk —
   # the trap covers that case too.
   trap 'rm -f "$BTEQ_SCRIPT"' EXIT

   # BTEQ login header
   cat > "$BTEQ_SCRIPT" << BTEQHDR
.LOGON ${TD_HOST}/${TD_USER},${TD_PASSWORD};
BTEQHDR

   # Append substituted schema SQL
   sed \
      -e "s|{{DB_NAME}}|${db}|g" \
      -e "s|{{APP_USER}}|${app_user}|g" \
      -e "s|{{APP_PASSWORD}}|${app_pw}|g" \
      -e "s|{{PERM_SPACE_MB}}|${TD_PERM_SPACE_MB}|g" \
      -e "s|{{SPOOL_SPACE_MB}}|${TD_SPOOL_SPACE_MB}|g" \
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
      "$SCHEMA_FILE" >> "$BTEQ_SCRIPT"

   # Append seed data if requested
   if [[ "$seed" == "true" && -f "$SEED_FILE" ]]; then
      sed -e "s|{{DB_NAME}}|${db}|g" "$SEED_FILE" >> "$BTEQ_SCRIPT"
   fi

   echo ".LOGOFF;" >> "$BTEQ_SCRIPT"
   echo ".QUIT 0;"  >> "$BTEQ_SCRIPT"

   if bteq < "$BTEQ_SCRIPT" 2>&1; then
      log "${E} deployed successfully."
      SUCCEEDED+=("$env")
   else
      error "${E} BTEQ execution FAILED."
      FAILED+=("$env")
   fi

   rm -f "$BTEQ_SCRIPT"
done

[[ ${#SUCCEEDED[@]} -gt 0 ]] && echo -e "${GREEN}[✓]${NC} Succeeded: ${SUCCEEDED[*]}"
[[ ${#FAILED[@]}    -gt 0 ]] && { echo -e "${RED}[✗]${NC} Failed: ${FAILED[*]}"; exit 1; }
