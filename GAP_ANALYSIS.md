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
| G2 | Windows CI cannot run database-backed tests | Medium | Accepted — ubuntu `integration-postgres` covers the full suite |
| G3 | Tiers X and E remain unimplemented | Medium | No — deferred by design |
| G4 | Runtime artifacts are not gitignored | Low | No |

G1 and G5 (below) are resolved — see "Closed by this pass".

---

### G1 — `config.env.example` variable names (High) — RESOLVED 2026-08-12

#### Reproduction (historical — no longer reproduces)

```text
$ cp build/config.env.example build/config.local.env
$ bash build/csv_loader.sh data.csv --engine postgresql --env dev
build/csv/loader_postgresql.sh: line 33: PG_DB_DEV: unbound variable

```

#### Detail (historical)

| Consumer | Expects | `config.env.example` provided (old) |
|---|---|---|
| `build/csv/loader_postgresql.sh` | `PG_DB_DEV`, `PG_SCHEMA_DEV` | `DEV_DB_NAME`, `DEV_SCHEMA` |
| `build/setup.sh` (defaults) | `PG_DB_DEV`, `PG_SUPERUSER_PASSWORD` | `DEV_DB_NAME`, `PG_PASSWORD` |

Two consequences: `setup.sh` sources the example for its wizard defaults, so
those defaults silently never bound; and anyone copying the example directly to
`config.local.env` got a 100% CSV load-failure rate.

#### Resolution

`build/config.env.example` now uses the `PG_*_<ENV>` scheme throughout,
matching `setup.sh` and all six loaders exactly (verified: `grep PG_DB_
build/config.env.example build/setup.sh` shows identical variable names, and
`cp build/config.env.example build/config.local.env` followed by a loader run
no longer hits an unbound-variable error). This doc previously listed G1 as
open with a decision still needed — that was stale; the rename (option 1) was
already applied in the code.

### G2 — Windows CI cannot host PostgreSQL (Medium)

GitHub Actions service containers are Linux-only, so
`python-validator-tests.yml` (windows-latest) cannot run the `integration`,
`e2e` or `parity` markers. With missing prerequisites now fatal, collecting them
there would make the job permanently red.

**Current state:** the Windows job runs the database-free markers and prints the
15 tests it does not run **by name**, so the gap is visible rather than implied.
Those tests run in the Linux `integration-postgres` job. Every test reports
pass/fail in exactly one job.

**Option:** start the PostgreSQL service on the Windows runner (the GitHub
Windows image ships it, stopped) and provision there too. Not verified — no
Windows runner was available during this audit.

### G3 — Tiers X and E unimplemented (Medium)

`evals/PLAN.md` defines five tiers; P, I and S are implemented. **X**
(cross-engine schema equivalence) and **E** (cross-environment structural
parity) remain deferred, so cross-engine claims for MariaDB, SQLite, InfluxDB,
Redis and Teradata rest on code review rather than execution.

Partially mitigated: `tests/test_parity.py::TestAllEnvironmentsHaveRequiredTables`
now runs against all four PostgreSQL environments.

### G4 — Runtime artifacts not gitignored (Low)

These appear as untracked after a normal run and risk being committed by a
careless `git add -A`:

```text
tests/snapshots/all_valid_expected_valid.csv
infra/terraform-prod/tfplan
infra/terraform/terraform-provider-debug-after-refresh.log

```

**Suggested `.gitignore` additions**

```text
tests/snapshots/
tfplan
*.tfplan
terraform-provider-*.log

```

### G5 — `VCRM.md` BR-20 edited (Low) — RESOLVED

BR-20 read "85 of 85 assertions passing"; the suite reports **142** and the
Tier S expectation JSON already specified 142. Updated to match observed
behaviour. Flagged because `VCRM.md` is a formal traceability document — revert
if that figure is contractually fixed.

**Confirmed, not reverted:** verified `VCRM.md` still reads "142 of 142
assertions passing" and matches the current Tier S expected JSON and observed
suite output (142/142, 100%). No contractual reason to revert was raised, so
the figure stands. This doc previously listed G5 as open pending confirmation
— confirming it here closes it.

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
| G1 — `config.env.example` variable-name mismatch | `grep PG_DB_ build/config.env.example build/setup.sh` (identical scheme) |
| G5 — `VCRM.md` BR-20 confirmed at 142 | `VCRM.md` line 64, matches Tier S expected JSON |

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
