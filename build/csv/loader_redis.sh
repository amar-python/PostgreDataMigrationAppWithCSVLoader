#!/usr/bin/env bash
# =============================================================================
# csv/loader_redis.sh — Redis 7.x CSV Loader
# =============================================================================
# Stores each CSV row as a Redis Hash using the key pattern:
#   {prefix}:{table_name}:{row_number}
#
# Also maintains a Redis Set of all loaded keys:
#   {prefix}:{table_name}:_index
#
# Called by csv_loader.sh — do not run directly.
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}  [redis ✓]${NC} $*"; }
warn() { echo -e "${YELLOW}  [redis ⚠]${NC} $*"; }
err()  { echo -e "${RED}  [redis ✗]${NC} $*" >&2; }

# ── Load config ───────────────────────────────────────────────────────────────
CONFIG_LOCAL="${SCRIPT_DIR}/config.local.env"
CONFIG_DEFAULT="${SCRIPT_DIR}/config.env"
[[ -f "$CONFIG_LOCAL" ]] && source "$CONFIG_LOCAL" || source "$CONFIG_DEFAULT"

E="${TARGET_ENV^^}"
DB_INDEX="$(eval echo "\$REDIS_DB_${E}")"
KEY_PREFIX="$(eval echo "\$REDIS_KEY_PREFIX_${E}")"

REDIS_ARGS="-h ${REDIS_HOST} -p ${REDIS_PORT} -n ${DB_INDEX}"
[[ -n "${REDIS_PASSWORD:-}" ]] && REDIS_ARGS+=" -a ${REDIS_PASSWORD}"
[[ "${REDIS_TLS:-false}" == "true" ]] && REDIS_ARGS+=" --tls"

command -v redis-cli &>/dev/null || { err "redis-cli not found on PATH."; exit 1; }
log "Target: ${REDIS_HOST}:${REDIS_PORT} → db=${DB_INDEX} prefix='${KEY_PREFIX}:${TABLE_NAME}'"

# ── Load CSV rows as Redis Hashes using Python ────────────────────────────────
REDIS_CMDS=$(python3 << PYEOF
import csv
import sys

valid_csv  = "$VALID_CSV"
prefix     = "$KEY_PREFIX"
table      = "$TABLE_NAME"

with open(valid_csv, 'r', encoding='utf-8-sig', newline='') as f:
   reader  = csv.DictReader(f)
   headers = [h.strip().lower().replace(' ','_') for h in reader.fieldnames]

   cmds = []
   for i, row in enumerate(reader, start=1):
      key = f"{prefix}:{table}:{i}"
      # HSET key field1 val1 field2 val2 ...
      fields = []
      for col, val in zip(headers, row.values()):
         fields.extend([col, val if val.strip() else 'NULL'])
      fields.extend(['_loaded_at', '$(date -u +%Y-%m-%dT%H:%M:%SZ)'])
      fields_str = ' '.join(f'"{f}"' for f in fields)
      cmds.append(f"HSET {key} {fields_str}")
      # Add to index set
      cmds.append(f"SADD {prefix}:{table}:_index {key}")

print('\n'.join(cmds))
PYEOF
)

CMD_COUNT=$(echo "$REDIS_CMDS" | wc -l)
log "Executing ${CMD_COUNT} Redis commands..."

# Pipe all commands to redis-cli
echo "$REDIS_CMDS" | redis-cli $REDIS_ARGS --pipe >> "$LOG_FILE" 2>&1 \
   && log "Redis load complete." \
   || { err "Redis load failed. Check: ${LOG_FILE}"; exit 1; }

# ── Verify ────────────────────────────────────────────────────────────────────
KEY_COUNT=$(redis-cli $REDIS_ARGS SCARD "${KEY_PREFIX}:${TABLE_NAME}:_index")
log "Keys in '${KEY_PREFIX}:${TABLE_NAME}:_index': ${KEY_COUNT}"
log "Sample key: ${KEY_PREFIX}:${TABLE_NAME}:1"
redis-cli $REDIS_ARGS HGETALL "${KEY_PREFIX}:${TABLE_NAME}:1" | head -20 >> "$LOG_FILE" 2>&1
