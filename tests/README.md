# Test suite

Tests are grouped into six categories. Each group lives in its own folder, and
`tests/conftest.py` automatically gives every test the marker for its folder. So
`pytest tests/uat` and `pytest -m uat` select the same tests.

| Group | Folder | Marker | Needs | What it proves |
|-------|--------|--------|-------|----------------|
| Unit | `tests/unit/` (+ `csv-table-hub-main/src/__tests__/unit/`) | `unit` | nothing | Individual functions and modules behave correctly in isolation (parser, casting, config, auth, pool, loaders' guard paths, validator, eval runner, static security scans, CI-workflow structure). Frontend logic is covered by vitest. |
| System | `tests/system/` | `system` | PostgreSQL | The whole backend works end-to-end through its public HTTP API and shell pipeline: upload → list → read → delete → audit, typing, duplicates, overwrite, limits, T&E mode. |
| System integration (SIT) | `tests/system_integration/` | `sit` | PostgreSQL (+ all 4 envs for parity) | The seams between components: API ↔ frontend contract (checked against the zod schemas in `csv.functions.ts`), API ↔ PostgreSQL bootstrap/schema, API ↔ deploy scripts, cross-environment parity. |
| Performance | `tests/performance/` | `performance` | PostgreSQL for the API cases | Throughput, latency and resource bounds: 100k-row parse, 20k-row upload, concurrent uploads, p95 read latency, constant query count, bounded error payloads. |
| Accessibility | `tests/accessibility/` | `accessibility` | Node + `csv-table-hub-main/node_modules`, Playwright Chromium | WCAG 2.1 A/AA via axe-core in real Chromium, plus keyboard operability, focus trapping, headings, accessible names and 320px reflow. The backend is mocked, so no database is needed. |
| User acceptance (UAT) | `tests/uat/` | `uat` | PostgreSQL | User stories written as Given/When/Then, run against the API with the shipped sample CSVs. |

The SQL assertion suite (`tests/framework/`, `tests/suites/`, `tests/run_all_tests.sql`,
`tests/run_tests.sh`) stays where it is. It is driven by `psql`, not pytest, and the
Tier S eval and deploy scripts reference those paths. It belongs to the system
integration group: it verifies the deployed T&E schema and its business rules.

The full catalogue of test cases, with IDs and objectives, is in
[`docs/TEST_CASES.md`](../docs/TEST_CASES.md). Regenerate it with
`python3 scripts/test_catalogue.py` after adding tests.

## Running

```bash
# Database-free (CI free tier)
make test-unit

# Need a provisioned dev database:
#   bash scripts/provision_full_test_env.sh && export PGDATABASE=te_mgmt_dev
make test-system
make test-sit
make test-performance        # PERF_BUDGET_SCALE=3 on slow machines
make test-uat

# Needs the frontend installed: (cd csv-table-hub-main && bun install)
make test-accessibility      # A11Y_BASE_URL=http://host:port to test a running app

# Frontend unit tests (vitest)
cd csv-table-hub-main && npx vitest run
```

## Rules

- **No skips.** A missing prerequisite (database, Node, Chromium) makes a test fail
  with remediation text. `scripts/test_report.py --strict` enforces this in CI.
- **Leave no data behind.** Database tests use unique content per run and the
  `registry_cleanup` / `te_org_cleanup` fixtures to remove what they created.
- **One group per test.** Put a new test in the folder that matches what it
  proves. Do not add a second category marker by hand.
