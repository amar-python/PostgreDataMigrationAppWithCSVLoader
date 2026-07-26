#!/usr/bin/env bash
# =============================================================================
# adapters/adapter_mariadb.sh — MariaDB / MySQL Deployment Adapter
# Called by deploy_all.sh — do not run directly.
# =============================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓ MYSQL]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠ MYSQL]${NC} $*"; }
error() { echo -e "${RED}[✗ MYSQL]${NC} $*" >&2; }

ENVS=("$@")
SCHEMA_FILE="${SCRIPT_DIR}/schema/mariadb/te_core_schema.sql"
SEED_FILE="${SCRIPT_DIR}/schema/mariadb/te_seed_data.sql"

[[ ! -f "$SCHEMA_FILE" ]] && { error "Schema not found: $SCHEMA_FILE"; exit 1; }

MYSQL_OPTS="-h ${MYSQL_HOST} -P ${MYSQL_PORT} -u ${MYSQL_ROOT_USER}"
[[ -n "${MYSQL_ROOT_PASSWORD:-}" ]] && MYSQL_OPTS+=" -p${MYSQL_ROOT_PASSWORD}"

SUCCEEDED=(); FAILED=()

for env in "${ENVS[@]}"; do
   E="${env^^}"
   db="$(eval echo "\$MYSQL_DB_${E}")"
   app_user="$(eval echo "\$MYSQL_APP_USER_${E}")"
   app_pw="$(eval echo "\$MYSQL_APP_PASSWORD_${E}")"
   seed="$(eval echo "\$SEED_${E}")"

   echo ""
   warn "Deploying MariaDB ${E}: db=${db}  user=${app_user}  seed=${seed}"

   # Substitute variables into schema SQL using sed and pipe to mysql
   if sed \
      -e "s|{{DB_NAME}}|${db}|g" \
      -e "s|{{APP_USER}}|${app_user}|g" \
      -e "s|{{APP_PASSWORD}}|${app_pw}|g" \
      -e "s|{{CHARSET}}|${MYSQL_CHARSET}|g" \
      -e "s|{{COLLATION}}|${MYSQL_COLLATION}|g" \
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
      "$SCHEMA_FILE" | mysql $MYSQL_OPTS 2>&1; then
      log "${E} schema deployed."

      # Load seed data if requested
      if [[ "$seed" == "true" && -f "$SEED_FILE" ]]; then
         sed -e "s|{{DB_NAME}}|${db}|g" "$SEED_FILE" | mysql $MYSQL_OPTS 2>&1 \
            && log "${E} seed data loaded." \
            || warn "${E} seed data failed — check ${SEED_FILE}"
      fi

      SUCCEEDED+=("$env")
   else
      error "${E} deployment FAILED."
      FAILED+=("$env")
   fi
done

[[ ${#SUCCEEDED[@]} -gt 0 ]] && echo -e "${GREEN}[✓]${NC} Succeeded: ${SUCCEEDED[*]}"
[[ ${#FAILED[@]}    -gt 0 ]] && { echo -e "${RED}[✗]${NC} Failed: ${FAILED[*]}"; exit 1; }
