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
# InfluxDB / Redis / Teradata. Multi-engine routing is tracked in docs/VCRM_GAPS.md
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

# Read one \set variable from an environment launcher (RV-S1, #172).
# env_<env>.sql is the single place that says which database an environment
# deploys to and who owns it. This script used to keep its own copy
# (te_mgmt_<env>, owner postgres) which drifted from Terraform's.
launcher_var() {
   tr -d '\r' < "$1" | sed -n "s/^\\\\set[[:space:]][[:space:]]*$2[[:space:]][[:space:]]*'\{0,1\}\([^' ]*\)'\{0,1\}.*/\1/p" | head -n1
}

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

   DB_NAME="$(launcher_var "${env_file}" db_name)"
   DB_OWNER="$(launcher_var "${env_file}" db_owner)"
   # Both land inside quoted SQL identifiers/literals below, so insist on plain names.
   if [[ ! "${DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ || ! "${DB_OWNER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      error "${env_file}: db_name ('${DB_NAME}') and db_owner ('${DB_OWNER}') must both be set to plain identifiers."
      FAILED+=("${env}")
      continue
   fi

   echo ""
   warn "Deploying environment: ${env^^}  (database: ${DB_NAME})"

   # Create the database if it doesn't exist.
   # CREATE DATABASE cannot run inside a transaction, so we handle it here
   # at the shell level rather than inside te_core_schema.sql's DO block.
   DB_EXISTS=$(${PSQL} -d postgres -tA -c \
      "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" 2>/dev/null || true)
   if [[ -z "${DB_EXISTS}" ]]; then
      # The owner has to exist before it can own anything. On Azure it is the
      # server admin and already does. Anywhere else (CI, the offline install, a
      # fresh dev server) it is created NOLOGIN: it owns the database and nothing
      # else, so it adds no credential and no way in.
      OWNER_EXISTS=$(${PSQL} -d postgres -tA -c \
         "SELECT 1 FROM pg_roles WHERE rolname = '${DB_OWNER}'" 2>/dev/null || true)
      if [[ -z "${OWNER_EXISTS}" ]]; then
         log "Creating database owner role: ${DB_OWNER} (NOLOGIN)"
         ${PSQL} -d postgres -c "CREATE ROLE \"${DB_OWNER}\" NOLOGIN" || {
            error "Failed to create owner role ${DB_OWNER}"
            FAILED+=("${env}")
            continue
         }
      fi
      log "Creating database: ${DB_NAME} (owner: ${DB_OWNER})"
      ${PSQL} -d postgres -c \
         "CREATE DATABASE \"${DB_NAME}\"
            WITH OWNER = \"${DB_OWNER}\"
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
      # Report drift, never fix it: changing the owner of a database that already
      # holds data is not a decision a deploy script should take silently.
      ACTUAL_OWNER=$(${PSQL} -d postgres -tA -c \
         "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '${DB_NAME}'" 2>/dev/null || true)
      if [[ -n "${ACTUAL_OWNER}" && "${ACTUAL_OWNER}" != "${DB_OWNER}" ]]; then
         warn "${DB_NAME} is owned by '${ACTUAL_OWNER}', but ${env_file##*/} says '${DB_OWNER}'. Left unchanged."
      fi
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
