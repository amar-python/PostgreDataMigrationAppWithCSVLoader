#!/usr/bin/env bash
# install.sh: install from the offline bundle on an Ubuntu 24.04 VM with no internet (#60).
#
# From inside the extracted bundle directory:
#   sudo bash app/scripts/offline/install.sh [API_HOST]
# API_HOST is the address browsers use to reach the API (default: localhost).
# The first tenant and its admin come from TE_TENANT (default: main),
# TE_ADMIN_USER (default: admin) and TE_ADMIN_PASSWORD (default: generated and
# written to /root/te-initial-admin, readable by root only).
# Installs to /opt/te-migration, deploys database te_mgmt_prod (schema te_prod),
# writes /opt/te-migration/env, and installs systemd units te-api and te-frontend.
set -euo pipefail

BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
API_HOST="${1:-localhost}"
DEST=/opt/te-migration

echo "== 1/6 verify bundle checksums"
( cd "$BUNDLE" && sha256sum --quiet -c SHA256SUMS )

echo "== 2/6 install Ubuntu packages from the bundle only"
# Use the bundle as the only apt source; the VM's own sources are ignored.
APTDIR="$(mktemp -d)"; mkdir -p "$APTDIR/lists/partial"
echo "deb [trusted=yes] file:$BUNDLE/debs ./" > "$APTDIR/sources.list"
APT_OPTS=(-o Dir::Etc::SourceList="$APTDIR/sources.list" -o Dir::Etc::SourceParts=/dev/null
          -o Dir::State::Lists="$APTDIR/lists")
apt-get "${APT_OPTS[@]}" update -qq
apt-get "${APT_OPTS[@]}" install -y -qq --no-install-recommends \
  postgresql-16 postgresql-client-16 python3.12-venv nodejs >/dev/null
systemctl enable --now postgresql >/dev/null

echo "== 3/6 application files and Python environment"
id te-app >/dev/null 2>&1 || useradd --system --home "$DEST" --shell /usr/sbin/nologin te-app
rm -rf "$DEST"; mkdir -p "$DEST"
cp -r "$BUNDLE/app" "$DEST/app"; cp -r "$BUNDLE/frontend" "$DEST/frontend"
python3.12 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install -q --no-index --find-links "$BUNDLE/wheels" -r "$DEST/app/api/requirements.txt"

echo "== 4/6 database, T&E schema and application role"
DB_PASS="$(openssl rand -hex 24)"; API_KEY="$(openssl rand -hex 32)"
# env_prod.sql creates te_mgmt_prod, schema te_prod and login role te_prod_user.
sed "s/__INJECT_AT_DEPLOY__/$DB_PASS/" "$DEST/app/build/environments/env_prod.example.sql" \
  > "$DEST/app/build/environments/env_prod.sql"
( cd "$DEST/app" && sudo -u postgres env PGHOST=/var/run/postgresql bash build/deploy_all.sh prod >/dev/null )
rm "$DEST/app/build/environments/env_prod.sql"   # it holds the password
# M3d (#107): a separate runtime role for requests; it can only read and insert the
# audit and upload tables. te_prod_user stays the owner and runs migrations at startup.
APP_DB_PASS="$(openssl rand -hex 24)"
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d te_mgmt_prod -c "SET client_min_messages = warning" \
  -c "DO \$\$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'te_prod_runtime') THEN CREATE ROLE te_prod_runtime LOGIN; END IF; END\$\$" \
  -c "ALTER ROLE te_prod_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '$APP_DB_PASS'" \
  -c "GRANT te_prod_runtime TO te_prod_user" \
  -c "GRANT CONNECT ON DATABASE te_mgmt_prod TO te_prod_runtime" >/dev/null

echo "== 5/6 configuration and services"
cat > "$DEST/env" <<ENV
API_ENV=prod
API_KEY=$API_KEY
PGHOST=localhost
PGPORT=5432
PGUSER=te_prod_user
PGPASSWORD=$DB_PASS
PGDATABASE=te_mgmt_prod
APP_DB_USER=te_prod_runtime
APP_DB_PASSWORD=$APP_DB_PASS
TE_SCHEMA=te_prod
CORS_ORIGINS=http://$API_HOST:3000
PORT=3000
ENV
chmod 600 "$DEST/env"
# Browsers sign in per user (#96); the API key stays server-side for scripts.
grep -rl "__OFFLINE_API_BASE__" "$DEST/frontend" | xargs sed -i "s#__OFFLINE_API_BASE__#http://$API_HOST:8000#g"
chown -R te-app:te-app "$DEST"
cat > /etc/systemd/system/te-api.service <<UNIT
[Unit]
Description=T&E migration API
After=postgresql.service
[Service]
User=te-app
EnvironmentFile=$DEST/env
WorkingDirectory=$DEST/app
ExecStart=$DEST/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/te-frontend.service <<UNIT
[Unit]
Description=T&E migration frontend
After=te-api.service
[Service]
User=te-app
EnvironmentFile=$DEST/env
ExecStart=/usr/bin/node $DEST/frontend/server/index.mjs
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now te-api te-frontend >/dev/null

echo "== 6/6 first tenant admin and smoke test"
TE_TENANT="${TE_TENANT:-main}"; TE_ADMIN_USER="${TE_ADMIN_USER:-admin}"
if [ -z "${TE_ADMIN_PASSWORD:-}" ]; then
  TE_ADMIN_PASSWORD="$(openssl rand -base64 18)"
  ( umask 077; printf 'tenant=%s\nusername=%s\npassword=%s\n' "$TE_TENANT" "$TE_ADMIN_USER" "$TE_ADMIN_PASSWORD" \
      > /root/te-initial-admin )
  echo "First admin's password written to /root/te-initial-admin (root only). Change it after first sign-in."
fi
( cd "$DEST/app" && set -a && . "$DEST/env" && set +a && export TE_ADMIN_PASSWORD &&
  runuser -u te-app -- "$DEST/venv/bin/python" scripts/create_tenant_admin.py \
    --tenant "$TE_TENANT" --name "$TE_TENANT" --username "$TE_ADMIN_USER" )
SMOKE_TENANT="$TE_TENANT" SMOKE_USER="$TE_ADMIN_USER" SMOKE_PASSWORD="$TE_ADMIN_PASSWORD" \
  bash "$DEST/app/scripts/offline/smoke_test.sh" "$API_KEY"
