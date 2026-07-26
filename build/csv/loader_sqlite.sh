#!/usr/bin/env bash
# =============================================================================
# csv/loader_sqlite.sh — SQLite 3 CSV Loader
# =============================================================================
# Uses Python's csv + sqlite3 modules for reliable CSV-to-SQLite loading.
# Auto-creates the target table if it does not exist.
# Called by csv_loader.sh — do not run directly.
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [sqlite ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [sqlite ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [sqlite ✗]${NC} $*" >&2; }

# ── Load config ───────────────────────────────────────────────────────────────
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"
[[ -f "$CONFIG_LOCAL" ]] && source "$CONFIG_LOCAL" || source "$CONFIG_DEFAULT"

E="${TARGET_ENV^^}"
DB_FILE="${SQLITE_DIR}/$(eval echo "\$SQLITE_DB_${E}")"

[[ ! -f "$DB_FILE" ]] && { warn "SQLite DB not found at ${DB_FILE} — it will be created."; }
mkdir -p "$(dirname "$DB_FILE")"

log "Target: ${DB_FILE} → table '${TABLE_NAME}'"

# ── Load CSV into SQLite via Python ───────────────────────────────────────────
python3 << PYEOF >> "$LOG_FILE" 2>&1
import csv
import sqlite3
import sys
from datetime import datetime

db_file    = "$DB_FILE"
table      = "$TABLE_NAME"
valid_csv  = "$VALID_CSV"

conn = sqlite3.connect(db_file)
cur  = conn.cursor()

# Enable WAL mode for better concurrency
cur.execute("PRAGMA journal_mode=WAL;")
cur.execute("PRAGMA foreign_keys=ON;")

with open(valid_csv, 'r', encoding='utf-8-sig', newline='') as f:
   reader  = csv.reader(f)
   headers = next(reader)

   # Sanitise column names
   cols = [h.strip().lower().replace(' ', '_').replace('-', '_') for h in headers]

   # Auto-create table if not exists (all TEXT columns)
   col_defs  = ', '.join(f'"{c}" TEXT' for c in cols)
   create_sql = f'''
      CREATE TABLE IF NOT EXISTS "{table}" (
         _csv_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
         {col_defs},
         _loaded_at  TEXT NOT NULL DEFAULT (datetime('now'))
      )
   '''
   cur.execute(create_sql)

   # Insert rows
   placeholders = ', '.join(['?'] * len(cols))
   col_list     = ', '.join(f'"{c}"' for c in cols)
   insert_sql   = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'

   loaded = 0
   for row in reader:
      cur.execute(insert_sql, row)
      loaded += 1

   conn.commit()
   print(f"Loaded {loaded} rows into '{table}' in {db_file}")

   # Verify
   cur.execute(f'SELECT COUNT(*) FROM "{table}"')
   total = cur.fetchone()[0]
   print(f"Total rows now in '{table}': {total}")

conn.close()
PYEOF

if [[ $? -eq 0 ]]; then
   log "Load complete."
   # Show row count
   ROW_COUNT=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_FILE')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM \"${TABLE_NAME}\"')
print(cur.fetchone()[0])
conn.close()
")
   log "Rows now in '${TABLE_NAME}': ${ROW_COUNT}"
else
   err "Load failed. Check: ${LOG_FILE}"
   exit 1
fi
