#!/usr/bin/env bash
# =============================================================================
# csv/validator.sh — Shared CSV Validator
# =============================================================================
# Called by csv_loader.sh. Reads from environment variables:
#   CSV_FILE    — path to the source CSV file
#   TABLE_NAME  — derived table name
#   SKIP_FILE   — path to write rejected rows
#   VALID_CSV   — path to write accepted rows
#
# Validation rules applied to every row:
#   1. File must have at least one header row and one data row
#   2. Every row must have the same number of columns as the header
#   3. No row may be entirely empty
#   4. Detects and handles quoted fields correctly
#   5. Flags rows where all values are blank
#   6. Removes BOM characters if present (common in Windows CSV exports)
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [validator ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [validator ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [validator ✗]${NC} $*" >&2; }

# ── Verify required env vars are set ─────────────────────────────────────────
for var in CSV_FILE TABLE_NAME SKIP_FILE VALID_CSV; do
   [[ -z "${!var:-}" ]] && { err "Required env var \$$var is not set."; exit 1; }
done

# ── Remove BOM if present (UTF-8 BOM = EF BB BF) ─────────────────────────────
# Use LOG_DIR for temp files — works on Windows Git Bash, WSL2, and Linux
CLEAN_CSV="${VALID_CSV%.csv}_clean_$$.csv"
sed 's/^\xEF\xBB\xBF//' "$CSV_FILE" > "$CLEAN_CSV"

# ── Check file is not empty ───────────────────────────────────────────────────
LINE_COUNT=$(wc -l < "$CLEAN_CSV")
if [[ $LINE_COUNT -lt 2 ]]; then
   err "CSV file has fewer than 2 lines (needs at least a header + 1 data row)."
   rm -f "$CLEAN_CSV"
   exit 1
fi

# ── Extract and validate header row ──────────────────────────────────────────
HEADER=$(head -1 "$CLEAN_CSV")

# Count header columns (handles quoted commas)
HEADER_COLS=$(echo "$HEADER" | python3 -c "
import sys, csv
reader = csv.reader(sys.stdin)
row = next(reader)
print(len(row))
")

if [[ $HEADER_COLS -eq 0 ]]; then
   err "Header row is empty."
   rm -f "$CLEAN_CSV"
   exit 1
fi

log "Header: ${HEADER_COLS} columns detected — $(echo "$HEADER" | tr ',' ' | ')"

# ── Check for duplicate column names ─────────────────────────────────────────
DUPE_COLS=$(echo "$HEADER" | python3 -c "
import sys, csv
reader = csv.reader(sys.stdin)
cols = [c.strip().lower() for c in next(reader)]
dupes = [c for c in set(cols) if cols.count(c) > 1]
print(','.join(dupes))
")
if [[ -n "$DUPE_COLS" ]]; then
   warn "Duplicate column names detected: ${DUPE_COLS} — this may cause load issues."
fi

# ── Process rows — validate and split into valid/skipped ─────────────────────
VALID_COUNT=0
SKIP_COUNT=0

# Write header to both output files
echo "$HEADER" > "$VALID_CSV"
echo "${HEADER},_skip_reason" > "$SKIP_FILE"

# Process each data row using Python for correct CSV parsing
python3 << PYEOF
import csv
import sys
import os

clean_csv   = "$CLEAN_CSV"
valid_csv   = "$VALID_CSV"
skip_file   = "$SKIP_FILE"
header_cols = int("$HEADER_COLS")

valid_count = 0
skip_count  = 0

with open(clean_csv, 'r', encoding='utf-8-sig', newline='') as infile, \
     open(valid_csv, 'a', newline='', encoding='utf-8') as vf, \
     open(skip_file, 'a', newline='', encoding='utf-8') as sf:

   reader     = csv.reader(infile)
   writer_v   = csv.writer(vf)
   writer_s   = csv.writer(sf)

   next(reader)   # skip header — already written

   for line_num, row in enumerate(reader, start=2):

      # Rule 1: skip completely empty lines
      if not any(cell.strip() for cell in row):
         writer_s.writerow(row + ['empty row — all values blank'])
         skip_count += 1
         continue

      # Rule 2: column count must match header
      if len(row) != header_cols:
         reason = f'column count mismatch — expected {header_cols}, got {len(row)}'
         writer_s.writerow(row + [reason])
         skip_count += 1
         continue

      # Rule 3: row must have at least one non-blank value
      non_blank = sum(1 for cell in row if cell.strip())
      if non_blank == 0:
         writer_s.writerow(row + ['all values are blank'])
         skip_count += 1
         continue

      # Valid row
      writer_v.writerow(row)
      valid_count += 1

print(f"VALID:{valid_count}")
print(f"SKIPPED:{skip_count}")
PYEOF

# ── Parse Python output ───────────────────────────────────────────────────────
VALID_COUNT=$(grep "^VALID:" /dev/stdin 2>/dev/null || \
   python3 -c "
lines = open('$VALID_CSV').readlines()
print(max(0, len(lines)-1))
")

SKIP_COUNT=$(python3 -c "
lines = open('$SKIP_FILE').readlines()
print(max(0, len(lines)-1))
")

# ── Report ────────────────────────────────────────────────────────────────────
TOTAL=$(($(wc -l < "$CLEAN_CSV") - 1))
log "Validation complete — ${TOTAL} rows processed."

VALID_LINES=$(wc -l < "$VALID_CSV")
VALID_LINES=$((VALID_LINES - 1))
SKIP_LINES=$(wc -l < "$SKIP_FILE")
SKIP_LINES=$((SKIP_LINES - 1))

log "  Valid rows   : ${VALID_LINES}"
[[ $SKIP_LINES -gt 0 ]] && warn "  Skipped rows : ${SKIP_LINES} — written to: ${SKIP_FILE}"

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -f "$CLEAN_CSV"

# If no valid rows, exit with error
if [[ $VALID_LINES -eq 0 ]]; then
   err "No valid rows found. Nothing to load."
   exit 1
fi

exit 0
