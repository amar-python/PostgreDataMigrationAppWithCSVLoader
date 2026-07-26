#!/usr/bin/env bash
# =============================================================================
# setup.sh — Multi-Database Interactive Configuration Wizard
#
# Prompts the user to select a database engine and configure all settings,
# then writes config.local.env for use by deploy_all.sh and run_tests.sh.
#
# Usage:
#   ./setup.sh                    # full interactive wizard
#   ./setup.sh --defaults         # accept all defaults silently
#   ./setup.sh --engine sqlite    # pre-select a database engine
#   ./setup.sh --env dev          # configure one environment only
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_TEMPLATE="${SCRIPT_DIR}/config.env"
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m';  BOLD='\033[1m';      NC='\033[0m'

header()  { echo -e "\n${BOLD}${CYAN}$*${NC}"; printf '─%.0s' {1..60}; echo; }
prompt()  { echo -e "${YELLOW}  ▶ $*${NC}"; }
success() { echo -e "${GREEN}  ✓ $*${NC}"; }
info()    { echo -e "  $*"; }
warn()    { echo -e "${YELLOW}  ⚠ $*${NC}"; }

# ── Load defaults ─────────────────────────────────────────────────────────────
# Prefer config.env; fall back to config.env.example so a fresh checkout works
# without forcing the user to copy the file before their first run.
if [[ -f "$CONFIG_TEMPLATE" ]]; then
   source "$CONFIG_TEMPLATE"
elif [[ -f "${CONFIG_TEMPLATE}.example" ]]; then
   echo "INFO: config.env not found; using config.env.example as defaults."
   echo "      Run 'cp config.env.example config.env' to make a local copy."
   source "${CONFIG_TEMPLATE}.example"
else
   echo "ERROR: neither config.env nor config.env.example found in ${SCRIPT_DIR}"
   exit 1
fi

# ── Helper: ask with default (supports hidden input for passwords) ─────────────
ask() {
   local var="$1" question="$2" default="$3" secret="${4:-}"
   local input=""
   prompt "$question"
   if [[ -n "$secret" ]]; then
      info "(hidden — press Enter to keep default)"
      read -rsp "  > " input; echo
   else
      info "(default: $default)"
      read -rp  "  > " input
   fi
   eval "export ${var}=\"${input:-$default}\""
}

# ── Helper: yes/no prompt ─────────────────────────────────────────────────────
ask_bool() {
   local var="$1" question="$2" default="$3"
   prompt "$question (true/false)"
   info "(default: $default)"
   read -rp "  > " input
   eval "export ${var}=\"${input:-$default}\""
}

# ── Parse flags ───────────────────────────────────────────────────────────────
USE_DEFAULTS=false
PRESET_ENGINE=""
ENV_FILTER=""

while [[ $# -gt 0 ]]; do
   case "$1" in
      --defaults) USE_DEFAULTS=true ;;
      --engine)   shift; PRESET_ENGINE="${1:-}" ;;
      --env)      shift; ENV_FILTER="${1:-}" ;;
   esac
   shift
done

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════════════╗
  ║       PostgreDataMigrationApp — Database Setup Wizard        ║
  ║   Supports: PostgreSQL · MariaDB · SQLite · InfluxDB         ║
  ║             Redis · Teradata                                  ║
  ║   github.com/amar-python/PostgreDataMigrationApp             ║
  ╚══════════════════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Select Database Engine
# ══════════════════════════════════════════════════════════════════════════════
header "Step 1 — Select Database Engine"

SUPPORTED_ENGINES=(postgresql mariadb mysql sqlite influxdb redis teradata)

if [[ -n "$PRESET_ENGINE" ]]; then
   DB_ENGINE="$PRESET_ENGINE"
   success "Engine pre-selected: ${DB_ENGINE}"
elif [[ "$USE_DEFAULTS" == "true" ]]; then
   success "Using default engine: ${DB_ENGINE}"
else
   echo "  Available database engines:"
   echo ""
   echo "    1)  postgresql  — PostgreSQL 15  (relational, ACID, recommended)"
   echo "    2)  mariadb     — MariaDB 10.x   (relational, MySQL-compatible)"
   echo "    3)  mysql       — MySQL 8.x      (relational, MySQL protocol)"
   echo "    4)  sqlite      — SQLite 3       (embedded, file-based, no server)"
   echo "    5)  influxdb    — InfluxDB 2.x   (time-series, metrics & events)"
   echo "    6)  redis       — Redis 7.x      (in-memory key-value / cache)"
   echo "    7)  teradata    — Teradata Vantage (enterprise data warehouse)"
   echo ""
   prompt "Enter engine name or number (default: ${DB_ENGINE})"
   read -rp "  > " engine_input

   case "${engine_input:-}" in
      1|postgresql) DB_ENGINE=postgresql ;;
      2|mariadb)    DB_ENGINE=mariadb ;;
      3|mysql)      DB_ENGINE=mysql ;;
      4|sqlite)     DB_ENGINE=sqlite ;;
      5|influxdb)   DB_ENGINE=influxdb ;;
      6|redis)      DB_ENGINE=redis ;;
      7|teradata)   DB_ENGINE=teradata ;;
      "")           DB_ENGINE="${DB_ENGINE:-postgresql}" ;;
      *) warn "Unrecognised input — defaulting to postgresql"; DB_ENGINE=postgresql ;;
   esac
