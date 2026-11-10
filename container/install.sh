#!/usr/bin/env bash
# install.sh: install the T&E platform from the container bundle, on macOS or Linux, with
# no internet access (#128, BR-38). Windows uses install.ps1 and does the same steps.
#
# Needs Docker or Podman already installed. From inside the extracted bundle directory:
#   bash install.sh [HOST]
# HOST is the name or address people use to reach this machine (default: localhost; with
# the default, only this machine can use the web app).
#
# Environment (all optional):
#   TE_RUNTIME         docker or podman (default: whichever is installed, docker first)
#   TE_TENANT          first tenant (default: main)
#   TE_ADMIN_USER      first tenant admin (default: admin)
#   TE_ADMIN_PASSWORD  its password, 12+ characters (default: generated, and written to
#                      ./te-initial-admin, readable only by you)
#
# Safe to re-run: secrets and data are kept, the first admin is created only once.
# Written for bash 3.2 (macOS's default).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
# The host people use to reach this machine. Given explicitly it wins; on a re-run with
# none given, the earlier choice in .env is kept (see step 3); otherwise localhost.
HOST_ARG="${TE_HOST:-${1:-}}"
TE_TENANT="${TE_TENANT:-main}"
TE_ADMIN_USER="${TE_ADMIN_USER:-admin}"

die() { echo "ERROR: $*" >&2; exit 1; }
step() { echo "== $*"; }

# ---- container runtime -------------------------------------------------------------------
RT="${TE_RUNTIME:-}"
if [ -z "$RT" ]; then
  if command -v docker >/dev/null 2>&1; then RT=docker
  elif command -v podman >/dev/null 2>&1; then RT=podman
  else die "neither docker nor podman is installed. Install one (Podman is free; Docker Desktop needs a paid subscription for larger organisations) and run this again."
  fi
fi
case "$RT" in
  docker) COMPOSE="docker compose" ;;
  podman) COMPOSE="podman compose" ;;
  *) die "TE_RUNTIME must be docker or podman (got '$RT')" ;;
esac
$RT info >/dev/null 2>&1 || die "$RT is installed but not running. Start it (Docker Desktop, or 'podman machine start') and run this again."
$COMPOSE version >/dev/null 2>&1 || die "'$COMPOSE' is not available. Docker needs the Compose plugin; Podman needs 'podman compose' (docker-compose or podman-compose)."

# ---- 1. verify the bundle ----------------------------------------------------------------
step "1/6 verify bundle checksums"
if command -v sha256sum >/dev/null 2>&1; then sha256sum --quiet -c SHA256SUMS
else shasum -a 256 -c SHA256SUMS >/dev/null; fi   # macOS ships shasum, not sha256sum
echo "checksums match"

# ---- 2. load the images for this CPU -----------------------------------------------------
step "2/6 load the container images (no download)"
case "$(uname -m)" in
  x86_64|amd64)  ARCH=amd64 ;;
  arm64|aarch64) ARCH=arm64 ;;
  *) die "unsupported CPU '$(uname -m)'; the bundle has amd64 and arm64 builds" ;;
esac
[ -f "images-$ARCH.tar" ] || die "this bundle has no images for $ARCH. It holds: $(ls images-*.tar 2>/dev/null | tr '\n' ' ')"
TE_VERSION="$(cat VERSION)"
load_out="$($RT load -i "images-$ARCH.tar" 2>&1)" || { echo "$load_out" >&2; die "$RT could not load images-$ARCH.tar"; }
echo "loaded te-api, te-frontend, te-db ($TE_VERSION, $ARCH)"

# ---- 3. secrets --------------------------------------------------------------------------
step "3/6 secrets and configuration"
rnd() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }   # 48 hex characters from the OS
FIRST_RUN=0
if [ -f .env ]; then
  # Keep the existing secrets: the database volume was initialised with them. The bundle's
  # version is the one just loaded, so it must win over the old value in the file.
  NEW_VERSION="$TE_VERSION"
  set -a; . ./.env; set +a
  TE_VERSION="$NEW_VERSION"; TE_HOST="${HOST_ARG:-${TE_HOST:-localhost}}"
  echo "keeping the secrets in .env"
