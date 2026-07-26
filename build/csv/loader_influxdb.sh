#!/usr/bin/env bash
# =============================================================================
# csv/loader_influxdb.sh — InfluxDB 2.x CSV Loader
# =============================================================================
# Converts CSV rows to InfluxDB line protocol and writes to the target bucket.
# The table name becomes the measurement name.
# The first column is used as the timestamp if it is named 'time' or 'timestamp'.
# All other columns are written as fields.
# Called by csv_loader.sh — do not run directly.
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [influx ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [influx ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [influx ✗]${NC} $*" >&2; }

# ── Load config ───────────────────────────────────────────────────────────────
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"
[[ -f "$CONFIG_LOCAL" ]] && source "$CONFIG_LOCAL" || source "$CONFIG_DEFAULT"

E="${TARGET_ENV^^}"
BUCKET="$(eval echo "\$INFLUX_BUCKET_${E}")"
INFLUX_URL="${INFLUX_HOST}:${INFLUX_PORT}"
MEASUREMENT="${TABLE_NAME}"

command -v influx &>/dev/null || { err "influx CLI not found on PATH."; exit 1; }
log "Target: ${INFLUX_URL} → bucket '${BUCKET}' → measurement '${MEASUREMENT}'"

# ── Convert CSV to line protocol and write ────────────────────────────────────
LP_FILE=$(mktemp /tmp/influx_lp_XXXXXX.lp)

python3 << PYEOF > "$LP_FILE"
import csv
import sys
import time

valid_csv   = "$VALID_CSV"
measurement = "$MEASUREMENT"

with open(valid_csv, 'r', encoding='utf-8-sig', newline='') as f:
   reader  = csv.DictReader(f)
   headers = reader.fieldnames

   # Detect timestamp column
   ts_cols = [h for h in headers if h.strip().lower() in ('time','timestamp','ts')]
   ts_col  = ts_cols[0] if ts_cols else None

   base_ts = int(time.time_ns())

   for i, row in enumerate(reader):
      fields = []
      ts     = base_ts + i  # nanosecond offset to ensure unique timestamps

      for col, val in row.items():
         col_clean = col.strip().lower().replace(' ', '_')
         if col == ts_col:
            try:
               ts = int(float(val)) * 1_000_000_000  # assume epoch seconds
            except ValueError:
               pass
            continue
         if val.strip() == '':
            continue
         # Try numeric, else string
         try:
            num = float(val)
            if num == int(num):
               fields.append(f'{col_clean}={int(num)}i')
            else:
               fields.append(f'{col_clean}={num}')
         except ValueError:
            escaped = val.replace('"', '\\"')
            fields.append(f'{col_clean}="{escaped}"')

      if fields:
         print(f'{measurement} {",".join(fields)} {ts}')
PYEOF

LP_LINES=$(wc -l < "$LP_FILE")
log "Generated ${LP_LINES} line protocol entries."

influx write \
   --host "${INFLUX_URL}" \
   --token "${INFLUX_TOKEN}" \
   --org "${INFLUX_ORG}" \
   --bucket "${BUCKET}" \
   --file "$LP_FILE" >> "$LOG_FILE" 2>&1 \
   && log "Write to InfluxDB complete." \
   || { err "InfluxDB write failed. Check: ${LOG_FILE}"; rm -f "$LP_FILE"; exit 1; }

rm -f "$LP_FILE"
log "Measurement '${MEASUREMENT}' written to bucket '${BUCKET}'."
