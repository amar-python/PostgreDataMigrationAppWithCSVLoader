#!/usr/bin/env bash
# =============================================================================
# deploy_all.sh — Deploy all Defence T&E environments in sequence
# Usage:
#   ./deploy_all.sh                        # deploy all 4 environments
#   ./deploy_all.sh dev test               # deploy dev and test only
#   PGHOST=myserver ./deploy_all.sh prod   # target a specific host
#   ./deploy_all.sh --dry-run prod         # show the database and owner each
#                                          # launcher names, touch nothing
#   ./deploy_all.sh --yes dev              # use a database that already exists
#                                          # without asking (also -y)
#
# A database that already exists is never recreated. When a person is at the terminal,
# the script asks before applying the schema to it; answer y to use it, anything else
# skips that environment and changes nothing. With no terminal (CI, a container, a
# pipe) or with --yes it uses the existing database without asking.
#
# Prerequisites:
#   - psql installed and on PATH (checked up front; a --dry-run does not need it)
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

# On Windows the PostgreSQL installer puts psql.exe under Program Files but does not
# add it to PATH. Look there, newest version first, so the message can name the exact
# folder. PROGRAMFILES is C:\Program Files in Git Bash; cygpath converts it.
find_installed_psql() {
   local pf="${PROGRAMFILES:-}" root
   if [[ -n "${pf}" ]] && command -v cygpath >/dev/null 2>&1; then
      root="$(cygpath -u "${pf}")"
   elif [[ "${pf}" == /* ]]; then
      root="${pf}"
   else
      root="/c/Program Files"
   fi
   ls -1d "${root}"/PostgreSQL/*/bin/psql.exe 2>/dev/null | sort -V | tail -n 1 || true
}

# A real run needs psql. Without this check a missing psql was read as "the database
# does not exist": the script printed a green "Creating database" and only then failed.
require_psql() {
   if command -v psql >/dev/null 2>&1; then return 0; fi
   error "psql was not found on PATH. This script needs the PostgreSQL client tools."
   local found
   found="$(find_installed_psql)"
   if [[ -n "${found}" ]]; then
      echo "      PostgreSQL is installed, but its bin folder is not on PATH. In Git Bash:" >&2
      echo "          export PATH=\"$(dirname "${found}"):\$PATH\"" >&2
      echo "      then run this script again. To keep it, add that folder to the Windows PATH." >&2
   else
      case "$(uname -s 2>/dev/null || true)" in
         MINGW*|MSYS*|CYGWIN*)
            echo "      Install PostgreSQL (tick 'Command Line Tools'), then add its bin folder," >&2
            echo "      for example C:\\Program Files\\PostgreSQL\\<version>\\bin, to the Windows PATH." >&2 ;;
         Darwin*) echo "      Install it with: brew install libpq   (then add it to PATH as brew says)" >&2 ;;
         *)       echo "      Install it with: apt install postgresql-client   (or your distribution's equivalent)" >&2 ;;
      esac
   fi
   exit 1
}

# Say once, before touching anything, if the server cannot be reached: a wrong port, a
# server that is not running or a missing password otherwise repeat for every environment.
require_server() {
   local out
   if out="$(${PSQL} -d postgres -tA -c 'SELECT 1' 2>&1)"; then return 0; fi
   error "Could not connect to PostgreSQL at ${PG_HOST}:${PG_PORT} as ${PG_USER}:"
   printf '%s\n' "${out}" | sed 's/^/      /' >&2
   echo "      Check that the server is running on that host and port, and that PGPASSWORD is set" >&2
   echo "      for ${PG_USER}. Override with PGHOST, PGPORT, PGUSER and PGPASSWORD." >&2
   exit 1
}

# A database that already exists is reused, never recreated. When a person is at the
# terminal, ask first: deploying into a database they did not mean to touch should be
# their decision. Scripts, CI and containers have no terminal (stdin and stderr must
# both be one), so they keep using it, and --yes says the same explicitly.
# Returns 0 to use the database, 1 to skip this environment.
accept_existing_database() {
   local db="$1" reply=""
   if [[ "${ASSUME_YES}" == true ]] || ! [[ -t 0 && -t 2 ]]; then return 0; fi
   warn "Database ${db} already exists on ${PG_HOST}:${PG_PORT}."
   printf '      Use it and apply the T&E schema to it? [y/N] ' >&2
   read -r reply || reply=""
   [[ "${reply}" =~ ^[Yy]([Ee][Ss])?$ ]]
}

# launcher_var FILE NAME — the value of `\set NAME value` in a launcher, quotes
# stripped; empty if the launcher doesn't set it.
launcher_var() {
   sed -nE "s/^[[:space:]]*\\\\set[[:space:]]+$2[[:space:]]+'?([^'[:space:]]*)'?.*/\\1/p" "$1" | head -n 1
}

