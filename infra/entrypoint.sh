#!/usr/bin/env bash
# entrypoint.sh - dispatches to the correct workflow inside the container.
# Usage (passed as the container CMD): deploy | load | evals | full | render | shell

set -euo pipefail

ACTION="${1:-deploy}"
MIGRATION_HOME="${MIGRATION_HOME:-/opt/migration}"

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

# The image carries only the committed launcher templates
# (build/environments/env_<env>.example.sql); the concrete env_<env>.sql holds
# credentials, is gitignored, and must never be baked into an image (#174). So
# make it here, at run time, from this container's own settings (#172):
#   db_name     <- PGDATABASE   the database the infrastructure created
#   db_owner    <- PGUSER       the login that runs the deployment
#   app_password <- APP_DB_PASSWORD, read by psql (\getenv) when the deployment
#                  runs, so the secret is never written to disk.
# An existing launcher (mounted in, or from a developer's checkout) is left alone.
ensure_launcher() {
    local dir="${MIGRATION_HOME}/build/environments"
    local launcher="${dir}/env_${TARGET_ENV}.sql"
    local template="${dir}/env_${TARGET_ENV}.example.sql"

    if [ -f "$launcher" ]; then
        echo "--- Using existing launcher: ${launcher} ---"
        return 0
    fi
    if [ ! -f "$template" ]; then
        echo "ERROR: no launcher for TARGET_ENV='${TARGET_ENV}': neither ${launcher}" >&2
        echo "       nor its template ${template} exists." >&2
        exit 1
    fi
    if [ -z "${APP_DB_PASSWORD:-}" ]; then
        echo "ERROR: APP_DB_PASSWORD is not set. It is the password for the application" >&2
        echo "       role this deployment creates; supply it as a secret environment variable." >&2
        exit 1
    fi
    local ident
    for ident in "$PGDATABASE" "$PGUSER"; do
        if [[ ! "$ident" =~ ^[a-z_][a-z0-9_]*$ ]]; then
            echo "ERROR: '${ident}' (PGDATABASE / PGUSER) must be lower-case letters, digits and underscores." >&2
            exit 1
        fi
    done

    sed -E \
        -e "s/^([[:space:]]*\\\\set[[:space:]]+db_name[[:space:]]+).*/\\1${PGDATABASE}/" \
        -e "s/^([[:space:]]*\\\\set[[:space:]]+db_owner[[:space:]]+).*/\\1${PGUSER}/" \
        -e "s/^[[:space:]]*\\\\set[[:space:]]+app_password[[:space:]].*/\\\\getenv app_password APP_DB_PASSWORD/" \
        "$template" > "$launcher"
    echo "--- Generated ${launcher} from its template (db ${PGDATABASE}, owner ${PGUSER}) ---"
}

run_deploy() {
    wait_for_pg
    ensure_launcher
    echo "--- Deploying schema for env: ${TARGET_ENV} ---"
    cd "$MIGRATION_HOME"
    bash build/deploy_all.sh "${TARGET_ENV}"
}

run_render() {
    ensure_launcher
    cat "${MIGRATION_HOME}/build/environments/env_${TARGET_ENV}.sql"
}

run_load() {
    wait_for_pg
    if [ ! -f "${MIGRATION_HOME}/input_data/load_input_data.sql" ]; then
        echo "--- SKIP load: no input_data/load_input_data.sql in image ---"
        echo "    (mount input_data as a volume or rebuild the image with it included)"
        return 0
    fi
    echo "--- Loading input data ---"
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
         -v ON_ERROR_STOP=1 \
         -f "${MIGRATION_HOME}/input_data/load_input_data.sql"
}

run_evals() {
    wait_for_pg
    echo "--- Running eval suite (tiers p,i,s) ---"
    cd "$MIGRATION_HOME"
    python3 evals/runner.py --tiers p,i,s
}

run_full() {
    run_deploy
    run_load
    run_evals
}

case "$ACTION" in
    deploy) run_deploy ;;
    render) run_render ;;
    load)   run_load ;;
    evals)  run_evals ;;
    full)   run_full ;;
    shell)  exec /bin/bash ;;
    *)
        echo "Unknown action: $ACTION" >&2
        echo "Valid: deploy | render | load | evals | full | shell" >&2
        exit 2
        ;;
esac

echo "============================================================"
echo " Done: $ACTION"
echo "============================================================"