fi

success "Selected engine: ${DB_ENGINE}"

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Environments
# ══════════════════════════════════════════════════════════════════════════════
header "Step 2 — Environments"

if [[ -n "$ENV_FILTER" ]]; then
   ENVS=("$ENV_FILTER")
   info "Configuring single environment: ${ENV_FILTER}"
else
   ENVS=(dev test staging prod)
   info "Configuring all 4 environments: dev, test, staging, prod"
fi

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Engine-specific configuration
# ══════════════════════════════════════════════════════════════════════════════

configure_postgresql() {
   header "Step 3 — PostgreSQL 15 Configuration"
   if [[ "$USE_DEFAULTS" == "false" ]]; then
      ask PG_HOST             "Server hostname"                  "$PG_HOST"
      ask PG_PORT             "Server port"                      "$PG_PORT"
      ask PG_SUPERUSER        "Superuser name"                   "$PG_SUPERUSER"
      ask PG_SUPERUSER_PASSWORD "Superuser password"             "$PG_SUPERUSER_PASSWORD" secret

      for env in "${ENVS[@]}"; do
         header "  PostgreSQL — ${env^^} Environment"
         E="${env^^}"
         ask "PG_DB_${E}"           "Database name"    "$(eval echo "\$PG_DB_${E}")"
         ask "PG_SCHEMA_${E}"       "Schema name"      "$(eval echo "\$PG_SCHEMA_${E}")"
         ask "PG_APP_USER_${E}"     "App username"     "$(eval echo "\$PG_APP_USER_${E}")"
         ask "PG_APP_PASSWORD_${E}" "App password"     "$(eval echo "\$PG_APP_PASSWORD_${E}")" secret
         ask "PG_CONN_LIMIT_${E}"   "Connection limit" "$(eval echo "\$PG_CONN_LIMIT_${E}")"
         if [[ "$env" == "prod" || "$env" == "staging" ]]; then
            eval "export SEED_${E}=false"
            info "Seed data disabled for ${E}"
         else
            ask_bool "SEED_${E}" "Load seed data?" "$(eval echo "\$SEED_${E}")"
         fi
      done
   else
      success "Using PostgreSQL defaults from config.env"
   fi
}

configure_mariadb() {
   header "Step 3 — MariaDB / MySQL Configuration"
   if [[ "$USE_DEFAULTS" == "false" ]]; then
      ask MYSQL_HOST          "Server hostname"   "$MYSQL_HOST"
      ask MYSQL_PORT          "Server port"       "$MYSQL_PORT"
      ask MYSQL_ROOT_USER     "Root username"     "$MYSQL_ROOT_USER"
      ask MYSQL_ROOT_PASSWORD "Root password"     "$MYSQL_ROOT_PASSWORD" secret
      ask MYSQL_CHARSET       "Character set"     "$MYSQL_CHARSET"
      ask MYSQL_COLLATION     "Collation"         "$MYSQL_COLLATION"

      for env in "${ENVS[@]}"; do
         header "  MariaDB — ${env^^} Environment"
         E="${env^^}"
         ask "MYSQL_DB_${E}"           "Database name" "$(eval echo "\$MYSQL_DB_${E}")"
         ask "MYSQL_APP_USER_${E}"     "App username"  "$(eval echo "\$MYSQL_APP_USER_${E}")"
         ask "MYSQL_APP_PASSWORD_${E}" "App password"  "$(eval echo "\$MYSQL_APP_PASSWORD_${E}")" secret
         if [[ "$env" == "prod" || "$env" == "staging" ]]; then
            eval "export SEED_${E}=false"
            info "Seed data disabled for ${E}"
         else
            ask_bool "SEED_${E}" "Load seed data?" "$(eval echo "\$SEED_${E}")"
         fi
      done
   else
      success "Using MariaDB defaults from config.env"
   fi
}

