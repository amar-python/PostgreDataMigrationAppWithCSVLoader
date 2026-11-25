# Tests

Python tests are grouped by **what they need to run**, one folder per category. The
folder a test lives in is its category; `conftest.py` adds the matching marker
automatically.

| Folder | Needs | Marker | Run with |
|---|---|---|---|
| `unit/` | Nothing: no database, no network. Includes the regression, security-scan and snapshot tests | `unit` (explicit) | `make test-unit` |
| `system/` | The API and a live PostgreSQL | `system` (automatic) | `make test-system` |
| `system_integration/` | The whole pipeline: shell loaders, every deployed environment, cross-environment parity | `sit` (automatic) | `make test-sit` |
| `performance/` | Load and timing tests (none yet) | `performance` (automatic) | `make test-performance` |
| `accessibility/` | Chromium, the frontend's dev server and Node; the API is stubbed. WCAG 2.1 AA scans, own CI job ([README](accessibility/README.md), #168) | `accessibility` (automatic) | `make test-accessibility` |
| `uat/` | User-acceptance scenarios (none yet) | `uat` (automatic) | `make test-uat` |

Which folder does a new test go in? Ask what is the least it needs: nothing →
`unit/`; the API against PostgreSQL → `system/`; several components or environments
together → `system_integration/`.

The finer markers still work and are what CI selects on: `integration`, `e2e`,
`regression`, `security`, `snapshot`, `parity`. The free tier (and the Windows job)
runs `unit or regression or security or snapshot`, so a test that needs a database
must not carry `unit`.

A file is placed by its heaviest need. Six files in `system/` also hold database-free
classes (marked `unit`); they run in the free tier because that selects on the marker,
not the folder. So `-m unit` and `-m system` overlap by those classes.

## Not Python, so not moved

`suites/` and `framework/` are the SQL assertion suites (`run_tests.sh` runs them),
`snapshots/` holds golden files, and `run_python_tests.ps1` is the Windows runner.

## Running

```bash
make test-unit                       # one category
python -m pytest tests/system -v     # the same, directly
python -m pytest -m "not accessibility"   # everything except the browser job
python -m pytest tests/system/test_roles.py   # one file
```

Database-backed tests **fail, never skip**, when PostgreSQL isn't reachable; start one
first (`scripts/provision_full_test_env.sh`). A category with no tests yet (`make
test-performance`, `make test-uat`) reports that and succeeds.

## Coverage

