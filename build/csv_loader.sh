#!/usr/bin/env bash
# =============================================================================
# csv_loader.sh — Multi-Database CSV Loader
# =============================================================================
# Accepts any CSV file, derives the target table from the filename,
# validates the data, loads valid rows, and reports skipped rows.
#
# Usage:
#   ./csv_loader.sh <path/to/file.csv>                  # use config.local.env engine
#   ./csv_loader.sh <path/to/file.csv> --engine postgresql
#   ./csv_loader.sh <path/to/file.csv> --engine mariadb --env dev
#   ./csv_loader.sh <path/to/file.csv> --engine sqlite  --env test
#
# Examples:
#   ./csv_loader.sh data/customers.csv
#   ./csv_loader.sh data/orders.csv --engine postgresql --env dev
#   ./csv_loader.sh data/products.csv --engine mariadb
#
# The table name is derived from the CSV filename:
#   customers.csv       → customers
#   order_items.csv     → order_items
#   2025_invoices.csv   → 2025_invoices
#
# Output files written to csv/logs/:
#   <filename>_loaded_<timestamp>.log    — rows successfully loaded
#   <filename>_skipped_<timestamp>.csv   — rows that failed validation
#   <filename>_report_<timestamp>.txt    — full summary report
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_DIR="${SCRIPT_DIR}/csv"
LOG_DIR="${CSV_DIR}/logs"
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m';  BOLD='\033[1m';   NC='\033[0m'

log()       { echo -e "${GREEN}[✓]${NC} $*"; }
warn()      { echo -e "${YELLOW}[⚠]${NC} $*"; }
error()     { echo -e "${RED}[✗]${NC} $*" >&2; }
info()      { echo -e "${CYAN}[i]${NC} $*"; }
separator() { echo "────────────────────────────────────────────────────────────"; }

# ── Usage ─────────────────────────────────────────────────────────────────────
usage() {
   echo ""
   echo -e "${BOLD}Usage:${NC}"
   echo "  ./csv_loader.sh <path/to/file.csv> [options]"
   echo ""
   echo -e "${BOLD}Options:${NC}"
   echo "  --engine  <engine>   postgresql | mariadb | sqlite | influxdb | redis | teradata"
   echo "  --env     <env>      dev | test | staging | prod  (default: dev)"
   echo "  --table   <name>     Override table name (default: derived from filename)"
   echo "  --dry-run            Validate only — do not load data"
   echo "  --help               Show this help message"
   echo ""
   echo -e "${BOLD}Examples:${NC}"
   echo "  ./csv_loader.sh data/customers.csv"
   echo "  ./csv_loader.sh data/orders.csv --engine postgresql --env test"
   echo "  ./csv_loader.sh data/products.csv --engine sqlite --dry-run"
   echo ""
   exit 0
}

# ── Parse arguments ───────────────────────────────────────────────────────────
CSV_FILE=""
ENGINE_OVERRIDE=""
TARGET_ENV="dev"
TABLE_OVERRIDE=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
   case "$1" in
      --engine)  shift; ENGINE_OVERRIDE="$1" ;;
      --env)     shift; TARGET_ENV="$1" ;;
      --table)   shift; TABLE_OVERRIDE="$1" ;;
      --dry-run) DRY_RUN=true ;;
      --help|-h) usage ;;
      *.csv|*.CSV) CSV_FILE="$1" ;;
      *) error "Unknown argument: $1"; usage ;;
   esac
   shift
done

[[ -z "$CSV_FILE" ]] && { error "No CSV file specified."; usage; }
[[ ! -f "$CSV_FILE" ]] && { error "File not found: $CSV_FILE"; exit 1; }

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

# Allow --engine flag to override config
DB_ENGINE="${ENGINE_OVERRIDE:-${DB_ENGINE:-postgresql}}"

# Validate engine
SUPPORTED_ENGINES=(postgresql mariadb sqlite influxdb redis teradata)
if [[ ! " ${SUPPORTED_ENGINES[*]} " =~ " ${DB_ENGINE} " ]]; then
   error "Unsupported engine: '${DB_ENGINE}'"
   error "Supported: ${SUPPORTED_ENGINES[*]}"
   exit 1
fi

# ── Derive table name from filename ───────────────────────────────────────────
BASENAME="$(basename "$CSV_FILE")"
TABLE_NAME="${TABLE_OVERRIDE:-${BASENAME%.csv}}"
TABLE_NAME="${TABLE_NAME%.CSV}"
# Sanitise: lowercase, replace spaces/hyphens with underscores
TABLE_NAME="$(echo "$TABLE_NAME" | tr '[:upper:]' '[:lower:]' | tr ' -' '__')"

# ── Setup log directory and files ─────────────────────────────────────────────
mkdir -p "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Create a test file to confirm LOG_DIR is writable
touch "${LOG_DIR}/.test" && rm -f "${LOG_DIR}/.test"
SAFE_NAME="${TABLE_NAME}"
LOG_FILE="${LOG_DIR}/${SAFE_NAME}_loaded_${TIMESTAMP}.log"
SKIP_FILE="${LOG_DIR}/${SAFE_NAME}_skipped_${TIMESTAMP}.csv"
REPORT_FILE="${LOG_DIR}/${SAFE_NAME}_report_${TIMESTAMP}.txt"

