# Decision: Python 3.12 is the one supported version (#328, SE-07)

Status:  Decided; code in the #325/#327/#328/#329 pull request
Date:    2026-11-24
Review:  When Python 3.12 is within a year of end of life (October 2028), or when a dependency stops supporting it

## Choice

One version, **CPython 3.12**, named in one file: `.python-version`. Before this, four places disagreed:

| Where | Before | Now |
|---|---|---|
| Every CI job (`quality-gate.yml`, `python-validator-tests.yml`, `security-scan.yml`) | 3.11 | `python-version-file: .python-version` (3.12) |
| `container/api.Dockerfile` (what ships) | 3.12 | 3.12 |
| `infra/Dockerfile` (migration runner) | 3.11 | 3.12 |
| Offline bundle (`scripts/offline/build_bundle.sh --python-version`, `install.sh`) | 3.12 | 3.12 |
| `preflight.sh` / `preflight.ps1` | 3.10 or later | 3.12 or later required; anything but 3.12 is a warning |
| README badge, `docs/QUICKSTART.md`, `evals/USAGE.md` | 3.10+ | 3.12 |
| Hashed lock files (`scripts/lock_requirements.sh`, #327) | none | compiled for 3.12 |
| `pyproject.toml` `requires-python`, mypy `python_version` (added by #412) | `>=3.10`, unset | `>=3.12`, `3.12` |

## Why 3.12

- It is what ships: the API image and the offline bundle (wheels and `python3.12-venv` from Ubuntu 24.04) already
  used it. CI tested 3.11, so the shipped runtime was never tested. Moving CI to 3.12 closes that gap without
  touching what customers run.
- It is the developers' version (Windows 11 machines run 3.12).
- It is the Python of Ubuntu 24.04, which the offline install targets, so the offline VM needs no extra interpreter.
- The whole database-free suite passes on 3.12 (checked locally on 24 Nov before this change: the unit, regression,
  security and snapshot markers).

## Why one version, not a range

The issue suggested a range (for example 3.11 to 3.12) with a CI matrix over both ends. A range only helps if someone
installs on the lower version, and no install path does: the images, the offline bundle and the developer machines
are all 3.12. A matrix would double the database jobs for a version nobody runs. One version also lets the hashed locks
(#327) be compiled once. If a second version is ever needed (for example during the move to 3.13), add it to the
matrix of the free-tier and integration jobs and compile the locks for both, then remove the old one.

## `pyproject.toml`

When this was decided the repository had no `pyproject.toml`, so `.python-version` became the single source
(`actions/setup-python` reads it, and so do pyenv and uv). #412 then added a `pyproject.toml` for tool configuration;
its `requires-python` is now `>=3.12` and mypy checks against 3.12 (`python_version`), both naming the same version.

## How it stays true

`tests/unit/test_reproducible_builds.py` fails if `.python-version` is not 3.12, if a CI job names its own Python
version, if a Dockerfile's Python base image is another version, if the offline bundle downloads wheels for another
version, if preflight accepts an older version, if `pyproject.toml` names another version, or if the locks are compiled for
another version. Dependabot does not
propose minor or major Python image updates (`.github/dependabot.yml`): changing the version is a new decision.
