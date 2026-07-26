#!/usr/bin/env bash
# =============================================================================
# csv_utilise.sh — Utilise CSV-loaded tables
# =============================================================================
# Companion to csv_loader.sh. Lists, describes, peeks at, exports, or drops
# tables that were created by the CSV loader. CSV-loaded tables are
# identified by the marker columns the loader always adds:
#   _csv_row_id  BIGSERIAL PRIMARY KEY
#   _loaded_at   TIMESTAMPTZ
#
# Usage:
#   ./csv_utilise.sh list                            [--env ENV] [--engine ENG]
#   ./csv_utilise.sh describe <table>                [--env ENV] [--engine ENG]
#   ./csv_utilise.sh peek <table> [--limit N]        [--env ENV] [--engine ENG]
#   ./csv_utilise.sh export <table> <out.csv>        [--env ENV] [--engine ENG]
#   ./csv_utilise.sh drop <table> --yes              [--env ENV] [--engine ENG]
#
#   ENG  defaults to value from config (or postgresql).
#   ENV  defaults to dev.
#
# Only the postgresql engine is implemented in this script. Other engines
# return a clear "not implemented" message and exit 2.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m';  BOLD=$'\033[1m';   NC=$'\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }
info()  { echo -e "${CYAN}[i]${NC} $*"; }

usage() {
   cat <<EOF

${BOLD}Usage:${NC}
  ./csv_utilise.sh <command> [args] [--env ENV] [--engine ENG]

${BOLD}Commands:${NC}
  list                        List CSV-loaded tables in the target schema
  describe <table>            Show columns and row count for a table
  peek <table> [--limit N]    Show first N rows (default 10)
  export <table> <out.csv>    Export the table back to CSV
  drop <table> --yes          Drop a CSV-loaded table (requires --yes)

${BOLD}Options:${NC}
  --env  <env>                dev | test | staging | prod   (default: dev)
  --engine <engine>           postgresql                    (default: from config)
  --limit <N>                 row limit for 'peek'          (default: 10)
  --yes                       confirmation flag for 'drop'
  --help, -h                  show this message

${BOLD}Examples:${NC}
  ./csv_utilise.sh list --env dev
  ./csv_utilise.sh describe customers
  ./csv_utilise.sh peek orders --limit 5
  ./csv_utilise.sh export inventory /tmp/inventory_dump.csv
  ./csv_utilise.sh drop orders --yes --env test

EOF
}

# ── Parse arguments ───────────────────────────────────────────────────────────
COMMAND=""
TABLE=""
OUT_FILE=""
TARGET_ENV="dev"
ENGINE_OVERRIDE=""
PEEK_LIMIT="10"
CONFIRM_DROP="false"

if [[ $# -eq 0 ]]; then usage; exit 1; fi

case "$1" in
   --help|-h) usage; exit 0 ;;
   list|describe|peek|export|drop) COMMAND="$1"; shift ;;
   *) error "Unknown command: $1"; usage; exit 1 ;;
esac

# Positional args for some commands
case "$COMMAND" in
   describe|peek|drop)
      if [[ $# -eq 0 || "${1:0:2}" == "--" ]]; then
         error "Command '${COMMAND}' requires a <table> argument."; usage; exit 1
      fi
      TABLE="$1"; shift
      ;;
   export)
      if [[ $# -lt 2 || "${1:0:2}" == "--" || "${2:0:2}" == "--" ]]; then
         error "Command 'export' requires <table> and <out.csv> arguments."; usage; exit 1
      fi
      TABLE="$1"; OUT_FILE="$2"; shift 2
      ;;
esac

while [[ $# -gt 0 ]]; do
   case "$1" in
      --env)     shift; TARGET_ENV="${1:-}" ;;
      --engine)  shift; ENGINE_OVERRIDE="${1:-}" ;;
      --limit)   shift; PEEK_LIMIT="${1:-10}" ;;
      --yes)     CONFIRM_DROP="true" ;;
      --help|-h) usage; exit 0 ;;
      *) error "Unknown argument: $1"; usage; exit 1 ;;
   esac
   shift
done

