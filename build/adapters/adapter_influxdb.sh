#!/usr/bin/env bash
# =============================================================================
# adapters/adapter_influxdb.sh — InfluxDB 2.x Deployment Adapter
#
# InfluxDB uses buckets (not databases) and measurements (not tables).
# This adapter creates buckets and loads seed data as line protocol.
# Requires: influx CLI v2.x installed and on PATH
# =============================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓ INFLUX]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠ INFLUX]${NC} $*"; }
error() { echo -e "${RED}[✗ INFLUX]${NC} $*" >&2; }

ENVS=("$@")
SEED_FILE="${SCRIPT_DIR}/schema/influxdb/te_seed_data.lp"

command -v influx &>/dev/null || { error "influx CLI not found. Install from: https://docs.influxdata.com/influxdb/v2/tools/influx-cli/"; exit 1; }

INFLUX_URL="${INFLUX_HOST}:${INFLUX_PORT}"
INFLUX_OPTS="--host ${INFLUX_URL} --token ${INFLUX_TOKEN} --org ${INFLUX_ORG}"

SUCCEEDED=(); FAILED=()

for env in "${ENVS[@]}"; do
   E="${env^^}"
   bucket="$(eval echo "\$INFLUX_BUCKET_${E}")"
   retention="$(eval echo "\$INFLUX_RETENTION_${E}")"
   seed="$(eval echo "\$SEED_${E:-false}")"

   echo ""
   warn "Deploying InfluxDB ${E}: bucket=${bucket}  retention=${retention}"

   # Create bucket (idempotent — delete old if exists, recreate)
   influx bucket delete $INFLUX_OPTS --name "${bucket}" 2>/dev/null || true

   if influx bucket create $INFLUX_OPTS \
      --name "${bucket}" \
      --retention "${retention}" 2>&1; then
      log "${E} bucket '${bucket}' created."

      # Write seed data (line protocol) if requested
      if [[ "$seed" == "true" && -f "$SEED_FILE" ]]; then
         if influx write $INFLUX_OPTS \
            --bucket "${bucket}" \
            --file "${SEED_FILE}" 2>&1; then
            log "${E} seed data written."
         else
            warn "${E} seed data write failed — check ${SEED_FILE}"
         fi
      fi
      SUCCEEDED+=("$env")
   else
      error "${E} bucket creation FAILED."
      FAILED+=("$env")
   fi
done

[[ ${#SUCCEEDED[@]} -gt 0 ]] && echo -e "${GREEN}[✓]${NC} Succeeded: ${SUCCEEDED[*]}"
[[ ${#FAILED[@]}    -gt 0 ]] && { echo -e "${RED}[✗]${NC} Failed: ${FAILED[*]}"; exit 1; }
