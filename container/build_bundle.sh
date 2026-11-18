#!/usr/bin/env bash
# build_bundle.sh: build the container images and assemble the offline bundle (#128, BR-38).
# Run on a machine WITH internet access, from anywhere in the repo, with Docker or Podman.
#
#   bash container/build_bundle.sh images               # build the 3 images for THIS CPU and
#                                                       # save dist/te-images-<version>-<arch>.tar
#   bash container/build_bundle.sh assemble TAR [TAR..] # put one or more such tarballs, plus the
#                                                       # compose file and installers, in a bundle
#
# Each CPU's images are built on a machine with that CPU (CI uses a native runner for each),
# so there is no emulation. `assemble` takes the tarballs from each CPU, so one bundle
# serves amd64 and arm64: the installer loads the one that matches the machine.
# Output: dist/te-container-bundle-<version>/, its .tar.gz and a .sha256 for the .tar.gz.
#
# TE_VERSION overrides the version (default: the short git commit). TE_RUNTIME picks
# docker (default) or podman.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RT="${TE_RUNTIME:-docker}"
VERSION="${TE_VERSION:-$(git rev-parse --short HEAD)}"
mkdir -p dist

sums() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

case "${1:-}" in
  images)
    case "$(uname -m)" in
      x86_64|amd64)  ARCH=amd64 ;;
      arm64|aarch64) ARCH=arm64 ;;
      *) echo "unsupported CPU: $(uname -m)" >&2; exit 1 ;;
    esac
    for img in api frontend db; do
      echo "== build te-$img:$VERSION ($ARCH)"
      $RT build -f "container/$img.Dockerfile" -t "te-$img:$VERSION" .
    done
    TAR="dist/te-images-$VERSION-$ARCH.tar"
    $RT save -o "$TAR" "te-api:$VERSION" "te-frontend:$VERSION" "te-db:$VERSION"
    echo "Images: $TAR ($(du -h "$TAR" | cut -f1))"
    ;;

  assemble)
    shift
    [ "$#" -ge 1 ] || { echo "usage: build_bundle.sh assemble TAR [TAR...]" >&2; exit 1; }
    OUT="dist/te-container-bundle-$VERSION"
    rm -rf "$OUT"; mkdir -p "$OUT"
    for tar in "$@"; do
      case "$tar" in
        *-amd64.tar) cp "$tar" "$OUT/images-amd64.tar" ;;
        *-arm64.tar) cp "$tar" "$OUT/images-arm64.tar" ;;
        *) echo "not an images tarball (expected ...-amd64.tar or ...-arm64.tar): $tar" >&2; exit 1 ;;
      esac
    done
    cp container/docker-compose.yml container/install.sh container/install.ps1 "$OUT/"
    printf '%s\n' "$VERSION" > "$OUT/VERSION"
    ( cd "$OUT" && sums $(ls | grep -v '^SHA256SUMS$' | sort) > SHA256SUMS )
    tar -C dist -czf "$OUT.tar.gz" "te-container-bundle-$VERSION"
    ( cd dist && sums "te-container-bundle-$VERSION.tar.gz" > "te-container-bundle-$VERSION.tar.gz.sha256" )
    echo "Bundle: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1)); CPUs: $(cd "$OUT" && ls images-*.tar | sed 's/images-//; s/\.tar//' | tr '\n' ' ')"
    ;;

  *)
    sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
