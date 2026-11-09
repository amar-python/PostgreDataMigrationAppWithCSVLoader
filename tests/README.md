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
| `accessibility/` | A real browser against the running app, WCAG scans (#168) | `accessibility` (automatic) | `make test-accessibility` |
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

`docs/TEST_CASES.md` lists every test and is generated: run
`python3 scripts/test_catalogue.py` after adding or moving tests. CI fails if it is stale.