# ── Sanitise table identifier (before any side effects) ──────────────────────
if [[ -n "$TABLE" ]]; then
   if [[ ! "$TABLE" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
      error "Invalid table name: '${TABLE}'. Allowed: letters, digits, underscore; must not start with a digit."
      exit 1
   fi
fi

# ── Early engine check (avoids loading config for unsupported engines) ───────
if [[ -n "$ENGINE_OVERRIDE" && "$ENGINE_OVERRIDE" != "postgresql" ]]; then
   error "csv_utilise.sh: engine '${ENGINE_OVERRIDE}' is not implemented."
   error "Only 'postgresql' is supported. Run with --engine postgresql."
   exit 2
fi

# ── Load configuration ────────────────────────────────────────────────────────
if [[ -f "$CONFIG_LOCAL" ]]; then
   source "$CONFIG_LOCAL"
elif [[ -f "$CONFIG_DEFAULT" ]]; then
   source "$CONFIG_DEFAULT"
   warn "config.local.env not found — using defaults. Run ./setup.sh to configure."
else
   error "No config found. Run ./setup.sh first."
   exit 1
fi

DB_ENGINE="${ENGINE_OVERRIDE:-${DB_ENGINE:-postgresql}}"

if [[ "$DB_ENGINE" != "postgresql" ]]; then
   error "csv_utilise.sh: engine '${DB_ENGINE}' is not implemented."
   error "Only 'postgresql' is supported. Run with --engine postgresql."
   exit 2
fi

# ── Resolve PostgreSQL connection details ────────────────────────────────────
E="${TARGET_ENV^^}"
PG_HOST="${PGHOST:-${PG_HOST:-localhost}}"
PG_PORT="${PGPORT:-${PG_PORT:-5432}}"
PG_USER="${PGUSER:-${PG_SUPERUSER:-postgres}}"
DB_NAME="$(eval echo "\$PG_DB_${E}")"
SCHEMA="$(eval echo "\$PG_SCHEMA_${E}")"

if [[ -z "$DB_NAME" || -z "$SCHEMA" ]]; then
   error "Could not resolve database / schema for env '${TARGET_ENV}'."
   error "Check that PG_DB_${E} and PG_SCHEMA_${E} are set in config.local.env."
   exit 1
fi

[[ -n "${PG_SUPERUSER_PASSWORD:-}" ]] && export PGPASSWORD="${PG_SUPERUSER_PASSWORD}"

PSQL=(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1)

# ── Reachability probe (gives a friendly error when DB is down) ──────────────
if ! "${PSQL[@]}" -tA -c "SELECT 1" >/dev/null 2>&1; then
   error "Cannot reach PostgreSQL at ${PG_HOST}:${PG_PORT} as ${PG_USER}/${DB_NAME}."
   error "Check the database is running and config.local.env credentials are correct."
   exit 3
fi

# ── Helper: assert table is a CSV-loaded table ───────────────────────────────
assert_csv_table() {
   local tbl="$1"
   local cnt
   cnt=$("${PSQL[@]}" -tA -c "
      SELECT COUNT(*)
      FROM information_schema.columns
      WHERE table_schema = '${SCHEMA}'
        AND table_name   = '${tbl}'
        AND column_name IN ('_csv_row_id','_loaded_at');
   ")
   if [[ "$cnt" != "2" ]]; then
      error "Table '${SCHEMA}.${tbl}' is not a CSV-loaded table (missing marker columns)."
      error "Use the original loader to create it: ./csv_loader.sh <file>.csv"
      exit 1
   fi
}

# ── Commands ──────────────────────────────────────────────────────────────────
case "$COMMAND" in

   list)
      info "CSV-loaded tables in ${DB_NAME}.${SCHEMA}:"
      "${PSQL[@]}" -P pager=off -c "
         SELECT t.table_name AS table,
                pg_size_pretty(pg_total_relation_size(format('%I.%I', t.table_schema, t.table_name)::regclass)) AS size
         FROM information_schema.tables t
         WHERE t.table_schema = '${SCHEMA}'
           AND EXISTS (SELECT 1 FROM information_schema.columns c
                       WHERE c.table_schema = t.table_schema
                         AND c.table_name   = t.table_name
                         AND c.column_name  = '_csv_row_id')
           AND EXISTS (SELECT 1 FROM information_schema.columns c
                       WHERE c.table_schema = t.table_schema
                         AND c.table_name   = t.table_name
                         AND c.column_name  = '_loaded_at')
         ORDER BY t.table_name;
      "
      ;;

   describe)
      assert_csv_table "$TABLE"
      info "Columns of ${SCHEMA}.${TABLE}:"
      "${PSQL[@]}" -P pager=off -c "
         SELECT column_name, data_type, is_nullable
         FROM information_schema.columns
         WHERE table_schema = '${SCHEMA}' AND table_name = '${TABLE}'
         ORDER BY ordinal_position;
      "
      ROW_COUNT=$("${PSQL[@]}" -tA -c "SELECT COUNT(*) FROM \"${SCHEMA}\".\"${TABLE}\";")
      log "Row count: ${ROW_COUNT}"
      ;;

   peek)
      assert_csv_table "$TABLE"
      if [[ ! "$PEEK_LIMIT" =~ ^[0-9]+$ ]]; then
         error "--limit must be a positive integer (got: '${PEEK_LIMIT}')."
         exit 1
      fi
      info "First ${PEEK_LIMIT} row(s) of ${SCHEMA}.${TABLE}:"
      "${PSQL[@]}" -P pager=off -c "SELECT * FROM \"${SCHEMA}\".\"${TABLE}\" ORDER BY _csv_row_id LIMIT ${PEEK_LIMIT};"
      ;;

   export)
      assert_csv_table "$TABLE"
      # Validate output path is writable
      OUT_DIR="$(dirname "$OUT_FILE")"
      mkdir -p "$OUT_DIR"
      info "Exporting ${SCHEMA}.${TABLE} to ${OUT_FILE}..."
      "${PSQL[@]}" -c "\\COPY (SELECT * FROM \"${SCHEMA}\".\"${TABLE}\" ORDER BY _csv_row_id) TO '${OUT_FILE}' WITH (FORMAT CSV, HEADER TRUE)"
      log "Export complete: ${OUT_FILE}"
      ;;

   drop)
      assert_csv_table "$TABLE"
      if [[ "$CONFIRM_DROP" != "true" ]]; then
         error "Refusing to drop '${SCHEMA}.${TABLE}' without --yes."
         exit 1
      fi
      warn "Dropping ${SCHEMA}.${TABLE}..."
      "${PSQL[@]}" -c "DROP TABLE \"${SCHEMA}\".\"${TABLE}\";"
      log "Dropped ${SCHEMA}.${TABLE}"
      ;;
esac

unset PGPASSWORD
exit 0