configure_sqlite() {
   header "Step 3 — SQLite 3 Configuration"
   if [[ "$USE_DEFAULTS" == "false" ]]; then
      ask SQLITE_DIR "Directory for .db files" "$SQLITE_DIR"
      for env in "${ENVS[@]}"; do
         header "  SQLite — ${env^^} Environment"
         E="${env^^}"
         ask "SQLITE_DB_${E}" "Database filename" "$(eval echo "\$SQLITE_DB_${E}")"
         if [[ "$env" == "prod" || "$env" == "staging" ]]; then
            eval "export SEED_${E}=false"
            info "Seed data disabled for ${E}"
         else
            ask_bool "SEED_${E}" "Load seed data?" "$(eval echo "\$SEED_${E}")"
         fi
      done
   else
      success "Using SQLite defaults from config.env"
   fi
}

configure_influxdb() {
   header "Step 3 — InfluxDB 2.x Configuration"
   if [[ "$USE_DEFAULTS" == "false" ]]; then
      ask INFLUX_HOST  "InfluxDB URL (e.g. http://localhost)" "$INFLUX_HOST"
      ask INFLUX_PORT  "InfluxDB port"                        "$INFLUX_PORT"
      ask INFLUX_TOKEN "API token (hidden)"                   "$INFLUX_TOKEN" secret
      ask INFLUX_ORG   "Organisation name"                    "$INFLUX_ORG"
      for env in "${ENVS[@]}"; do
         header "  InfluxDB — ${env^^} Environment"
         E="${env^^}"
         ask "INFLUX_BUCKET_${E}"    "Bucket name"     "$(eval echo "\$INFLUX_BUCKET_${E}")"
         ask "INFLUX_RETENTION_${E}" "Retention period (e.g. 30d, 0 = infinite)" \
            "$(eval echo "\$INFLUX_RETENTION_${E}")"
      done
   else
      success "Using InfluxDB defaults from config.env"
   fi
}

configure_redis() {
   header "Step 3 — Redis 7.x Configuration"
   if [[ "$USE_DEFAULTS" == "false" ]]; then
      ask REDIS_HOST     "Redis hostname"          "$REDIS_HOST"
      ask REDIS_PORT     "Redis port"              "$REDIS_PORT"
      ask REDIS_PASSWORD "Redis password (hidden)" "$REDIS_PASSWORD" secret
      ask REDIS_TLS      "Enable TLS? (true/false)" "$REDIS_TLS"
      for env in "${ENVS[@]}"; do
         header "  Redis — ${env^^} Environment"
         E="${env^^}"
         ask "REDIS_DB_${E}"          "Database index (0-15)"  "$(eval echo "\$REDIS_DB_${E}")"
         ask "REDIS_KEY_PREFIX_${E}"  "Key namespace prefix"   "$(eval echo "\$REDIS_KEY_PREFIX_${E}")"
      done
   else
      success "Using Redis defaults from config.env"
   fi
}

configure_teradata() {
   header "Step 3 — Teradata Vantage Configuration"
   if [[ "$USE_DEFAULTS" == "false" ]]; then
      ask TD_HOST     "Teradata server hostname"  "$TD_HOST"
      ask TD_PORT     "Teradata server port"      "$TD_PORT"
      ask TD_USER     "DBA username"              "$TD_USER"
      ask TD_PASSWORD "DBA password (hidden)"     "$TD_PASSWORD" secret
      ask TD_PERM_SPACE_MB  "Perm space per DB (MB)"  "$TD_PERM_SPACE_MB"
      ask TD_SPOOL_SPACE_MB "Spool space per DB (MB)" "$TD_SPOOL_SPACE_MB"
      for env in "${ENVS[@]}"; do
         header "  Teradata — ${env^^} Environment"
         E="${env^^}"
         ask "TD_DB_${E}"           "Database name" "$(eval echo "\$TD_DB_${E}")"
         ask "TD_APP_USER_${E}"     "App username"  "$(eval echo "\$TD_APP_USER_${E}")"
         ask "TD_APP_PASSWORD_${E}" "App password"  "$(eval echo "\$TD_APP_PASSWORD_${E}")" secret
         if [[ "$env" == "prod" || "$env" == "staging" ]]; then
            eval "export SEED_${E}=false"
         else
            ask_bool "SEED_${E}" "Load seed data?" "$(eval echo "\$SEED_${E}")"
         fi
      done
   else
      success "Using Teradata defaults from config.env"
   fi
}

