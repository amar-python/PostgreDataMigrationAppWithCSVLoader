#!/usr/bin/env bash
# =============================================================================
# deploy_all.sh — Deploy all Defence T&E environments in sequence
# Usage:
#   ./deploy_all.sh                        # deploy all 4 environments
#   ./deploy_all.sh dev test               # deploy dev and test only
#   PGHOST=myserver ./deploy_all.sh prod   # target a specific host
#
# Prerequisites:
#   - psql installed and on PATH
#   - Running as a PostgreSQL superuser (default: postgres)
#   - Script run from the te_database_setup/ directory
#
# SCOPE NOTE: This deployer is intentionally PostgreSQL-only despite the
# presence of build/adapters/adapter_<engine>.sh stubs for MariaDB / SQLite /
# InfluxDB / Redis / Teradata. Multi-engine routing is tracked in VCRM_GAPS.md
# as BR-02 (deferred). When you add it, the natural place is right before the
# deploy loop below: dispatch to build/adapters/adapter_$ENGINE.sh instead of
# running psql directly. Until then, only PostgreSQL targets are validated by
# the eval suite (Tier S in particular).
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PG_USER="${PGUSER:-postgres}"
PG_HOST="${PGHOST:-localhost}"
PG_PORT="${PGPORT:-5432}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PSQL="psql -U ${PG_USER} -h ${PG_HOST} -p ${PG_PORT}"

ALL_ENVS=(dev test staging prod)

# Colours
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
log()     { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[⚠]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }
separator(){ echo "────────────────────────────────────────────────────────────"; }

# ── Parse arguments ───────────────────────────────────────────────────────────
ENVS_TO_DEPLOY=("${@:-${ALL_ENVS[@]}}")

# Validate each requested environment
for env in "${ENVS_TO_DEPLOY[@]}"; do
   if [[ ! " ${ALL_ENVS[*]} " =~ " ${env} " ]]; then
      error "Unknown environment: '${env}'. Valid options: ${ALL_ENVS[*]}"
      exit 1
   fi
done

# ── Main deployment loop ──────────────────────────────────────────────────────
separator
echo "  Defence T&E Database Deployment"
echo "  Host     : ${PG_HOST}:${PG_PORT}"
echo "  User     : ${PG_USER}"
echo "  Targets  : ${ENVS_TO_DEPLOY[*]}"
separator

FAILED=()
SUCCEEDED=()

for env in "${ENVS_TO_DEPLOY[@]}"; do
   env_file="${SCRIPT_DIR}/environments/env_${env}.sql"

   if [[ ! -f "${env_file}" ]]; then
      error "Environment file not found: ${env_file}"
      FAILED+=("${env}")
      continue
   fi

   DB_NAME="te_mgmt_${env}"

   echo ""
   warn "Deploying environment: ${env^^}  (database: ${DB_NAME})"

   # Create the database if it doesn't exist.
   # CREATE DATABASE cannot run inside a transaction, so we handle it here
   # at the shell level rather than inside te_core_schema.sql's DO block.
   DB_EXISTS=$(${PSQL} -d postgres -tA -c \
      "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" 2>/dev/null || true)
   if [[ -z "${DB_EXISTS}" ]]; then
      log "Creating database: ${DB_NAME}"
      ${PSQL} -d postgres -c \
         "CREATE DATABASE \"${DB_NAME}\"
            WITH OWNER = postgres
            ENCODING = 'UTF8'
            TEMPLATE = template0
            CONNECTION LIMIT = -1" || {
         error "Failed to create database ${DB_NAME}"
         FAILED+=("${env}")
         continue
      }
      log "Database ${DB_NAME} created."
   else
      log "Database ${DB_NAME} already exists — skipping CREATE."
   fi

   if ${PSQL} \
         --set=ON_ERROR_STOP=1 \
         --file="${env_file}" \
         2>&1; then
      log "Environment ${env^^} deployed successfully."
      SUCCEEDED+=("${env}")
   else
      error "Deployment FAILED for environment: ${env^^}"
      FAILED+=("${env}")
   fi

   separator
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "  Deployment Summary"
separator
if [[ ${#SUCCEEDED[@]} -gt 0 ]]; then
   log "Succeeded : ${SUCCEEDED[*]}"
fi
if [[ ${#FAILED[@]} -gt 0 ]]; then
   error "Failed    : ${FAILED[*]}"
   exit 1
fi
echo ""
