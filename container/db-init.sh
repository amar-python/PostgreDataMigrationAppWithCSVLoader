#!/usr/bin/env bash
# First-start schema deploy for the te-db image (#128). Mirrors step 4 of
# scripts/offline/install.sh (the Ubuntu install): deploy the prod environment with the
# repo's own deployer, then add the runtime role that serves requests (M3d, #107).
#
# Runs as the postgres user against the temporary server the image starts for
# initialisation, which listens on the unix socket only. Passwords come from
# TE_DB_PASSWORD (the schema owner, te_prod_user) and TE_RUNTIME_PASSWORD (te_prod_runtime).
# psql reads them with \getenv, so they are never written to a file or put in a command line.
set -euo pipefail
: "${TE_DB_PASSWORD:?TE_DB_PASSWORD is required}"
: "${TE_RUNTIME_PASSWORD:?TE_RUNTIME_PASSWORD is required}"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp -r /opt/te/build "$WORK/build"
sed -E 's/^[[:space:]]*\\set[[:space:]]+app_password[[:space:]].*/\\getenv app_password TE_DB_PASSWORD/' \
  /opt/te/build/environments/env_prod.example.sql > "$WORK/build/environments/env_prod.sql"
grep -q 'getenv app_password' "$WORK/build/environments/env_prod.sql" \
  || { echo "te-db: the launcher template has no app_password line to replace" >&2; exit 1; }

export PGHOST=/var/run/postgresql PGUSER=postgres
bash "$WORK/build/deploy_all.sh" prod

psql -v ON_ERROR_STOP=1 -q -d te_mgmt_prod <<'SQL'
\getenv rt_pw TE_RUNTIME_PASSWORD
CREATE ROLE te_prod_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'rt_pw';
GRANT te_prod_runtime TO te_prod_user;
GRANT CONNECT ON DATABASE te_mgmt_prod TO te_prod_runtime;
SQL
echo "te-db: T&E schema deployed (database te_mgmt_prod, schema te_prod)"