# ── Parse arguments ───────────────────────────────────────────────────────────
# --dry-run prints each environment's target database and owner, as read from
# its launcher, and exits before touching PostgreSQL.
DRY_RUN=false
ASSUME_YES=false
REQUESTED=()
for arg in "$@"; do
   case "${arg}" in
      --dry-run)  DRY_RUN=true ;;
      --yes|-y)   ASSUME_YES=true ;;
      *)          REQUESTED+=("${arg}") ;;
   esac
done
ENVS_TO_DEPLOY=("${REQUESTED[@]:-${ALL_ENVS[@]}}")

# Validate each requested environment
for env in "${ENVS_TO_DEPLOY[@]}"; do
   if [[ ! " ${ALL_ENVS[*]} " =~ " ${env} " ]]; then
      error "Unknown environment: '${env}'. Valid options: ${ALL_ENVS[*]}"
      exit 1
   fi
done

# ── Prerequisites ─────────────────────────────────────────────────────────────
# A dry run reads launchers only, so it needs neither psql nor a server.
if [[ "${DRY_RUN}" != true ]]; then
   require_psql
   require_server
fi

# ── Main deployment loop ──────────────────────────────────────────────────────
separator
echo "  Defence T&E Database Deployment"
echo "  Host     : ${PG_HOST}:${PG_PORT}"
echo "  User     : ${PG_USER}"
echo "  Targets  : ${ENVS_TO_DEPLOY[*]}"
separator

FAILED=()
SUCCEEDED=()
SKIPPED=()

for env in "${ENVS_TO_DEPLOY[@]}"; do
   env_file="${SCRIPT_DIR}/environments/env_${env}.sql"

   if [[ ! -f "${env_file}" ]]; then
      error "Environment file not found: ${env_file}"
      FAILED+=("${env}")
      continue
   fi

   # The launcher is the single source of truth for the database name and owner
   # (#172). Hard-coding them here let the deployer disagree with the launcher
   # and with the infrastructure that built the server. The defaults below are
   # the on-prem names, used only when a launcher doesn't set them.
   DB_NAME="$(launcher_var "${env_file}" db_name)"
   DB_NAME="${DB_NAME:-te_mgmt_${env}}"
   DB_OWNER="$(launcher_var "${env_file}" db_owner)"
   DB_OWNER="${DB_OWNER:-postgres}"
   unsafe=""
   for ident in "${DB_NAME}" "${DB_OWNER}"; do
      [[ "${ident}" =~ ^[a-z_][a-z0-9_]*$ ]] || unsafe="${ident}"
   done
   if [[ -n "${unsafe}" ]]; then
      error "Unsafe identifier '${unsafe}' in ${env_file} (use lower-case letters, digits and underscores)"
      FAILED+=("${env}")
      continue
   fi

   echo ""
   warn "Deploying environment: ${env^^}  (database: ${DB_NAME}, owner: ${DB_OWNER})"
   if [[ "${DRY_RUN}" == true ]]; then
      SUCCEEDED+=("${env}")
      continue
   fi

   # Create the database if it doesn't exist.
   # CREATE DATABASE cannot run inside a transaction, so we handle it here
   # at the shell level rather than inside te_core_schema.sql's DO block.
   # Only an empty answer from a query that SUCCEEDED means "absent". A failed query
   # used to be swallowed (2>/dev/null || true) and read as absent. stderr goes to a
   # file, not into the answer: psql can print a harmless warning there (Windows
   # prints a console code-page one) that would otherwise read as "exists".
   errfile="$(mktemp)"
   if DB_EXISTS=$(${PSQL} -d postgres -tA -c \
         "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" 2>"${errfile}"); then
      rm -f "${errfile}"
   else
      error "Could not check whether database ${DB_NAME} exists:"
      sed 's/^/      /' "${errfile}" >&2
      rm -f "${errfile}"
      FAILED+=("${env}")
      continue
   fi
   if [[ -z "${DB_EXISTS}" ]]; then
      log "Creating database: ${DB_NAME}"
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
      if ! accept_existing_database "${DB_NAME}"; then
         warn "Skipped ${env}: the existing database ${DB_NAME} was not accepted. Nothing was changed."
         SKIPPED+=("${env}")
         continue
      fi
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
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
   warn "Skipped   : ${SKIPPED[*]}  (existing database not accepted)"
fi
if [[ ${#FAILED[@]} -gt 0 ]]; then
   error "Failed    : ${FAILED[*]}"
   exit 1
fi
echo ""
