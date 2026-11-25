# Decision: Reproducible builds: hashed Python locks, one JS lock, base images by digest (#327, SE-06)

Status:  Decided; code in the #325/#327/#328/#329 pull request
Date:    2026-11-24
Review:  When Dependabot's support for uv-compiled lock files is confirmed, or when the remaining gaps below are closed

## What changed

| Gap | Now |
|---|---|
| Python requirements use ranges; no lock | Four hashed lock files, compiled by `scripts/lock_requirements.sh` with `uv pip compile --universal --generate-hashes` for Python 3.12: `api/requirements.lock`, `streamlit_app/requirements.lock`, `requirements-dev.lock` (dev + API: most CI jobs) and `requirements-a11y.lock` (dev + API + accessibility + Streamlit: the browser jobs). Universal: one lock serves Linux, Windows and macOS. All four share one set of versions |
| Installs could pull anything in range | CI installs only from a lock, with `pip install --require-hashes`. So do `container/api.Dockerfile` and the offline bundle (`pip download` and the offline `pip install`, both `--require-hashes`) |
| Two JS lock files (`bun.lock`, `package-lock.json`) | `bun.lock` and `bunfig.toml` deleted; `package-lock.json` is the one lock (CI, the images and the offline bundle all use `npm ci`). The new `frontend` CI job fails if `npm ci` changes a tracked file |
| Base images by tag | Every `FROM` pinned by digest (`python:3.12-slim`, `node:22-slim`, `postgres:16`, `golang:1.26`), as are the CI service image (`postgres:16-alpine`) and the trivy and gitleaks images. Dependabot's docker ecosystem proposes new digests (#325) |
| No `HEALTHCHECK` in the images | The API and frontend images have one; it is the same probe as the compose healthcheck (the frontend service got one in compose too) |

`tests/unit/test_reproducible_builds.py` keeps it so: every lock entry is hashed; each lock still satisfies the
requirements files it was compiled from; a package has the same version in every lock; CI installs only from locks
with `--require-hashes`; one JS lock; every `FROM`, service and tool image has a digest; the healthchecks match.

## How a dependency changes now

1. Edit the `requirements*.txt` file (or merge Dependabot's pull request, which edits it).
2. Run `bash scripts/lock_requirements.sh` (`--upgrade` to move everything to the newest allowed versions) and commit
   the locks. Until then, the test above fails if the lock no longer satisfies the edited range.

## Not done, and why

- **Dependabot does not regenerate the locks.** It updates the `requirements*.txt` files. Whether it also understands
  uv-compiled lock files is not confirmed, so the locks are refreshed with the script after its pull requests, and the
  test makes a stale lock fail rather than pass quietly.
- **The 24-hour release-age guard in `bunfig.toml` is gone with it.** It applied only to installs with bun, which
  nothing in CI or the images used. Nothing replaces it for npm here; the lock file (with its integrity hashes) and the
  review of Dependabot's pull requests are the protection. Worth revisiting if npm's own release-age setting is adopted.
- **Tools installed for single steps are pinned by version, not hash**: `pip-audit==2.10.1` (security scan),
  `podman-compose` (the Podman install test) and `uv` (only on the machine that runs the lock script). They are not
  in any image. Hash-pinning them means a lock each for one package; not worth it yet.
- **Debian and Ubuntu packages are not pinned** (`apt-get install` in the Dockerfiles and the offline bundle's `.deb`
  download). The base image digest fixes the starting point; the security-only upgrades in the Dockerfiles (#326)
  deliberately take the archive's newest fix.
- **The image build is not bit-for-bit reproducible** (timestamps, layer metadata). The aim here is that two builds
  install the same, verified code, not identical image digests.