# ── Route to correct configurator ─────────────────────────────────────────────
case "$DB_ENGINE" in
   postgresql)          configure_postgresql ;;
   mariadb|mysql)       DB_ENGINE=mariadb; configure_mariadb ;;
   sqlite)              configure_sqlite ;;
   influxdb)            configure_influxdb ;;
   redis)               configure_redis ;;
   teradata)            configure_teradata ;;
esac

# ── Shared table names (relational engines only) ──────────────────────────────
case "$DB_ENGINE" in
   postgresql|mariadb|sqlite|teradata)
      header "Step 4 — Table Names"
      if [[ "$USE_DEFAULTS" == "false" ]]; then
         echo "  Press Enter to keep the default name for each table."
         echo ""
         ask TBL_ORGANISATIONS     "organisations"     "$TBL_ORGANISATIONS"
         ask TBL_PERSONNEL         "personnel"         "$TBL_PERSONNEL"
         ask TBL_TEST_PROGRAMS     "test_programs"     "$TBL_TEST_PROGRAMS"
         ask TBL_TEMP_DOCUMENTS    "temp_documents"    "$TBL_TEMP_DOCUMENTS"
         ask TBL_TEST_PHASES       "test_phases"       "$TBL_TEST_PHASES"
         ask TBL_REQUIREMENTS      "requirements"      "$TBL_REQUIREMENTS"
         ask TBL_TEST_CASES        "test_cases"        "$TBL_TEST_CASES"
         ask TBL_VCRM_ENTRIES      "vcrm_entries"      "$TBL_VCRM_ENTRIES"
         ask TBL_TEST_EVENTS       "test_events"       "$TBL_TEST_EVENTS"
         ask TBL_TEST_RESULTS      "test_results"      "$TBL_TEST_RESULTS"
         ask TBL_DEFECT_REPORTS    "defect_reports"    "$TBL_DEFECT_REPORTS"
         ask TBL_EVIDENCE_ARTIFACTS "evidence_artifacts" "$TBL_EVIDENCE_ARTIFACTS"
      else
         success "Using default table names"
      fi
      ;;
   influxdb)
      header "Step 4 — InfluxDB Measurements (table equivalents)"
      info "InfluxDB uses measurements instead of tables."
      info "Using default measurement names — edit config.local.env to rename."
      ;;
   redis)
      header "Step 4 — Redis Key Structure"
      info "Redis uses key prefixes instead of tables."
      info "Key prefixes are set per environment above."
      ;;
esac

# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: Write config.local.env
# ══════════════════════════════════════════════════════════════════════════════
header "Step 5 — Writing Configuration"

cat > "$CONFIG_LOCAL" << EOF
# =============================================================================
# config.local.env — Generated by setup.sh on $(date)
# Engine: ${DB_ENGINE}
# DO NOT COMMIT — this file is in .gitignore
# Re-run ./setup.sh to regenerate.
# =============================================================================

DB_ENGINE=${DB_ENGINE}
TARGET_ENV=${TARGET_ENV}

# ── PostgreSQL ────────────────────────────────────────────────────────────────
PG_HOST=${PG_HOST}
PG_PORT=${PG_PORT}
PG_SUPERUSER=${PG_SUPERUSER}
PG_SUPERUSER_PASSWORD=${PG_SUPERUSER_PASSWORD}
PG_DB_DEV=${PG_DB_DEV}
PG_DB_TEST=${PG_DB_TEST}
PG_DB_STAGING=${PG_DB_STAGING}
PG_DB_PROD=${PG_DB_PROD}
PG_SCHEMA_DEV=${PG_SCHEMA_DEV}
PG_SCHEMA_TEST=${PG_SCHEMA_TEST}
PG_SCHEMA_STAGING=${PG_SCHEMA_STAGING}
PG_SCHEMA_PROD=${PG_SCHEMA_PROD}
PG_APP_USER_DEV=${PG_APP_USER_DEV}
PG_APP_USER_TEST=${PG_APP_USER_TEST}
PG_APP_USER_STAGING=${PG_APP_USER_STAGING}
PG_APP_USER_PROD=${PG_APP_USER_PROD}
PG_APP_PASSWORD_DEV=${PG_APP_PASSWORD_DEV}
PG_APP_PASSWORD_TEST=${PG_APP_PASSWORD_TEST}
PG_APP_PASSWORD_STAGING=${PG_APP_PASSWORD_STAGING}
PG_APP_PASSWORD_PROD=${PG_APP_PASSWORD_PROD}
PG_CONN_LIMIT_DEV=${PG_CONN_LIMIT_DEV}
PG_CONN_LIMIT_TEST=${PG_CONN_LIMIT_TEST}
PG_CONN_LIMIT_STAGING=${PG_CONN_LIMIT_STAGING}
PG_CONN_LIMIT_PROD=${PG_CONN_LIMIT_PROD}

