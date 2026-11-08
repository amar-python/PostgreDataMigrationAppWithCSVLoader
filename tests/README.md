# Test categories

Tests are grouped by **what they need to run**, not by what they cover. The
folder is the grouping; `tests/conftest.py` gives every test the marker of its
folder, so `pytest -m sit` and `pytest tests/system_integration` select the
same set.

| Folder | Marker | Needs | Target |
|---|---|---|---|
| `unit/` | `unit` | nothing | `make test-unit` |
| `system/` | `system` | PostgreSQL | `make test-system` |
| `system_integration/` | `sit` | PostgreSQL, a deployed environment | `make test-sit` |
| `performance/` | `performance` | PostgreSQL | `make test-performance` |
| `accessibility/` | `accessibility` | Playwright browsers + the Vite dev server | `make test-accessibility` |
| `uat/` | `uat` | PostgreSQL | `make test-uat` |

The older behaviour markers (`integration`, `e2e`, `regression`, `security`,
`snapshot`, `parity`) still apply and still drive CI's tier split. A test can
carry both: `tests/unit/test_regression.py` is `unit` *and* `regression`.

## Which folder does a new test go in?

- Imports a module and asserts on its return value → `unit/`
- Drives one component through its public surface (the HTTP API, the loader
  CLI) and needs a database → `system/`
- Crosses components, or checks a deployed schema or environment → `system_integration/`
- Asserts a timing or throughput budget → `performance/`
- Asserts a WCAG rule against rendered pages → `accessibility/`
- Traces to an issue or a user story and reads as a user would describe it → `uat/`

## No-skip policy

An unmet prerequisite **fails** with remediation text; it does not skip.
`scripts/test_report.py --strict` enforces this in CI. The shared fixtures in
`tests/conftest.py` (`live_api`, `registry_cleanup`, `te_org_cleanup`,
`destructive_enabled`, `unique_tag`) already follow it — prefer them over a
per-module `setUpClass` that swallows a connection error.

## Non-Python suites

`suites/` and `framework/` hold the SQL assertion suites, run by
`evals/runner.py` (Tier S), not by pytest.