# ── Banner ────────────────────────────────────────────────────────────────────
separator
echo -e "${BOLD}  PostgreDataMigrationApp — CSV Loader${NC}"
echo "  File        : ${CSV_FILE}"
echo "  Table       : ${TABLE_NAME}"
echo "  Engine      : ${DB_ENGINE}"
echo "  Environment : ${TARGET_ENV}"
echo "  Dry Run     : ${DRY_RUN}"
separator

# ── Step 1: Validate CSV ──────────────────────────────────────────────────────
info "Step 1/3 — Validating CSV..."

VALIDATOR="${CSV_DIR}/validator.py"
[[ ! -f "$VALIDATOR" ]] && { error "Validator not found: $VALIDATOR"; exit 1; }

export CSV_FILE TABLE_NAME LOG_DIR SKIP_FILE TIMESTAMP
VALID_CSV="${LOG_DIR}/${SAFE_NAME}_valid_${TIMESTAMP}.csv"
export VALID_CSV

if ! python3 "${CSV_DIR}/validator.py"; then
   error "CSV validation failed. Check: ${SKIP_FILE}"
   exit 1
fi

TOTAL_ROWS=$(wc -l < "$CSV_FILE")
TOTAL_ROWS=$((TOTAL_ROWS - 1))   # subtract header row
VALID_ROWS=$(wc -l < "$VALID_CSV" 2>/dev/null || echo 0)
VALID_ROWS=$((VALID_ROWS > 0 ? VALID_ROWS - 1 : 0))
SKIPPED_ROWS=$((TOTAL_ROWS - VALID_ROWS))

log "Validation complete — ${VALID_ROWS} valid, ${SKIPPED_ROWS} skipped of ${TOTAL_ROWS} total rows."

if [[ "$DRY_RUN" == "true" ]]; then
   warn "DRY RUN — skipping data load. Validation results saved to: ${SKIP_FILE}"
   exit 0
fi

[[ $VALID_ROWS -eq 0 ]] && { error "No valid rows to load. Aborting."; exit 1; }

# ── Step 2: Load data via engine adapter ──────────────────────────────────────
info "Step 2/3 — Loading ${VALID_ROWS} valid rows into '${TABLE_NAME}' via ${DB_ENGINE}..."

LOADER="${CSV_DIR}/loader_${DB_ENGINE}.sh"
[[ ! -f "$LOADER" ]] && { error "Loader not found: $LOADER"; exit 1; }

export DB_ENGINE TARGET_ENV TABLE_NAME VALID_CSV LOG_FILE SCRIPT_DIR

START_TIME=$(date +%s)
LOADED_ROWS=0
LOAD_ERRORS=0

if bash "$LOADER"; then
   LOADED_ROWS=$VALID_ROWS
   log "Load complete — ${LOADED_ROWS} rows loaded into '${TABLE_NAME}'."
else
   LOAD_ERRORS=$VALID_ROWS
   error "Load encountered errors — check: ${LOG_FILE}"
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# ── Step 3: Write summary report ──────────────────────────────────────────────
info "Step 3/3 — Writing summary report..."

cat > "$REPORT_FILE" << REPORT
================================================================================
CSV LOAD REPORT
================================================================================
Generated    : $(date '+%Y-%m-%d %H:%M:%S')
Source File  : ${CSV_FILE}
Table        : ${TABLE_NAME}
Engine       : ${DB_ENGINE}
Environment  : ${TARGET_ENV}
Duration     : ${DURATION} seconds

RESULTS
────────────────────────────────────────────────────────────
Total rows in CSV   : ${TOTAL_ROWS}
Valid rows          : ${VALID_ROWS}
Skipped rows        : ${SKIPPED_ROWS}
Loaded rows         : ${LOADED_ROWS}
Load errors         : ${LOAD_ERRORS}

OUTPUT FILES
────────────────────────────────────────────────────────────
Load log            : ${LOG_FILE}
Skipped rows CSV    : ${SKIP_FILE}
This report         : ${REPORT_FILE}
$(if [[ $SKIPPED_ROWS -gt 0 ]]; then
   echo ""
   echo "SKIPPED ROW REASONS"
   echo "────────────────────────────────────────────────────────────"
   if [[ -f "$SKIP_FILE" ]]; then
      tail -n +2 "$SKIP_FILE" | awk -F',' '{print $NF}' | sort | uniq -c | sort -rn
   fi
fi)
================================================================================
REPORT

log "Report written to: ${REPORT_FILE}"

# ── Final summary ─────────────────────────────────────────────────────────────
separator
echo ""
echo -e "${BOLD}  Load Summary${NC}"
echo "  Total rows    : ${TOTAL_ROWS}"
echo -e "  Loaded        : ${GREEN}${LOADED_ROWS}${NC}"
[[ $SKIPPED_ROWS -gt 0 ]] && echo -e "  Skipped       : ${YELLOW}${SKIPPED_ROWS}${NC} — see: ${SKIP_FILE}"
[[ $LOAD_ERRORS -gt 0  ]] && echo -e "  Errors        : ${RED}${LOAD_ERRORS}${NC} — see: ${LOG_FILE}"
echo "  Duration      : ${DURATION}s"
echo "  Report        : ${REPORT_FILE}"
echo ""

# Clean up temporary valid CSV
rm -f "$VALID_CSV"

[[ $LOAD_ERRORS -gt 0 ]] && exit 1
exit 0