# ── MariaDB / MySQL ───────────────────────────────────────────────────────────
MYSQL_HOST=${MYSQL_HOST}
MYSQL_PORT=${MYSQL_PORT}
MYSQL_ROOT_USER=${MYSQL_ROOT_USER}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
MYSQL_CHARSET=${MYSQL_CHARSET}
MYSQL_COLLATION=${MYSQL_COLLATION}
MYSQL_DB_DEV=${MYSQL_DB_DEV}
MYSQL_DB_TEST=${MYSQL_DB_TEST}
MYSQL_DB_STAGING=${MYSQL_DB_STAGING}
MYSQL_DB_PROD=${MYSQL_DB_PROD}
MYSQL_APP_USER_DEV=${MYSQL_APP_USER_DEV}
MYSQL_APP_USER_TEST=${MYSQL_APP_USER_TEST}
MYSQL_APP_USER_STAGING=${MYSQL_APP_USER_STAGING}
MYSQL_APP_USER_PROD=${MYSQL_APP_USER_PROD}
MYSQL_APP_PASSWORD_DEV=${MYSQL_APP_PASSWORD_DEV}
MYSQL_APP_PASSWORD_TEST=${MYSQL_APP_PASSWORD_TEST}
MYSQL_APP_PASSWORD_STAGING=${MYSQL_APP_PASSWORD_STAGING}
MYSQL_APP_PASSWORD_PROD=${MYSQL_APP_PASSWORD_PROD}

# ── SQLite ────────────────────────────────────────────────────────────────────
SQLITE_DIR=${SQLITE_DIR}
SQLITE_DB_DEV=${SQLITE_DB_DEV}
SQLITE_DB_TEST=${SQLITE_DB_TEST}
SQLITE_DB_STAGING=${SQLITE_DB_STAGING}
SQLITE_DB_PROD=${SQLITE_DB_PROD}

# ── InfluxDB ──────────────────────────────────────────────────────────────────
INFLUX_HOST=${INFLUX_HOST}
INFLUX_PORT=${INFLUX_PORT}
INFLUX_TOKEN=${INFLUX_TOKEN}
INFLUX_ORG=${INFLUX_ORG}
INFLUX_BUCKET_DEV=${INFLUX_BUCKET_DEV}
INFLUX_BUCKET_TEST=${INFLUX_BUCKET_TEST}
INFLUX_BUCKET_STAGING=${INFLUX_BUCKET_STAGING}
INFLUX_BUCKET_PROD=${INFLUX_BUCKET_PROD}
INFLUX_RETENTION_DEV=${INFLUX_RETENTION_DEV}
INFLUX_RETENTION_TEST=${INFLUX_RETENTION_TEST}
INFLUX_RETENTION_STAGING=${INFLUX_RETENTION_STAGING}
INFLUX_RETENTION_PROD=${INFLUX_RETENTION_PROD}

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST=${REDIS_HOST}
REDIS_PORT=${REDIS_PORT}
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_TLS=${REDIS_TLS}
REDIS_DB_DEV=${REDIS_DB_DEV}
REDIS_DB_TEST=${REDIS_DB_TEST}
REDIS_DB_STAGING=${REDIS_DB_STAGING}
REDIS_DB_PROD=${REDIS_DB_PROD}
REDIS_KEY_PREFIX_DEV=${REDIS_KEY_PREFIX_DEV}
REDIS_KEY_PREFIX_TEST=${REDIS_KEY_PREFIX_TEST}
REDIS_KEY_PREFIX_STAGING=${REDIS_KEY_PREFIX_STAGING}
REDIS_KEY_PREFIX_PROD=${REDIS_KEY_PREFIX_PROD}

