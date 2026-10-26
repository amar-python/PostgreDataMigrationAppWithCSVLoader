#!/usr/bin/env bash
# build_bundle.sh: build the offline install bundle (#60).
#
# Run on an INTERNET-CONNECTED Ubuntu 24.04 x86_64 machine with git, python3-pip,
# Node.js 20+ and apt-utils installed, from the repo root:
#   bash scripts/offline/build_bundle.sh
# Output: dist/offline-bundle-<commit>.tar.gz plus its .sha256 file.
# Copy both to the offline VM and follow docs/offline-install.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SHA="$(git rev-parse --short HEAD)"
OUT="$ROOT/dist/offline-bundle-$SHA"
rm -rf "$OUT"; mkdir -p "$OUT"/{wheels,debs}

echo "== 1/4 application source (git HEAD $SHA)"
git archive --format=tar --prefix=app/ HEAD | tar -x -C "$OUT"
rm -rf "$OUT/app/csv-table-hub-main"   # shipped prebuilt below

echo "== 2/4 Python wheels for CPython 3.12, manylinux x86_64"
python3 -m pip download -q -r api/requirements.txt -d "$OUT/wheels" \
  --only-binary=:all: --python-version 3.12 --implementation cp \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux_2_28_x86_64 --platform any
python3 -m pip download -q pip -d "$OUT/wheels" --only-binary=:all: --python-version 3.12

echo "== 3/4 frontend, built for a plain Node server"
# Placeholders are replaced by install.sh with the real API address and key.
( cd csv-table-hub-main
  [ -d node_modules ] || npm ci
  rm -rf .output
  NITRO_PRESET=node-server VITE_API_BASE=__OFFLINE_API_BASE__ VITE_API_KEY=__OFFLINE_API_KEY__ npm run build >/dev/null
  cp -r .output "$OUT/frontend" )

echo "== 4/4 Ubuntu packages: PostgreSQL 16, Python venv, Node.js, with dependencies"
PKGS="postgresql-16 postgresql-client-16 python3.12-venv nodejs"
# ponytail: downloads the whole dependency closure, including packages a stock
# Ubuntu 24.04 already has; apt skips those on install. Prune if size matters.
DEPS=$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts \
  --no-breaks --no-replaces --no-enhances $PKGS | grep '^[a-z0-9]' | sort -u)
( cd "$OUT/debs" && apt-get download $DEPS >/dev/null 2>&1 || true )
for p in $PKGS; do ls "$OUT/debs/${p}_"*.deb >/dev/null || { echo "missing deb: $p" >&2; exit 1; }; done
( cd "$OUT/debs" && apt-ftparchive packages . > Packages )   # local apt repository index

( cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
tar -C "$ROOT/dist" -czf "$OUT.tar.gz" "offline-bundle-$SHA"
( cd "$ROOT/dist" && sha256sum "offline-bundle-$SHA.tar.gz" > "offline-bundle-$SHA.tar.gz.sha256" )
echo "Bundle: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1))"