else
  FIRST_RUN=1
  TE_HOST="${HOST_ARG:-localhost}"
  POSTGRES_PASSWORD="$(rnd)"; TE_DB_PASSWORD="$(rnd)"; TE_RUNTIME_PASSWORD="$(rnd)"; API_KEY="$(rnd)"
  echo "generated new secrets"
fi
( umask 077
  {
    echo "TE_VERSION=$TE_VERSION"
    echo "TE_HOST=$TE_HOST"
    echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
    echo "TE_DB_PASSWORD=$TE_DB_PASSWORD"
    echo "TE_RUNTIME_PASSWORD=$TE_RUNTIME_PASSWORD"
    echo "API_KEY=$API_KEY"
  } > .env.tmp )
mv .env.tmp .env; chmod 600 .env
export TE_VERSION TE_HOST

# ---- 4. start ----------------------------------------------------------------------------
step "4/6 start the database, API and web app"
$COMPOSE up -d || {
  hint=""
  [ "$RT" = podman ] && hint=" With Podman, 'podman compose' needs a compose provider: install podman-compose, or install docker-compose and enable Podman's API socket (systemctl --user enable --now podman.socket)."
  die "'$COMPOSE up' failed.$hint"
}
# The API container starts only once the database is healthy (first start deploys the
# schema, which takes a few seconds), then runs its own migrations; wait for it to answer.
api_up() { $COMPOSE exec -T api python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health', timeout=3)" >/dev/null 2>&1; }
i=0; until api_up; do
  i=$((i + 1)); [ "$i" -le 120 ] || die "the API did not become healthy in 4 minutes. Look at: $COMPOSE logs"
  sleep 2
done
echo "API is up"

# ---- 5. first tenant admin ---------------------------------------------------------------
step "5/6 first tenant admin"
if [ "$FIRST_RUN" = 1 ]; then
  if [ -z "${TE_ADMIN_PASSWORD:-}" ]; then
    TE_ADMIN_PASSWORD="$(od -An -N18 -tx1 /dev/urandom | tr -d ' \n')"
    ( umask 077; printf 'tenant=%s\nusername=%s\npassword=%s\n' "$TE_TENANT" "$TE_ADMIN_USER" "$TE_ADMIN_PASSWORD" > te-initial-admin )
    echo "The admin's password is in ./te-initial-admin (readable only by you). Change it after first sign-in."
  fi
  export TE_ADMIN_PASSWORD
  $COMPOSE exec -T -e TE_ADMIN_PASSWORD api python scripts/create_tenant_admin.py \
    --tenant "$TE_TENANT" --name "$TE_TENANT" --username "$TE_ADMIN_USER"
else
  echo "already installed; keeping the existing admin"
  if [ -z "${TE_ADMIN_PASSWORD:-}" ] && [ -f te-initial-admin ]; then
    TE_ADMIN_PASSWORD="$(sed -n 's/^password=//p' te-initial-admin)"
  fi
fi

# ---- 6. smoke test -----------------------------------------------------------------------
step "6/6 smoke test"
export API_KEY SMOKE_TENANT="$TE_TENANT" SMOKE_USER="$TE_ADMIN_USER" SMOKE_PASSWORD="${TE_ADMIN_PASSWORD:-}"
smoke_rc=0
$COMPOSE exec -T -e API_KEY -e SMOKE_TENANT -e SMOKE_USER -e SMOKE_PASSWORD api python smoke_test.py || smoke_rc=$?
if command -v curl >/dev/null 2>&1; then
  # The smoke test runs inside the containers; this checks the ports are published to the host.
  curl -sf "http://localhost:8000/api/health" >/dev/null && curl -sf -o /dev/null "http://localhost:8080/" \
    && echo "PASS  ports 8000 and 8080 answer on this machine" || { echo "FAIL  ports 8000 and 8080 do not answer on this machine"; smoke_rc=1; }
fi
[ "$smoke_rc" = 0 ] || die "the smoke test failed; the stack is running, so look at: $COMPOSE logs"

echo
echo "Installed. Open http://$TE_HOST:8080 and sign in as tenant '$TE_TENANT', user '$TE_ADMIN_USER'."
echo "Stop:  $COMPOSE down        Start again:  $COMPOSE up -d        (the data is kept in a volume)"