# ── Teradata ──────────────────────────────────────────────────────────────────
TD_HOST=${TD_HOST}
TD_PORT=${TD_PORT}
TD_USER=${TD_USER}
TD_PASSWORD=${TD_PASSWORD}
TD_DB_DEV=${TD_DB_DEV}
TD_DB_TEST=${TD_DB_TEST}
TD_DB_STAGING=${TD_DB_STAGING}
TD_DB_PROD=${TD_DB_PROD}
TD_APP_USER_DEV=${TD_APP_USER_DEV}
TD_APP_USER_TEST=${TD_APP_USER_TEST}
TD_APP_USER_STAGING=${TD_APP_USER_STAGING}
TD_APP_USER_PROD=${TD_APP_USER_PROD}
TD_APP_PASSWORD_DEV=${TD_APP_PASSWORD_DEV}
TD_APP_PASSWORD_TEST=${TD_APP_PASSWORD_TEST}
TD_APP_PASSWORD_STAGING=${TD_APP_PASSWORD_STAGING}
TD_APP_PASSWORD_PROD=${TD_APP_PASSWORD_PROD}
TD_PERM_SPACE_MB=${TD_PERM_SPACE_MB}
TD_SPOOL_SPACE_MB=${TD_SPOOL_SPACE_MB}

# ── Table Names ───────────────────────────────────────────────────────────────
TBL_ORGANISATIONS=${TBL_ORGANISATIONS}
TBL_PERSONNEL=${TBL_PERSONNEL}
TBL_TEST_PROGRAMS=${TBL_TEST_PROGRAMS}
TBL_TEMP_DOCUMENTS=${TBL_TEMP_DOCUMENTS}
TBL_TEST_PHASES=${TBL_TEST_PHASES}
TBL_REQUIREMENTS=${TBL_REQUIREMENTS}
TBL_TEST_CASES=${TBL_TEST_CASES}
TBL_VCRM_ENTRIES=${TBL_VCRM_ENTRIES}
TBL_TEST_EVENTS=${TBL_TEST_EVENTS}
TBL_TEST_RESULTS=${TBL_TEST_RESULTS}
TBL_DEFECT_REPORTS=${TBL_DEFECT_REPORTS}
TBL_EVIDENCE_ARTIFACTS=${TBL_EVIDENCE_ARTIFACTS}

# ── Seed Data ─────────────────────────────────────────────────────────────────
SEED_DEV=${SEED_DEV}
SEED_TEST=${SEED_TEST}
SEED_STAGING=${SEED_STAGING}
SEED_PROD=${SEED_PROD}
EOF

success "Configuration written to: config.local.env"

# ── Summary ────────────────────────────────────────────────────────────────────
header "Setup Complete"

echo -e "  Engine   : ${BOLD}${DB_ENGINE}${NC}"
echo ""
printf "  %-10s  %-30s  %s\n" "Env" "Database / Bucket / File" "Seed"
printf "  %-10s  %-30s  %s\n" "───" "──────────────────────────────" "─────"
for env in dev test staging prod; do
   E="${env^^}"
   case "$DB_ENGINE" in
      postgresql) db_val="$(eval echo "\$PG_DB_${E}")" ;;
      mariadb)    db_val="$(eval echo "\$MYSQL_DB_${E}")" ;;
      sqlite)     db_val="${SQLITE_DIR}/$(eval echo "\$SQLITE_DB_${E}")" ;;
      influxdb)   db_val="$(eval echo "\$INFLUX_BUCKET_${E}")" ;;
      redis)      db_val="db$(eval echo "\$REDIS_DB_${E}") / $(eval echo "\$REDIS_KEY_PREFIX_${E}")" ;;
      teradata)   db_val="$(eval echo "\$TD_DB_${E}")" ;;
   esac
   seed_val="$(eval echo "\$SEED_${E}")"
   printf "  %-10s  %-30s  %s\n" "$env" "$db_val" "$seed_val"
done

echo ""
echo -e "${BOLD}  Next steps:${NC}"
echo "  1. Deploy:    ./deploy_all.sh dev"
echo "  2. Deploy all: ./deploy_all.sh"
echo "  3. Test:      ./tests/run_tests.sh dev"
echo ""
echo -e "${GREEN}  ✓ Ready to deploy.${NC}"
echo ""
