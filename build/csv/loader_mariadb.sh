#!/usr/bin/env bash
# =============================================================================
# csv/loader_mariadb.sh — MariaDB / MySQL CSV Loader
# =============================================================================
# Uses LOAD DATA LOCAL INFILE for high-performance bulk loading.
# Auto-creates the target table if it does not exist.
# Called by csv_loader.sh — do not run directly.
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [mysql ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [mysql ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [mysql ✗]${NC} $*" >&2; }

# ── Load config ───────────────────────────────────────────────────────────────
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"
[[ -f "$CONFIG_LOCAL" ]] && source "$CONFIG_LOCAL" || source "$CONFIG_DEFAULT"

E="${TARGET_ENV^^}"
_db_var="MYSQL_DB_${E}"; DB_NAME="${!_db_var:-}"
MYSQL_OPTS="-h ${MYSQL_HOST} -P ${MYSQL_PORT} -u ${MYSQL_ROOT_USER}"
# Use MYSQL_PWD instead of -p<password> — a password on the command line is
# visible to any local user via `ps`/`/proc`; MYSQL_PWD is read directly by
# the mysql client and never appears in argv.
[[ -n "${MYSQL_ROOT_PASSWORD:-}" ]] && export MYSQL_PWD="${MYSQL_ROOT_PASSWORD}"

# Defense-in-depth: don't rely solely on csv_loader.sh's upstream TABLE_NAME
# validation, or on MYSQL_DB_${E} being a well-formed config value -- validate
# both here too (this script can be run directly despite the "called by
# csv_loader.sh only" convention above), and quote every one of them at the
# point of use below, not just inside the CREATE TABLE statement.
mysql_quote_ident() { printf '`%s`' "${1//\`/\`\`}"; }
for _ident in "$TABLE_NAME" "$DB_NAME"; do
   if [[ ! "$_ident" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      err "Invalid identifier '${_ident}' -- must match ^[A-Za-z_][A-Za-z0-9_]*\$"
      exit 1
   fi
done

log "Target: ${DB_NAME}.${TABLE_NAME} on ${MYSQL_HOST}:${MYSQL_PORT}"

# ── Read CSV header ───────────────────────────────────────────────────────────
# CSV header text must never be trusted as raw SQL: each column name is
# sanitised to ^[a-z_][a-z0-9_]*$ (load aborts if that's not achievable) and
# every identifier below is always backtick-quoted, with embedded backticks
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
    return '\`' + name.replace('\`', '\`\`') + '\`'

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
    return '\`' + name.replace('\`', '\`\`') + '\`'

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
col_defs = ',\n  '.join(f'{quote_ident(c)}  TEXT' for c in sanitized)
db    = quote_ident(sys.argv[2])
table = quote_ident(sys.argv[3])
print(f'''CREATE TABLE IF NOT EXISTS {db}.{table} (
  \`_csv_row_id\`  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  {col_defs},
  \`_loaded_at\`   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;''')
" "$HEADER" "$DB_NAME" "$TABLE_NAME") || { err "Failed to build CREATE TABLE statement — check column names."; exit 1; }

log "Creating table if not exists..."
echo "$CREATE_SQL" | mysql $MYSQL_OPTS >> "$LOG_FILE" 2>&1 \
   && log "Table ready: ${DB_NAME}.${TABLE_NAME}" \
   || { err "Failed to create table. Check: ${LOG_FILE}"; exit 1; }

# ── Load data using LOAD DATA LOCAL INFILE ────────────────────────────────────
ABS_CSV="$(realpath "$VALID_CSV")"
log "Loading CSV using LOAD DATA LOCAL INFILE..."

Q_DB="$(mysql_quote_ident "$DB_NAME")"
Q_TABLE="$(mysql_quote_ident "$TABLE_NAME")"
LOAD_SQL="
USE ${Q_DB};
LOAD DATA LOCAL INFILE '${ABS_CSV}'
INTO TABLE ${Q_TABLE}
FIELDS TERMINATED BY ','
OPTIONALLY ENCLOSED BY '\"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(${COLUMNS})
SET \`_loaded_at\` = NOW();
"

echo "$LOAD_SQL" | mysql $MYSQL_OPTS --local-infile=1 >> "$LOG_FILE" 2>&1 \
   && log "Load complete." \
   || { err "Load failed. Check: ${LOG_FILE}"; exit 1; }

# ── Verify row count ──────────────────────────────────────────────────────────
DB_COUNT=$(echo "SELECT COUNT(*) FROM ${Q_DB}.${Q_TABLE};" \
   | mysql $MYSQL_OPTS -s -N)
log "Rows now in ${DB_NAME}.${TABLE_NAME}: ${DB_COUNT}"

unset MYSQL_PWD
