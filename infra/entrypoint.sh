#!/usr/bin/env bash
# entrypoint.sh - dispatches to the correct workflow inside the container.
# Usage (passed as the container CMD): deploy | load | evals | full | shell

set -euo pipefail

ACTION="${1:-deploy}"

echo "============================================================"
echo " T&E Migration container"
echo " action     : $ACTION"
echo " target env : ${TARGET_ENV}"
echo " pg host    : ${PGHOST}:${PGPORT}"
echo " pg user    : ${PGUSER}"
echo " pg db      : ${PGDATABASE}"
echo "============================================================"

# Wait for PostgreSQL to accept connections before doing anything else.
wait_for_pg() {
    local elapsed=0
    while ! pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -q; do
        if [ "$elapsed" -ge "$WAIT_FOR_DB_SECONDS" ]; then
            echo "ERROR: PostgreSQL did not become ready in ${WAIT_FOR_DB_SECONDS}s." >&2
            exit 1
        fi
        echo "waiting for pg..."
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo "PostgreSQL is ready."
}

run_deploy() {
    wait_for_pg
    echo "--- Deploying schema for env: ${TARGET_ENV} ---"
    cd /opt/migration
    bash build/deploy_all.sh "${TARGET_ENV}"
}

run_load() {
    wait_for_pg
    if [ ! -f /opt/migration/input_data/load_input_data.sql ]; then
        echo "--- SKIP load: no input_data/load_input_data.sql in image ---"
        echo "    (mount input_data as a volume or rebuild the image with it included)"
        return 0
    fi
    echo "--- Loading input data ---"
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
         -v ON_ERROR_STOP=1 \
         -f /opt/migration/input_data/load_input_data.sql
}

run_evals() {
    wait_for_pg
    echo "--- Running eval suite (tiers p,i,s) ---"
    cd /opt/migration
    python3 evals/runner.py --tiers p,i,s
}

run_full() {
    run_deploy
    run_load
    run_evals
}

case "$ACTION" in
    deploy) run_deploy ;;
    load)   run_load ;;
    evals)  run_evals ;;
    full)   run_full ;;
    shell)  exec /bin/bash ;;
    *)
        echo "Unknown action: $ACTION" >&2
        echo "Valid: deploy | load | evals | full | shell" >&2
        exit 2
        ;;
esac

echo "============================================================"
echo " Done: $ACTION"
echo "============================================================"
