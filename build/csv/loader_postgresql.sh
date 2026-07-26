#!/usr/bin/env bash
# =============================================================================
# csv/loader_postgresql.sh — PostgreSQL CSV Loader
# =============================================================================
# Uses PostgreSQL COPY command for high-performance bulk loading.
# Creates the target table automatically if it does not exist.
# Called by csv_loader.sh — do not run directly.
#
# Environment variables required (set by csv_loader.sh):
#   VALID_CSV    — path to the validated CSV file
#   TABLE_NAME   — target table name
#   TARGET_ENV   — dev | test | staging | prod
#   LOG_FILE     — path to write load log
#   SCRIPT_DIR   — project root directory
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [pg ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [pg ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [pg ✗]${NC} $*" >&2; }

# ── Load config ───────────────────────────────────────────────────────────────
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"
[[ -f "$CONFIG_LOCAL" ]] && source "$CONFIG_LOCAL" || source "$CONFIG_DEFAULT"

E="${TARGET_ENV^^}"
PG_HOST="${PGHOST:-${PG_HOST:-localhost}}"
PG_PORT="${PGPORT:-${PG_PORT:-5432}}"
PG_USER="${PGUSER:-${PG_SUPERUSER:-postgres}}"
DB_NAME="$(eval echo "\$PG_DB_${E}")"
SCHEMA="$(eval echo "\$PG_SCHEMA_${E}")"

[[ -n "${PG_SUPERUSER_PASSWORD:-}" ]] && export PGPASSWORD="${PG_SUPERUSER_PASSWORD}"

PSQL="psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${DB_NAME}"

log "Target: ${DB_NAME}.${SCHEMA}.${TABLE_NAME} on ${PG_HOST}:${PG_PORT}"

# ── Read CSV header to get column names ───────────────────────────────────────
HEADER=$(head -1 "$VALID_CSV")
COLUMNS=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
print(', '.join(c.strip().lower().replace(' ','_') for c in cols))
" "$HEADER")

log "Columns: ${COLUMNS}"

# ── Auto-create table if it doesn't exist ────────────────────────────────────
# All columns default to TEXT — alter types after load if needed
CREATE_SQL=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
col_defs = ',\n   '.join(
    f'{c.strip().lower().replace(\" \",\"_\")}   TEXT' for c in cols
)
schema = sys.argv[2]
table  = sys.argv[3]
print(f'''CREATE TABLE IF NOT EXISTS \"{schema}\".\"{table}\" (
   _csv_row_id  BIGSERIAL PRIMARY KEY,
   {col_defs},
   _loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);''')
" "$HEADER" "$SCHEMA" "$TABLE_NAME")

log "Creating table if not exists..."
$PSQL -c "$CREATE_SQL" >> "$LOG_FILE" 2>&1 \
   && log "Table ready: ${SCHEMA}.${TABLE_NAME}" \
   || { err "Failed to create table. Check: ${LOG_FILE}"; exit 1; }

# ── Load data using COPY ──────────────────────────────────────────────────────
log "Loading CSV using COPY..."

COPY_SQL="\\COPY \"${SCHEMA}\".\"${TABLE_NAME}\" (${COLUMNS}) FROM STDIN WITH (FORMAT CSV, HEADER FALSE, NULL '', QUOTE '\"', DELIMITER ',')"

# Skip header row from valid CSV before piping to COPY
tail -n +2 "$VALID_CSV" | $PSQL -c "$COPY_SQL" >> "$LOG_FILE" 2>&1 \
   && log "COPY complete." \
   || { err "COPY failed. Check: ${LOG_FILE}"; exit 1; }

# ── Verify row count ──────────────────────────────────────────────────────────
DB_COUNT=$($PSQL -t -c "SELECT COUNT(*) FROM \"${SCHEMA}\".\"${TABLE_NAME}\";" | xargs)
log "Rows now in ${SCHEMA}.${TABLE_NAME}: ${DB_COUNT}"

unset PGPASSWORD
