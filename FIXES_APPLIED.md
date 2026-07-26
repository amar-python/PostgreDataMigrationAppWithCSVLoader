# Fixes Applied

Every change made during the documentation audit and no-skip hardening pass,
with the evidence that verified it.

**Baseline:** `main` @ `b255262`
**Environment:** clean Ubuntu 24.04 container, PostgreSQL 16.14, Python 3.12.3
**Artifacts:** `test-artifacts/` (see `00_SUMMARY.md`)

---

## Summary

| # | Fix | Severity | Verified by |
|---|---|---|---|
| F1 | `env_dev.example.sql` missing 12 `tbl_*` variables | **Blocking** | `02_deploy_dev.log` |
| F2 | `env_{test,staging,prod}.example.sql` did not exist | **Blocking** | `01_provision.log` |
| F3 | CI deployed a gitignored file that was never re-added | **Blocking** | workflow diff |
| F4 | Tests skipped or failed confusingly on missing prerequisites | High | `09_negative_control_unprovisioned.log` |
| F5 | Eval runner skipped when PostgreSQL was unreachable | High | `evals/runner.py` diff |
| F6 | No visibility of what a run did *not* execute | High | `08_test_report_dbfree_markers.log` |
| F7 | Documentation counts and paths stale in 9+ places | Medium | `03_sql_test_suite.log` |

---

## F1 — Fresh clone could not deploy (blocking)

### Symptom

```text
psql:build/te_core_schema.sql:94: ERROR:  syntax error at or near ":"

```

### Cause

The finalisation pass (PR #22) deleted `build/environments/env_dev.sql`
(20 `\set` variables) and committed `env_dev.example.sql` with only 8. The 12
`tbl_*` variables that `build/te_core_schema.sql` requires were dropped, so psql
passed `:'tbl_requirements'` to the server literally.

**Fix** — restored the table-name block to the committed template.

**Evidence** — `02_deploy_dev.log`: exit 0, 12 tables in `te_dev`, seed loaded.

## F2 — Three of four environments were undeployable (blocking)

Only `env_dev.example.sql` shipped. `env_test.sql`, `env_staging.sql` and
`env_prod.sql` were deleted and no templates replaced them, so `test`, `staging`
and `prod` could not be deployed by any route.

**Fix** — added `env_test.example.sql`, `env_staging.example.sql` and
`env_prod.example.sql`, preserving each environment's documented settings
(conn limits 15 / 25 / 50; seed data on for test only).

**Evidence** — `01_provision.log`: all four deploy successfully.

## F3 — CI deployed a file that does not exist (blocking)

`quality-gate.yml` ran:

```yaml
run: psql -v ON_ERROR_STOP=1 -f build/environments/env_test.sql

```

That path is gitignored and was never re-added, so the `integration-postgres`
job could not succeed.

**Fix** — added a step that materialises `env_<env>.sql` from the committed
templates before any deploy, extended database creation to all four
environments, and replaced the single deploy with a loop over all four.

## F4 — Tests reported green while doing nothing

`test_parity` and `test_e2e_pipeline` gated only on *server reachability*. With
PostgreSQL running but nothing deployed they failed with confusing errors; in CI
they skipped silently.

**Fix** — prerequisites are now checked explicitly and their absence is a
**failure** with remediation text, never a skip:

| File | Guard |
|---|---|
| `tests/test_e2e_pipeline.py` | `setUpClass` raises unless PG **and** `env_dev.sql` present |
| `tests/test_parity.py` | `_require_pg()` / `_require_deployed()` |
| `tests/test_csv_loader_arbitrary_shapes.py` | `setUpClass` raises unless `config.local.env` present |
| `tests/test_csv_utilise.py` | `setUpClass` raises when bash is missing |

Added `scripts/provision_full_test_env.sh` so every prerequisite can be created
in one command.

**Evidence** — `09_negative_control_unprovisioned.log`: 44 passed, 6 failed,
4 errored, **0 skipped**, `RESULT: FAIL`. The same state previously reported
green.

## F5 — Eval runner skipped instead of failing

`evals/runner.py` set `result.skipped = True` for Tiers I and S when PostgreSQL
was unreachable. Both sites now record a failure. `tests/test_evals_runner.py`
asserted the old contract and was updated to assert the new one.

## F6 — No visibility of what was not run

Added `scripts/test_report.py`. Every run ends with a block accounting for all
collected tests:

```text
  collected     : 54
  executed      : 54
  PASSED        : 54
  FAILED        : 0
  ERROR         : 0
  SKIPPED       : 0
  NOT RUN       : 0  (deselected by the marker filter)

```

The **SKIPPED** section prints even when empty, so its absence is never
ambiguous, and **NOT RUN** names each deselected test. `--strict` exits non-zero
on any skip. Both workflows now end with it.

Verified with a planted `@unittest.skip`: reported as `SKIPPED (1)` with its
reason and failed the run under `--strict`. Probe removed afterwards.

## F7 — Documentation staleness

| Claim | Was | Actual |
|---|---|---|
| SQL assertions (9 files) | 85 | **142** |
| Python unit tests | 11 | **54** across 9 files |
| `TEST_CONDITIONS.md` categories | six, incl. `input_data/load_input_data.sql` | five — `input_data/` never existed |
| `ARCHITECTURE.md` → `evals/README.md` | nonexistent | `evals/USAGE.md` |
| `scripts/README.md` workflows | five workflow files | only the two that exist here |
| `evals/USAGE.md` tutorial | `21_rtl_arabic` — collides with real `21_utf8_arabic` | renumbered to `24_` |

README's own "142 assertions" was already correct. A static grep of `assert_*`
call sites returns 131; the suite reports **142** because some assertions run
inside loops — which is why the number was confirmed by execution
(`03_sql_test_suite.log`) rather than by grep.

---

## Files changed

### Added (5)

```text
build/environments/env_test.example.sql
build/environments/env_staging.example.sql
build/environments/env_prod.example.sql
scripts/provision_full_test_env.sh
scripts/test_report.py

```

**Modified (19)** — 2 workflows, 9 documentation files, `evals/runner.py`,
5 test modules, `tests/run_python_tests.ps1`, `build/environments/env_dev.example.sql`.

---

## Not fixed — needs a decision

**`build/config.env.example` variable names do not match the loaders.**
The example defines `DEV_DB_NAME`, `DEV_SCHEMA`, `PG_PASSWORD`; `build/setup.sh`
and `build/csv/loader_postgresql.sh` read `PG_DB_DEV`, `PG_SCHEMA_DEV`,
`PG_SUPERUSER_PASSWORD`. Because `setup.sh` sources the example for its
defaults, those defaults never bind, and copying it straight to
`config.local.env` produces `PG_DB_DEV: unbound variable` and a 100% CSV
load-failure rate.

`provision_full_test_env.sh` writes the correct names, so this is worked around,
not fixed. Renaming touches the example, `setup.sh` and all six loaders — see
`GAP_ANALYSIS.md`.
