#!/usr/bin/env bash
# entrypoint.sh - dispatches to the correct workflow inside the container.
# Usage (passed as the container CMD): deploy | load | evals | full | shell
#
# deploy needs APP_USER_PASSWORD: the password for the environment's application
# role (te_prod_user for prod). The image holds only the committed
# env_<env>.example.sql template, so the launcher is generated here at run time
# from that template and the password. It is never in the image (RV-S4, #174) and
# is deleted when the script exits (RV-S1, #172).

set -euo pipefail

ACTION="${1:-deploy}"
# Where the image keeps the runner. Overridable so the script can be tested
# outside a container; inside one it is always /opt/migration.
ROOT="${MIGRATION_ROOT:-/opt/migration}"

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

# \set <name> <value> from a launcher; same parsing as build/deploy_all.sh.
launcher_var() {
    tr -d '\r' < "$1" | sed -n "s/^\\\\set[[:space:]][[:space:]]*$2[[:space:]][[:space:]]*'\{0,1\}\([^' ]*\)'\{0,1\}.*/\1/p" | head -n1
}

GENERATED_LAUNCHER=""
cleanup() { [ -z "$GENERATED_LAUNCHER" ] || rm -f "$GENERATED_LAUNCHER"; }
trap cleanup EXIT

# Make sure build/environments/env_<env>.sql exists. An operator-supplied one
# (mounted in, or left by a developer) is used as is; otherwise build it from the
# template. A clean image has only the template, so without this a first deploy
# stops at "Environment file not found".
prepare_launcher() {
    case "$TARGET_ENV" in
        dev|test|staging|prod) ;;
        *) echo "ERROR: TARGET_ENV must be dev, test, staging or prod (got '${TARGET_ENV}')." >&2; exit 2 ;;
    esac
    local dir="$ROOT/build/environments"
    local template="$dir/env_${TARGET_ENV}.example.sql"
    local launcher="$dir/env_${TARGET_ENV}.sql"

    if [ -f "$launcher" ]; then
        echo "--- Using existing launcher ${launcher##*/} ---"
        return 0
    fi
    if [ ! -f "$template" ]; then
        echo "ERROR: neither ${launcher##*/} nor ${template##*/} is in $dir." >&2
        exit 1
    fi
    if [ -z "${APP_USER_PASSWORD:-}" ]; then
        echo "ERROR: APP_USER_PASSWORD is not set. It is the password for the ${TARGET_ENV} application role;" >&2
        echo "       without it the role would be created with the placeholder password in the template." >&2
        exit 1
    fi

    # Written 0600 and removed on exit by the trap above. Escaping is for psql's
    # single-quoted \set argument: '' for a quote, \\ for a backslash.
    GENERATED_LAUNCHER="$launcher"
    ( umask 077
      python3 - "$template" "$launcher" <<'EOF'
import os, sys
src, dst = sys.argv[1:3]
pw = os.environ["APP_USER_PASSWORD"].replace("\\", "\\\\").replace("'", "''")
text = open(src, encoding="utf-8-sig").read()
if "__INJECT_AT_DEPLOY__" not in text:
    sys.exit("template has no __INJECT_AT_DEPLOY__ placeholder: " + src)
open(dst, "w", encoding="utf-8").write(text.replace("__INJECT_AT_DEPLOY__", pw))
EOF
    )
    echo "--- Generated ${launcher##*/} from ${template##*/} ---"
}

run_deploy() {
    wait_for_pg
    prepare_launcher
    # The deployer creates and fills the database the launcher names, whatever the
    # job's PGDATABASE says. If the two differ the evals would then run against a
    # different database from the one just deployed, which is how Terraform and
    # the deployer drifted apart (#172). Fail before changing anything.
    local launcher_db
    launcher_db="$(launcher_var "$ROOT/build/environments/env_${TARGET_ENV}.sql" db_name)"
    if [ "$launcher_db" != "$PGDATABASE" ]; then
        echo "ERROR: PGDATABASE is '${PGDATABASE}' but env_${TARGET_ENV}.sql deploys to '${launcher_db}'." >&2
        echo "       Point the job at ${launcher_db}, or change db_name in the launcher template." >&2
        exit 1
    fi
    echo "--- Deploying schema for env: ${TARGET_ENV} ---"
    cd "$ROOT"
    bash build/deploy_all.sh "${TARGET_ENV}"
}

run_load() {
    wait_for_pg
    if [ ! -f "$ROOT/input_data/load_input_data.sql" ]; then
        echo "--- SKIP load: no input_data/load_input_data.sql in image ---"
        echo "    (mount input_data as a volume or rebuild the image with it included)"
        return 0
    fi
    echo "--- Loading input data ---"
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
         -v ON_ERROR_STOP=1 \
         -f "$ROOT/input_data/load_input_data.sql"
}

run_evals() {
    wait_for_pg
    echo "--- Running eval suite (tiers p,i,s) ---"
    cd "$ROOT"
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
