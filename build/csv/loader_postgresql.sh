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
_db_var="PG_DB_${E}";     DB_NAME="${!_db_var:-}"
_sc_var="PG_SCHEMA_${E}"; SCHEMA="${!_sc_var:-}"

# Defense-in-depth: don't rely solely on csv_loader.sh's upstream TABLE_NAME
# validation, or on PG_DB_${E}/PG_SCHEMA_${E} being well-formed config values
# -- validate all three here too (this script can be run directly despite the
# "called by csv_loader.sh only" convention above), and quote every one of
# them at the point of use below, not just inside the CREATE TABLE statement.
pg_quote_ident() { printf '"%s"' "${1//\"/\"\"}"; }
for _ident in "$TABLE_NAME" "$SCHEMA" "$DB_NAME"; do
   if [[ ! "$_ident" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      err "Invalid identifier '${_ident}' -- must match ^[A-Za-z_][A-Za-z0-9_]*\$"
      exit 1
   fi
done

[[ -n "${PG_SUPERUSER_PASSWORD:-}" ]] && export PGPASSWORD="${PG_SUPERUSER_PASSWORD}"

PSQL="psql -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER} -d ${DB_NAME}"

log "Target: ${DB_NAME}.${SCHEMA}.${TABLE_NAME} on ${PG_HOST}:${PG_PORT}"

# ── Read CSV header to get column names ───────────────────────────────────────
# CSV header text must never be trusted as raw SQL: each column name is
# sanitised to ^[a-z_][a-z0-9_]*$ (load aborts if that's not achievable) and
# every identifier below is always double-quoted, with embedded quotes
# escaped, before it goes into a SQL statement.
HEADER=$(head -1 "$VALID_CSV")
COLUMNS=$(python3 -c "
import csv, re, sys

def sanitize(name, idx):
    base = re.sub(r'[^a-z0-9_]+', '_', name.strip().lower()).strip('_')
    if not base:
        base = f'column_{idx}'
    if base[0].isdigit():
        base = f'col_{base}'
    return base

def quote_ident(name):
    return '\"' + name.replace('\"', '\"\"') + '\"'

cols = next(csv.reader([sys.argv[1]]))
sanitized = [sanitize(c, i + 1) for i, c in enumerate(cols)]
# Dedupe collisions after sanitisation (mirrors sanitize_columns() in
# api/services/csv_parse.py) — otherwise two headers that sanitise to the
# same name produce a CREATE TABLE with a duplicate column instead of a
# clean rejection.
assigned = set()
counter = {}
deduped = []
for base in sanitized:
    name = base
    while name in assigned:
        counter[base] = counter.get(base, 0) + 1
        name = f'{base}_{counter[base] + 1}'
    assigned.add(name)
    deduped.append(name)
sanitized = deduped
bad = [c for c in sanitized if not re.match(r'^[a-z_][a-z0-9_]*\$', c)]
if bad:
    sys.exit('unsafe column name(s) after sanitisation: ' + ', '.join(bad))
print(', '.join(quote_ident(c) for c in sanitized))
" "$HEADER") || { err "CSV header has column name(s) that can't be made into safe SQL identifiers."; exit 1; }

log "Columns: ${COLUMNS}"

# ── Auto-create table if it doesn't exist ────────────────────────────────────
# All columns default to TEXT — alter types after load if needed
CREATE_SQL=$(python3 -c "
import csv, re, sys

def sanitize(name, idx):
    base = re.sub(r'[^a-z0-9_]+', '_', name.strip().lower()).strip('_')
    if not base:
        base = f'column_{idx}'
    if base[0].isdigit():
        base = f'col_{base}'
    return base

def quote_ident(name):
    return '\"' + name.replace('\"', '\"\"') + '\"'

cols = next(csv.reader([sys.argv[1]]))
sanitized = [sanitize(c, i + 1) for i, c in enumerate(cols)]
# Dedupe collisions after sanitisation (mirrors sanitize_columns() in
# api/services/csv_parse.py) — otherwise two headers that sanitise to the
# same name produce a CREATE TABLE with a duplicate column instead of a
# clean rejection.
assigned = set()
counter = {}
deduped = []
for base in sanitized:
    name = base
    while name in assigned:
        counter[base] = counter.get(base, 0) + 1
        name = f'{base}_{counter[base] + 1}'
    assigned.add(name)
    deduped.append(name)
sanitized = deduped
bad = [c for c in sanitized if not re.match(r'^[a-z_][a-z0-9_]*\$', c)]
if bad:
    sys.exit('unsafe column name(s) after sanitisation: ' + ', '.join(bad))
col_defs = ',\n   '.join(f'{quote_ident(c)}   TEXT' for c in sanitized)
schema = quote_ident(sys.argv[2])
table  = quote_ident(sys.argv[3])
print(f'''CREATE TABLE IF NOT EXISTS {schema}.{table} (
   _csv_row_id  BIGSERIAL PRIMARY KEY,
   {col_defs},
   _loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);''')
" "$HEADER" "$SCHEMA" "$TABLE_NAME") || { err "Failed to build CREATE TABLE statement — check column names."; exit 1; }

log "Creating table if not exists..."
$PSQL -c "$CREATE_SQL" >> "$LOG_FILE" 2>&1 \
   && log "Table ready: ${SCHEMA}.${TABLE_NAME}" \
   || { err "Failed to create table. Check: ${LOG_FILE}"; exit 1; }

# ── Load data using COPY ──────────────────────────────────────────────────────
log "Loading CSV using COPY..."

Q_SCHEMA="$(pg_quote_ident "$SCHEMA")"
Q_TABLE="$(pg_quote_ident "$TABLE_NAME")"
COPY_SQL="\\COPY ${Q_SCHEMA}.${Q_TABLE} (${COLUMNS}) FROM STDIN WITH (FORMAT CSV, HEADER FALSE, NULL '', QUOTE '\"', DELIMITER ',')"

# Skip header row from valid CSV before piping to COPY
tail -n +2 "$VALID_CSV" | $PSQL -c "$COPY_SQL" >> "$LOG_FILE" 2>&1 \
   && log "COPY complete." \
   || { err "COPY failed. Check: ${LOG_FILE}"; exit 1; }

# ── Verify row count ──────────────────────────────────────────────────────────
DB_COUNT=$($PSQL -t -c "SELECT COUNT(*) FROM ${Q_SCHEMA}.${Q_TABLE};" | xargs)
log "Rows now in ${SCHEMA}.${TABLE_NAME}: ${DB_COUNT}"

unset PGPASSWORD