One scope, measured one way (#274, #278), the same in `.coveragerc`, the Makefile (`COVERAGE_SCOPE`) and the `coverage`
job of `quality-gate.yml`, with branch coverage.

| | |
|---|---|
| Measured | `api/` (routers, auth, tenancy, services), `streamlit_app/`, `build/csv` (the validator) and `evals/` (the runner) |
| Gated | the three loaders in `api/services/` per file, and `api/` and `streamlit_app/` each as a whole (`scripts/check_coverage_floors.py`) |
| Measured, not gated | `build/csv` and `evals/`: the loaders are shell, which coverage.py cannot see, and the runner is exercised through subprocesses, so they read low (0 % and 39 % on the full suite, 19 Nov) and a floor would mean nothing |
| Not measured | `scripts/`, and the React app (`csv-table-hub-main/`, which has its own vitest suite) |

`make coverage` runs what CI runs: the whole suite (it needs PostgreSQL, `PGDATABASE=te_mgmt_dev`), then the floors.
`make test-gate` prints the same scope for the free-tier tests, without floors, because the API figure is partial
without a database. The floors are statements, not branches, and sit a few points under the numbers measured on
19 Nov 2026 (api 94.4 %, `streamlit_app` 97.5 %); raise them as the numbers rise.
`tests/unit/test_ci_quality_gate.py` fails if the three places stop naming the same scope.

## Shared fixtures (`conftest.py`)

For tests that drive the live API. `unittest.TestCase` classes can't take fixture
arguments, so each fixture also sets an attribute; use them with
`@pytest.mark.usefixtures(...)`:

| Fixture | Scope | Gives you |
|---|---|---|
| `live_api` | class | the API started with its database pool; `self.client` |
| `destructive_enabled` | class | `API_ALLOW_DESTRUCTIVE` on for the class, restored after |
| `registry_cleanup` | test | `self.registry_cleanup`: append a file name and its registry row is deleted afterwards |
| `te_org_cleanup` | test | `self.te_org_cleanup`: append organisation names inserted into the T&E schema; deleted afterwards |

`system/test_failed_uploads.py` and one test in `system/test_review.py` use them. The
other 19 files that start the API by hand haven't been converted.

## Paths

A test file reaches the repository root with `Path(__file__).resolve().parents[2]`
(`tests/<category>/<file>`); `tests/snapshots/` is `parents[1] / "snapshots"`.

## The catalogue

`docs/TEST_CASES.md` lists every test. It is generated and **not committed**: run
`python3 scripts/test_catalogue.py` for a local copy, or download the `test-catalogue`
artifact from a CI run. It used to be committed, and every PR that added or moved a test
conflicted on it whenever `main` regenerated it.

## How CI runs the tests in parallel

The database jobs used to run one after another (the suite, the system tests again with the network blocked, then the
whole suite a third time for coverage): 25 to 40 minutes. Now `quality-gate.yml` runs them side by side:

| Job | Runs |
|---|---|
| `integration-shards` (1 to 3) | the test files of its shard, through `scripts/test_report.py --strict --paths ...` (so every test it holds is accounted for) |
| `integration-egress` (1 to 3) | the firewall steps and `pytest <its share of tests/system> --block-egress` |
| `coverage` | no tests: combines the coverage each shard recorded as it ran and applies the floors |
| `csv-loader` | `csv_loader/tests` (the imported CSV-loader tool) through `scripts/test_report.py --strict`, with its own PostgreSQL; the root `pytest.ini` collects only `tests/`, so this job is the only way they run |
| `integration-postgres` | the check named **integration (postgres service)**: succeeds only if the three above did |

- **The split** is by test file (`scripts/ci_shards.py`), heaviest first into the lightest shard, from the durations in
  `ci/shard_weights.json`. Each shard has its own PostgreSQL service, because the system tests share databases and assume a
  fresh one. A file with no recorded duration still lands in a shard, and `tests/unit/test_ci_shards.py` checks that every
  file pytest collects is in exactly one shard, so a test cannot silently stop running.
- **Egress shards:** the egress-blocked pass splits `tests/system/` the same way (`ci_shards.py files --shard K --of 3 --only
  tests/system/`), each shard in its own job with its own firewall block; `EGRESS_SHARDS` in `scripts/ci_shards.py` and the
  `shard:` matrix of `integration-egress` are kept in step by a test.
- **Coverage** is recorded inside the shards (`PYTEST_ADDOPTS` carries the `--cov` scope into `scripts/test_report.py`), each
  shard uploads `coverage-shard-N.dat`, and the `coverage` job runs `coverage combine`, `coverage json` and the floors.
- **Change the number of shards** in two places that a test keeps in step: `SHARDS` in `scripts/ci_shards.py` and the `shard:`
  matrix in the workflow (and the `--of` in its run step).
- **Refresh the durations** after the suite changes a lot (a full run against a fresh database, then record it):
  ```
  python3 -m pytest tests -m "not accessibility" --junitxml=junit.xml
  python3 scripts/ci_shards.py update-weights junit.xml     # rewrites ci/shard_weights.json
  python3 scripts/ci_shards.py plan --of 3                  # shows the split and the estimate
  ```
- **Documentation-only changes skip the database jobs** (`scripts/ci_changes.py`). A document counts as documentation only if
  no test, eval, script, source file or workflow names it by file name (several tests read documents, and only the database
  jobs run some of them); on any doubt, and on every push to `main`, everything runs. The fast jobs (free tier, browser,
  accessibility) always run. `scripts/ci_gate.py` turns the jobs' results into the one check, and treats a skipped job as
  a failure for a code change.
- **A newer push to a pull request cancels its older run**; runs on `main` are never cancelled.
