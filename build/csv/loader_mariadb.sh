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
DB_NAME="$(eval echo "\$MYSQL_DB_${E}")"
MYSQL_OPTS="-h ${MYSQL_HOST} -P ${MYSQL_PORT} -u ${MYSQL_ROOT_USER}"
[[ -n "${MYSQL_ROOT_PASSWORD:-}" ]] && MYSQL_OPTS+=" -p${MYSQL_ROOT_PASSWORD}"

log "Target: ${DB_NAME}.${TABLE_NAME} on ${MYSQL_HOST}:${MYSQL_PORT}"

# ── Read CSV header ───────────────────────────────────────────────────────────
HEADER=$(head -1 "$VALID_CSV")
COLUMNS=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
print(', '.join('\`' + c.strip().lower().replace(' ','_') + '\`' for c in cols))
" "$HEADER")

CREATE_SQL=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
col_defs = ',\n  '.join(
    '\`' + c.strip().lower().replace(' ','_') + '\`  TEXT' for c in cols
)
db    = sys.argv[2]
table = sys.argv[3]
print(f'''CREATE TABLE IF NOT EXISTS \`{db}\`.\`{table}\` (
  \`_csv_row_id\`  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  {col_defs},
  \`_loaded_at\`   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;''')
" "$HEADER" "$DB_NAME" "$TABLE_NAME")

log "Creating table if not exists..."
echo "$CREATE_SQL" | mysql $MYSQL_OPTS >> "$LOG_FILE" 2>&1 \
   && log "Table ready: ${DB_NAME}.${TABLE_NAME}" \
   || { err "Failed to create table. Check: ${LOG_FILE}"; exit 1; }

# ── Load data using LOAD DATA LOCAL INFILE ────────────────────────────────────
ABS_CSV="$(realpath "$VALID_CSV")"
log "Loading CSV using LOAD DATA LOCAL INFILE..."

LOAD_SQL="
USE \`${DB_NAME}\`;
LOAD DATA LOCAL INFILE '${ABS_CSV}'
INTO TABLE \`${TABLE_NAME}\`
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
DB_COUNT=$(echo "SELECT COUNT(*) FROM \`${DB_NAME}\`.\`${TABLE_NAME}\`;" \
   | mysql $MYSQL_OPTS -s -N)
log "Rows now in ${DB_NAME}.${TABLE_NAME}: ${DB_COUNT}"
