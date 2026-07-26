#!/usr/bin/env bash
# =============================================================================
# csv/loader_teradata.sh — Teradata Vantage CSV Loader
# =============================================================================
# Uses Teradata FastLoad for high-volume CSV loading.
# Falls back to BTEQ INSERT for small files (< 1000 rows).
# Auto-creates the target table if it does not exist.
# Called by csv_loader.sh — do not run directly.
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [td ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [td ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [td ✗]${NC} $*" >&2; }

# ── Load config ───────────────────────────────────────────────────────────────
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"
[[ -f "$CONFIG_LOCAL" ]] && source "$CONFIG_LOCAL" || source "$CONFIG_DEFAULT"

E="${TARGET_ENV^^}"
DB_NAME="$(eval echo "\$TD_DB_${E}")"
TD_USER="$(eval echo "\$TD_APP_USER_${E}")"
TD_PASS="$(eval echo "\$TD_APP_PASSWORD_${E}")"

command -v bteq &>/dev/null || { err "bteq not found. Install Teradata Tools and Utilities (TTU)."; exit 1; }
log "Target: ${TD_HOST}/${DB_NAME}.${TABLE_NAME}"

# ── Read CSV header ───────────────────────────────────────────────────────────
HEADER=$(head -1 "$VALID_CSV")
ROW_COUNT=$(( $(wc -l < "$VALID_CSV") - 1 ))

COLUMNS=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
print(', '.join(c.strip().lower().replace(' ','_') for c in cols))
" "$HEADER")

# ── Generate CREATE TABLE DDL ─────────────────────────────────────────────────
CREATE_DDL=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
col_defs = ',\n   '.join(
    c.strip().lower().replace(' ','_') + '  VARCHAR(2000) CHARACTER SET UNICODE'
    for c in cols
)
print(f'''CREATE TABLE {sys.argv[2]}.{sys.argv[3]} (
   _csv_row_id  INTEGER NOT NULL,
   {col_defs},
   _loaded_at   TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0)
)
PRIMARY INDEX (_csv_row_id);''')
" "$HEADER" "$DB_NAME" "$TABLE_NAME")

# ── Choose load method based on row count ─────────────────────────────────────
BTEQ_SCRIPT=$(mktemp /tmp/td_load_XXXXXX.btq)

if [[ $ROW_COUNT -lt 1000 ]]; then
   log "Using BTEQ INSERT (${ROW_COUNT} rows < 1000 threshold)..."

   # Generate INSERT statements from CSV
   INSERTS=$(python3 << PYEOF
import csv, sys

with open("$VALID_CSV", 'r', encoding='utf-8-sig', newline='') as f:
   reader  = csv.DictReader(f)
   cols    = [h.strip().lower().replace(' ','_') for h in reader.fieldnames]
   col_str = ', '.join(cols)

   for i, row in enumerate(reader, start=1):
      vals = []
      for v in row.values():
         if v.strip() == '':
            vals.append('NULL')
         else:
            escaped = v.replace("'", "''")
            vals.append(f"'{escaped}'")
      val_str = ', '.join(vals)
      print(f"INSERT INTO {DB_NAME}.{TABLE_NAME} ({col_str}, _csv_row_id) VALUES ({val_str}, {i});")
PYEOF
)

   cat > "$BTEQ_SCRIPT" << BTEQ
.LOGON ${TD_HOST}/${TD_USER},${TD_PASS};
DATABASE ${DB_NAME};
${CREATE_DDL};
${INSERTS}
.LOGOFF;
.QUIT 0;
BTEQ

else
   log "Using FastLoad (${ROW_COUNT} rows >= 1000 threshold)..."
   ABS_CSV="$(realpath "$VALID_CSV")"

   FASTLOAD_COLS=$(python3 -c "
import csv, sys
cols = next(csv.reader([sys.argv[1]]))
defs = ',\n   '.join(
    f'({c.strip().lower().replace(\" \",\"_\")} VARCHAR(2000))'
    for c in cols
)
print(defs)
" "$HEADER")

   cat > "$BTEQ_SCRIPT" << BTEQ
.LOGON ${TD_HOST}/${TD_USER},${TD_PASS};
DATABASE ${DB_NAME};
${CREATE_DDL};
.LOGOFF;
.QUIT 0;
BTEQ

   # Run BTEQ to create table
   bteq < "$BTEQ_SCRIPT" >> "$LOG_FILE" 2>&1

   # Create FastLoad script
   FL_SCRIPT=$(mktemp /tmp/td_fl_XXXXXX.fl)
   cat > "$FL_SCRIPT" << FASTLOAD
LOGON ${TD_HOST}/${TD_USER},${TD_PASS};
BEGIN LOADING ${DB_NAME}.${TABLE_NAME}
   ERRORFILES ${DB_NAME}.${TABLE_NAME}_ERR1, ${DB_NAME}.${TABLE_NAME}_ERR2
   CHECKPOINT 10000;
DEFINE
   ${FASTLOAD_COLS}
FILE=${ABS_CSV};
INSERT INTO ${DB_NAME}.${TABLE_NAME} (${COLUMNS})
VALUES (${COLUMNS});
END LOADING;
LOGOFF;
FASTLOAD

   fastload < "$FL_SCRIPT" >> "$LOG_FILE" 2>&1 \
      && log "FastLoad complete." \
      || { err "FastLoad failed. Check: ${LOG_FILE}"; rm -f "$FL_SCRIPT" "$BTEQ_SCRIPT"; exit 1; }

   rm -f "$FL_SCRIPT"
   rm -f "$BTEQ_SCRIPT"
   exit 0
fi

# ── Run BTEQ script ───────────────────────────────────────────────────────────
bteq < "$BTEQ_SCRIPT" >> "$LOG_FILE" 2>&1 \
   && log "BTEQ load complete." \
   || { err "BTEQ load failed. Check: ${LOG_FILE}"; rm -f "$BTEQ_SCRIPT"; exit 1; }

rm -f "$BTEQ_SCRIPT"

# ── Verify row count ──────────────────────────────────────────────────────────
VERIFY_SCRIPT=$(mktemp /tmp/td_verify_XXXXXX.btq)
cat > "$VERIFY_SCRIPT" << BTEQ
.LOGON ${TD_HOST}/${TD_USER},${TD_PASS};
SELECT COUNT(*) AS row_count FROM ${DB_NAME}.${TABLE_NAME};
.LOGOFF;
.QUIT 0;
BTEQ
bteq < "$VERIFY_SCRIPT" >> "$LOG_FILE" 2>&1
rm -f "$VERIFY_SCRIPT"
log "Rows loaded into ${DB_NAME}.${TABLE_NAME}: ${ROW_COUNT}"
