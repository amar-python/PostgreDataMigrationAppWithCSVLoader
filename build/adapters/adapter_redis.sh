#!/usr/bin/env bash
# =============================================================================
# adapters/adapter_redis.sh — Redis 7.x Deployment Adapter
#
# Redis is a key-value store — this adapter seeds lookup data and reference
# hashes using the key prefix pattern: {prefix}:{entity}:{id}
# Requires: redis-cli installed and on PATH
# =============================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓ REDIS]${NC} $*"; }
warn()  { echo -e "${YELLOW}[⚠ REDIS]${NC} $*"; }
error() { echo -e "${RED}[✗ REDIS]${NC} $*" >&2; }

ENVS=("$@")
SEED_FILE="${SCRIPT_DIR}/schema/redis/te_seed_data.sh"

command -v redis-cli &>/dev/null || { error "redis-cli not found on PATH."; exit 1; }

# Build redis-cli connection args
REDIS_ARGS="-h ${REDIS_HOST} -p ${REDIS_PORT}"
[[ -n "${REDIS_PASSWORD:-}" ]] && REDIS_ARGS+=" -a ${REDIS_PASSWORD}"
[[ "${REDIS_TLS:-false}" == "true" ]] && REDIS_ARGS+=" --tls"

SUCCEEDED=(); FAILED=()

for env in "${ENVS[@]}"; do
   E="${env^^}"
   db_index="$(eval echo "\$REDIS_DB_${E}")"
   key_prefix="$(eval echo "\$REDIS_KEY_PREFIX_${E}")"
   seed="$(eval echo "\$SEED_${E:-false}")"

   echo ""
   warn "Deploying Redis ${E}: db=${db_index}  prefix=${key_prefix}  seed=${seed}"

   REDIS_DB_ARGS="${REDIS_ARGS} -n ${db_index}"

   # Flush the target DB (idempotent reset)
   if redis-cli $REDIS_DB_ARGS FLUSHDB 2>&1; then
      log "${E} Redis DB ${db_index} flushed."

      # Store environment metadata key
      redis-cli $REDIS_DB_ARGS HSET "${key_prefix}:_meta" \
         env "${env}" \
         engine "redis" \
         prefix "${key_prefix}" \
         deployed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>&1

      # Load seed data if requested
      if [[ "$seed" == "true" && -f "$SEED_FILE" ]]; then
         KEY_PREFIX="$key_prefix" DB_INDEX="$db_index" \
         REDIS_ARGS="$REDIS_DB_ARGS" bash "$SEED_FILE" 2>&1 \
            && log "${E} seed data loaded." \
            || warn "${E} seed data failed — check ${SEED_FILE}"
      fi
      SUCCEEDED+=("$env")
   else
      error "${E} Redis flush FAILED — is Redis running on ${REDIS_HOST}:${REDIS_PORT}?"
      FAILED+=("$env")
   fi
done

[[ ${#SUCCEEDED[@]} -gt 0 ]] && echo -e "${GREEN}[✓]${NC} Succeeded: ${SUCCEEDED[*]}"
[[ ${#FAILED[@]}    -gt 0 ]] && { echo -e "${RED}[✗]${NC} Failed: ${FAILED[*]}"; exit 1; }
