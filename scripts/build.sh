#!/usr/bin/env bash
# build.sh - build the deployable migration runner image (Linux/Mac/Cloud Shell).
#
# Usage:
#   ./scripts/build.sh                     # local docker build, tag=dev
#   ./scripts/build.sh -t dev-1234         # custom tag
#   ./scripts/build.sh --acr-build         # build in Azure (no local Docker needed)
#   ./scripts/build.sh --push              # also push to ACR
#   ./scripts/build.sh --acr-build --push -t $(git rev-parse --short HEAD)
#
# Exit codes:
#   0 = success
#   1 = build failed
#   2 = prereq missing

set -uo pipefail

TAG="dev"
USE_ACR_BUILD=0
PUSH=0
ACR_NAME=""
RG=""

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--tag)         TAG="$2"; shift 2 ;;
        --acr-build)      USE_ACR_BUILD=1; shift ;;
        --push)           PUSH=1; shift ;;
        --acr)            ACR_NAME="$2"; shift 2 ;;
        -g|--rg)          RG="$2"; shift 2 ;;
        -h|--help)        sed -n '1,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)                echo "unknown arg: $1" >&2; exit 64 ;;
    esac
done

cd "$(dirname "$0")/.."

if [ -t 1 ]; then R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; C=$'\033[36m'; X=$'\033[0m'
else R=''; G=''; Y=''; C=''; X=''; fi

echo
echo "${C}===========================================================${X}"
echo "${C} PostgreDataMigrationApp - build${X}"
echo "${C} tag         : $TAG${X}"
echo "${C} mode        : $([ "$USE_ACR_BUILD" -eq 1 ] && echo 'az acr build (cloud)' || echo 'docker build (local)')${X}"
echo "${C} push to ACR : $([ "$PUSH" -eq 1 ] && echo 'yes' || echo 'no')${X}"
echo "${C}===========================================================${X}"
echo

fail() { echo "${R}FAIL: $1${X}" >&2; exit "${2:-1}"; }

# --- Validate prereqs ---
if [ "$USE_ACR_BUILD" -eq 1 ]; then
    command -v az >/dev/null 2>&1 || fail "az CLI not on PATH" 2
    if [ -z "$ACR_NAME" ] && [ -d infra/terraform ]; then
        ACR_NAME=$(cd infra/terraform && terraform output -raw acr_name 2>/dev/null || true)
        [ -z "$RG" ] && RG=$(cd infra/terraform && terraform output -raw resource_group_name 2>/dev/null || true)
    fi
    [ -n "$ACR_NAME" ] || fail "--acr-build needs --acr <name> (or terraform output)" 2
else
    command -v docker >/dev/null 2>&1 || fail "docker not on PATH (use --acr-build instead)" 2
fi

for f in infra/Dockerfile infra/entrypoint.sh build tests evals; do
    [ -e "$f" ] || fail "missing $f - run from project root" 2
done

# --- Build ---
if [ "$USE_ACR_BUILD" -eq 1 ]; then
    echo "${Y}[acr build] Building $TAG inside Azure...${X}"
    az acr build --registry "$ACR_NAME" --image "te-migration:$TAG" --file infra/Dockerfile . \
        || fail "az acr build failed"
    FULL_IMAGE="${ACR_NAME}.azurecr.io/te-migration:${TAG}"
    echo "${G}[acr build] OK: $FULL_IMAGE${X}"
else
    LOCAL_IMAGE="te-migration:$TAG"
    echo "${Y}[docker build] Building $LOCAL_IMAGE locally...${X}"
    docker build -f infra/Dockerfile -t "$LOCAL_IMAGE" . || fail "docker build failed"
    echo "${G}[docker build] OK: $LOCAL_IMAGE${X}"

    if [ "$PUSH" -eq 1 ]; then
        [ -n "$ACR_NAME" ] || fail "--push requires --acr <name>" 2
        FULL_IMAGE="${ACR_NAME}.azurecr.io/${LOCAL_IMAGE}"
        echo "${Y}[docker tag+push] $LOCAL_IMAGE -> $FULL_IMAGE${X}"
        az acr login --name "$ACR_NAME" || fail "az acr login failed"
        docker tag "$LOCAL_IMAGE" "$FULL_IMAGE"
        docker push "$FULL_IMAGE" || fail "docker push failed"
        echo "${G}[docker push] OK${X}"
    fi
fi

echo
echo "${G}===========================================================${X}"
echo "${G} BUILD SUCCESS${X}"
echo "${G}===========================================================${X}"
exit 0
