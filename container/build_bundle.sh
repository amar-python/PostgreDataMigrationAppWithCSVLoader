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
#
# SBOMs (#326): `assemble` puts a CycloneDX SBOM for each image of each CPU in the bundle, under sbom/, from
# TE_SBOM_DIR (default dist/sbom; files te-<image>-<arch>.cdx.json, which CI writes with trivy). They are listed in
# SHA256SUMS like everything else. TE_REQUIRE_SBOM=1 makes a missing SBOM an error. A file that is not a CycloneDX
# SBOM with components is always an error.
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
    ARCHS=""   # a string, not an array: this may run on macOS, whose bash 3.2 rejects an empty array under set -u
    for tar in "$@"; do
      case "$tar" in
        *-amd64.tar) cp "$tar" "$OUT/images-amd64.tar"; ARCHS="$ARCHS amd64" ;;
        *-arm64.tar) cp "$tar" "$OUT/images-arm64.tar"; ARCHS="$ARCHS arm64" ;;
        *) echo "not an images tarball (expected ...-amd64.tar or ...-arm64.tar): $tar" >&2; exit 1 ;;
      esac
    done
    cp container/docker-compose.yml container/install.sh container/install.ps1 "$OUT/"
    printf '%s\n' "$VERSION" > "$OUT/VERSION"

    # One SBOM per image per CPU in the bundle; an SBOM for a CPU that is not in the bundle is left out.
    SBOM_DIR="${TE_SBOM_DIR:-dist/sbom}"
    SBOM_COUNT=0
    if [ -d "$SBOM_DIR" ]; then
      for arch in $ARCHS; do
        for img in api frontend db; do
          f="$SBOM_DIR/te-$img-$arch.cdx.json"
          if [ -f "$f" ]; then
            if ! { grep -Eq '"bomFormat"[[:space:]]*:[[:space:]]*"CycloneDX"' "$f" && grep -q '"components"' "$f"; }; then
              echo "not a CycloneDX SBOM with components: $f" >&2; exit 1
            fi
            mkdir -p "$OUT/sbom"; cp "$f" "$OUT/sbom/"; SBOM_COUNT=$((SBOM_COUNT + 1))
          elif [ "${TE_REQUIRE_SBOM:-}" = 1 ]; then
            echo "missing SBOM: $f (TE_REQUIRE_SBOM=1)" >&2; exit 1
          fi
        done
      done
    elif [ "${TE_REQUIRE_SBOM:-}" = 1 ]; then
      echo "TE_REQUIRE_SBOM=1, but there is no SBOM directory: $SBOM_DIR" >&2; exit 1
    fi

    ( cd "$OUT" && sums $(find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort) > SHA256SUMS )
    tar -C dist -czf "$OUT.tar.gz" "te-container-bundle-$VERSION"
    ( cd dist && sums "te-container-bundle-$VERSION.tar.gz" > "te-container-bundle-$VERSION.tar.gz.sha256" )
    echo "Bundle: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1)); CPUs: $(cd "$OUT" && ls images-*.tar | sed 's/images-//; s/\.tar//' | tr '\n' ' '); SBOMs: $SBOM_COUNT"
    ;;

  *)
    sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
