#!/usr/bin/env bash
# lock_requirements.sh: compile the hashed Python lock files from the requirements files (#327).
#
# The *.txt files are what people edit: direct dependencies with ranges. The *.lock files are what images and CI
# install, with --require-hashes: every package, transitive ones included, at one version, with the hash of every
# wheel and sdist PyPI has for it. They are universal (Linux, Windows and macOS markers resolved together) for the
# one supported Python, 3.12 (DECISIONS/2026-11-24-one-python-version.md).
#
#   lock                       input
#   api/requirements.lock      api/requirements.txt                    (container/api.Dockerfile, offline bundle)
#   streamlit_app/requirements.lock  streamlit_app/requirements.txt
#   requirements-dev.lock      requirements-dev.txt + api/requirements.txt   (most CI jobs)
#   requirements-a11y.lock     the above + requirements-a11y.txt + streamlit_app/requirements.txt (browser jobs)
#
# All four are resolved against one set of versions (the largest set, compiled first, constrains the others), so a
# package has the same version in every lock. tests/unit/test_reproducible_builds.py checks that, and that every
# entry is hashed.
#
# Run from anywhere, with uv installed (pip install uv), after changing a requirements file:
#   bash scripts/lock_requirements.sh            # keep current versions where the inputs allow
#   bash scripts/lock_requirements.sh --upgrade  # move everything to the newest allowed versions
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY=3.12
EXTRA=("$@")
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

compile() {   # compile <output> <inputs...>
  local out="$1"; shift
  uv pip compile --quiet --universal --python-version "$PY" --generate-hashes \
    --custom-compile-command "bash scripts/lock_requirements.sh" \
    "${EXTRA[@]}" "$@" -o "$out"
}

# 1. The largest set first; its versions (without hashes) constrain the other three.
compile requirements-a11y.lock requirements-dev.txt api/requirements.txt requirements-a11y.txt \
  streamlit_app/requirements.txt
uv pip compile --quiet --universal --python-version "$PY" --no-header --no-annotate \
  "${EXTRA[@]}" requirements-dev.txt api/requirements.txt requirements-a11y.txt streamlit_app/requirements.txt \
  -o "$WORK/constraints.txt"

EXTRA=()   # --upgrade applied to the largest set; the others follow its versions
compile requirements-dev.lock          -c "$WORK/constraints.txt" requirements-dev.txt api/requirements.txt
compile api/requirements.lock          -c "$WORK/constraints.txt" api/requirements.txt
compile streamlit_app/requirements.lock -c "$WORK/constraints.txt" streamlit_app/requirements.txt
# The constraints file lives in a temporary folder; name it by what it is, so a re-lock does not change every lock.
for f in requirements-dev.lock api/requirements.lock streamlit_app/requirements.lock; do
  sed -i "s|-c $WORK/constraints.txt|-c requirements-a11y.lock (versions only)|" "$f"
done
echo "locked: requirements-a11y.lock requirements-dev.lock api/requirements.lock streamlit_app/requirements.lock"
