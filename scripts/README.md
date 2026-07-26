# scripts/

Independent build and test runners. Each can be triggered on its own —
local (PowerShell or Bash) or in GitHub Actions.

## What's here

| File | Purpose | Sibling CI workflow |
| --- | --- | --- |
| `build.ps1` | Windows: build the migration runner Docker image | _(no CI workflow; run locally)_ |
| `build.sh` | Linux/Mac/Cloud Shell: same | _(no CI workflow; run locally)_ |
| `test.ps1` | Windows: run pytest + SQL suite + evals | `.github/workflows/quality-gate.yml` |
| `test.sh` | Linux/Mac/Cloud Shell: same | `.github/workflows/quality-gate.yml` |

## Common recipes

### Local — just build the image

```powershell
.\scripts\build.ps1
```

```bash
./scripts/build.sh
```

Default: local `docker build`, tag `dev`, no push. Add `--acr-build` /
`-UseAcrBuild` if you don't have Docker installed locally.

### Local — full validation before pushing

```powershell
.\scripts\test.ps1                  # all three layers
.\scripts\test.ps1 -OnlyPython      # quick check, no PG needed
.\scripts\test.ps1 -SkipSql         # python + evals, skip SQL suite
```

```bash
./scripts/test.sh
./scripts/test.sh --only-python
./scripts/test.sh --skip-sql
```

### Build and push to ACR in one go

```powershell
.\scripts\build.ps1 -UseAcrBuild -AcrName acrtedev7u8hql -Tag $(git rev-parse --short HEAD)
```

```bash
./scripts/build.sh --acr-build --acr acrtedev7u8hql --push -t $(git rev-parse --short HEAD)
```

### CI — trigger via GitHub web UI

| Workflow | When to use |
| --- | --- |
| **Quality Gate** — `quality-gate.yml` | Lint, health check, pytest, and Tier P evals on every push |
| **Python Validator Tests** — `python-validator-tests.yml` | Windows unittest run for the CSV validator |

Open <https://github.com/amar-python/PostgreDataMigrationApp/actions>,
pick the workflow, click **Run workflow**, fill in inputs (defaults are
sensible), click the green button.

## Decision rules

| Situation | Run this |
| --- | --- |
| Pulled new code, no infra changes | `build` only |
| Updated only test fixtures | `test` only |
| Updated `build/csv/validator.py` or any source | `build` then `test` |
| Updated `infra/terraform/*` | Run Terraform locally — see `AZURE_DEPLOY.md` |
| End-of-day sanity check | `test -OnlyPython` |
| Before a release | `build` → `test` (full) → manual eyeball |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All selected layers passed |
| `1` | At least one layer failed |
| `2` | Prereq missing (docker/az/pytest) — fix the env, re-run |

## What each layer covers

| Layer | What it asserts | Needs PG? |
| --- | --- | --- |
| `pytest -m unit` | Python validator correctness (~75 tests) | No |
| SQL test suite | 5 suites x ~87 assertions: schema, indexes, business rules | Yes |
| Tier P evals | 23 CSV validator scenarios end-to-end | No |
| Tier I evals | Idempotency: deploy twice, identical row counts | Yes |
| Tier S evals | SQL suite integration: 142/142 PASS post-deploy | Yes |

## Relationship to the other workflows

| Workflow | Owner / scope |
| --- | --- |
| `quality-gate.yml` | Lint, health check, pytest (unit/regression/security/snapshot), Tier P evals. Runs on push. |
| `python-validator-tests.yml` | Windows `unittest discover` run for the CSV validator. Runs on push. |

These are the only two workflows in `.github/workflows/`. The `build.*` and
`test.*` scripts in this directory are run locally; Azure infrastructure is
provisioned with Terraform from `infra/terraform/` (see `AZURE_DEPLOY.md`).
