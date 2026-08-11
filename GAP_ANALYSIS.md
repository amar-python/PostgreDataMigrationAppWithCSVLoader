# Gap Analysis

Open gaps in the repository after the documentation audit and no-skip hardening
pass. Fixed items are in `FIXES_APPLIED.md`; evidence is in `test-artifacts/`.

**Assessed at:** `main` @ `b255262` + audit changes
**Method:** clean-clone execution on Ubuntu 24.04 with PostgreSQL 16.14 — every
claim below was reproduced, not inferred from reading code.

> **Relationship to `VCRM_GAPS.md`:** that file traces the 22 business
> requirements to eval evidence and is regenerated per run. This document covers
> engineering gaps that sit outside the BR set — configuration, coverage and
> process. The two are complementary.

---

## Open gaps

| ID | Gap | Severity | Decision needed |
|---|---|---|---|
| G1 | ~~`config.env.example` names do not match `setup.sh` / loaders~~ | **Closed** | Renamed to `PG_*_<ENV>` scheme |
| G2 | ~~Windows CI cannot run database-backed tests~~ | **Closed** | Added `windows-postgres` job to `quality-gate.yml` |
| G3 | Tiers X and E remain unimplemented | Medium | No — deferred by design |
| G4 | ~~Runtime artifacts are not gitignored~~ | **Closed** | Added to `.gitignore` |
| G5 | ~~`VCRM.md` BR-20 assertion count edited~~ | **Closed** | Confirmed: 142 matches suite output and Tier S JSON |

---

### G1 — `config.env.example` variable names (Closed)

**Resolution:** Renamed all variables in `config.env.example` to the
`PG_*_<ENV>` scheme (`PG_DB_DEV`, `PG_SCHEMA_DEV`, `PG_SUPERUSER`,
`PG_SUPERUSER_PASSWORD`, etc.) — matching what `loader_postgresql.sh`,
`csv_utilise.sh`, and `setup.sh`'s output all expect.

Copying the example directly to `config.local.env` now produces a working
configuration. The `provision_full_test_env.sh` workaround is still valid but
no longer required for basic operation.

### G2 — Windows CI cannot host PostgreSQL (Closed)

**Resolution:** Added a `windows-postgres` job to `quality-gate.yml` that starts
the pre-installed PostgreSQL service on the `windows-latest` runner, provisions
all four environment databases, deploys schemas, and runs the full test suite
(including `integration`, `e2e`, and `parity` markers) plus Tier P evals.

The existing `python-validator-tests.yml` Windows job continues to run
database-free markers as a fast signal; the new quality-gate job covers the
full surface.

### G3 — Tiers X and E unimplemented (Medium)

`evals/PLAN.md` defines five tiers; P, I and S are implemented. **X**
(cross-engine schema equivalence) and **E** (cross-environment structural
parity) remain deferred, so cross-engine claims for MariaDB, SQLite, InfluxDB,
Redis and Teradata rest on code review rather than execution.

Partially mitigated: `tests/test_parity.py::TestAllEnvironmentsHaveRequiredTables`
now runs against all four PostgreSQL environments.

### G4 — Runtime artifacts not gitignored (Closed)

**Resolution:** All four suggested entries were added to `.gitignore`:
`tests/snapshots/`, `tfplan`, `*.tfplan`, `terraform-provider-*.log`.

### G5 — `VCRM.md` BR-20 assertion count (Closed)

**Resolution:** Confirmed. The suite reports **142** assertions and the
Tier S expectation JSON specifies 142. The old "85 of 85" was stale; the
update to 142 is correct. No revert needed.

---

## Closed by this pass

| Gap | Evidence |
|---|---|
| Fresh clone could not deploy | `02_deploy_dev.log` |
| test / staging / prod undeployable | `01_provision.log` |
| CI deployed a nonexistent file | workflow diff |
| Prerequisites skipped silently | `09_negative_control_unprovisioned.log` |
| No visibility of unrun tests | `08_test_report_dbfree_markers.log` |
| Stale documentation counts | `03_sql_test_suite.log` |

---

## Coverage position

| Layer | Status | Evidence |
|---|---|---|
| Python unit / regression / security / snapshot | 54 tests, 0 skipped | `05_test_report_full.log` |
| SQL assertions | 142 / 142, 100% | `03_sql_test_suite.log` |
| Eval tiers P, I, S | 25 / 25, 0 skipped | `04_evals_p_i_s.log` |
| Eval tiers X, E | Not implemented | G3 |
| PostgreSQL engine | Fully exercised | above |
| Other five engines | Code review only | G3 |
