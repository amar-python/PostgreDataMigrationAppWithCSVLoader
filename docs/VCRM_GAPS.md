# VCRM Gap Analysis — uncovered & partially-covered requirements

Companion to `docs/VCRM.md`. Lists only the 5 business requirements that are **not fully verified** by an automated test condition, with risk assessment, recommended remediation, and effort/priority. The remaining 17 of 22 requirements are fully covered and not repeated here.

> **Verification methods** (from MIL-STD / IEEE 1012): **T**est, **A**nalysis, **I**nspection, **D**emonstration. The recommendations below pick the cheapest method that gives a real signal.

---

## Executive summary

**Status as at 2026-09-10.** Three of the five gaps below have been closed or
substantially narrowed since this document was first written. The per-gap sections
are kept rather than deleted, each headed with its current status and the evidence
that changed it, so the traceability history stays readable.

| Category | Count | Requirement IDs |
|----------|-------|-----------------|
| ✅ **Resolved** — automated coverage now exists | 2 | BR-01, BR-15 |
| ⏸ **Deferred by decision** — out of scope by recorded project decision | 3 | BR-02, BR-21, BR-22 |
| ❌ **Actionable gap** — no coverage and no decision | **0** | — |
| **Total not fully verified** | **3 of 22** (14 %) | all deferred |

**Coverage from the VCRM:** 19 of 22 (86 %) requirements fully verified by ≥ 1
automated test condition, up from 17 of 22 (77 %).

### What changed

| Requirement | Was | Now | Evidence |
|---|---|---|---|
| **BR-15** conn_limit | No coverage | ✅ Resolved | Assertion **S10** in `tests/suites/test_05_schema_and_business_rules.sql` reads `pg_roles.rolconnlimit` and compares it against the env's `conn_limit`, forwarded via `set_config('te.conn_limit')`. A typo such as `conn_limit=5` in `env_prod.sql` now fails the suite. |
| **BR-01** env isolation | ⚠️ Partial | ✅ Resolved | **Tier E scenario 01** `01_envs_have_identical_structure` compares all four deployed schemas column by column. Logic unit-tested in `tests/test_evals_tier_e_x.py` with negative controls. |
| **BR-02** six engines | ❌ Not verified | ⏸ Deferred by decision | **Tier X scenario 01** `01_sqlite_schema_structure` executes and pins the SQLite schema, and measured a shortfall nobody had counted before. On that evidence a decision was taken to reach a PostgreSQL milestone first — [ADR-0001](adr/0001-postgresql-first.md). Tier X remains in the repo but is out of CI. |

### BR-02 — deferred by decision (settled 2026-09-10)

Building Tier X measured what each engine actually defines:

| Engine | Tables defined | Against PostgreSQL's 12 |
|---|---|---|
| postgresql | 12 | reference |
| sqlite | 7 | 5 missing |
| mariadb | 7 | 5 missing |
| teradata | 1 | 11 missing |
| influxdb | no DDL (seed `.lp` only) | n/a |
| redis | no DDL (seed `.sh` only) | n/a |

The five absent from SQLite and MariaDB — `temp_documents`, `test_phases`,
`test_events`, `test_results`, `evidence_artifacts` — are the execution and
evidence half of the model. Those engines can hold a test plan and its
traceability but not a record of test execution.

**Decision taken:** pursue PostgreSQL to a working milestone first, then apply
what that teaches to the other engines. Recorded in
[ADR-0001](adr/0001-postgresql-first.md) with the full rationale, the alternatives
rejected, the accepted risk, and four revisit triggers.

BR-02's wording in `docs/VCRM.md` is **retained unchanged** and annotated as
deferred: it states the eventual target, not the current milestone. Its VCRM
status moved from ❌ Not verified to ⏸ Deferred by decision — which is a
different thing, and the distinction is the point. An unverified requirement is a
gap; a deferred one is a choice with a trigger to revisit.

### Remaining actionable work

**No requirement-level work outstanding.** All three not-fully-verified
requirements — BR-02, BR-21, BR-22 — are deferred by recorded decision.

Two items sit outside the BR set:

1. **Frontend** — see "Coverage note — frontend" at the end of this document. Not
   covered by any BR.
2. **G2** in `docs/GAP_ANALYSIS.md` — Windows CI cannot host PostgreSQL. Accepted;
   the ubuntu `integration-postgres` job carries the database-backed suite.

---

## Gap 1 — BR-01 (✅ RESOLVED 2026-09-10)

> **Closed by Tier E scenario 01** `01_envs_have_identical_structure`. The
> "What's NOT verified" section below is retained as the historical record of
> why the scenario was written; it no longer describes current state. The
> recommended implementation outline further down is what was built.

### Requirement

> The framework shall deploy isolated **Dev / Test / Staging / Prod** environments on a single PostgreSQL instance, each with its own database, schema, app user, and connection limit.

### What's already verified

- The deploy machinery for the Dev environment is exercised by **Tier I scenario 01** and **Tier S scenario 01**.
- Schema is parameterised correctly via `\set` (verified by **SQL suite 05** asserting that the chosen `:"schema_name"` and `:"tbl_*"` identifiers resolve).

### What's NOT verified

- **Test, Staging, and Prod environments are deployable but their structural equivalence to Dev is not asserted.** A change to `env_test.sql` that drifts from `env_dev.sql` would not be caught by any test.
- The four environment-specific `\set` blocks (database name, schema name, app user) are not validated as being the only allowed difference.

### Risk if unaddressed

| Scenario | Likelihood | Impact |
|----------|-----------|--------|
| `env_staging.sql` is edited and accidentally introduces a column or constraint not present in Dev | Medium | High — Prod release goes out with schema drift; production tests start failing on real data |
| An environment-specific `\set` value is mistyped (e.g. `schema_name` set to a value the DDL doesn't reference) | Medium | Medium — silent partial deployment |

### Recommended verification

**Method:** Test (T). Add a new **Tier E** scenario: `01_envs_have_identical_structure`.

**Implementation outline:**

1. Create `evals/datasets/tier_e/01_envs_have_identical_structure/NOTES.md`.
2. Create `evals/expected/tier_e/01_envs_have_identical_structure.json` declaring:

   ```json
   {
     "envs_under_test": ["dev", "test", "staging", "prod"],
     "expected": {
       "all_envs_deploy_exit_zero": true,
       "column_signature_identical_across_envs": true,
       "only_identifier_namespaces_differ": true
     }
   }
   ```

3. Add a runner branch `_run_envs_have_identical_structure` that:
   - Deploys all 4 envs (or skips if PG unavailable).
   - For each env, queries `information_schema.columns` filtered to its schema.
   - Normalises the result by stripping the schema name and computing a hash per table.
   - Asserts all 4 hashes match table-by-table.

### Effort & priority

| Effort | Priority | Owner |
|--------|----------|-------|
| ~1 day | **Medium** — addresses a documented requirement, but Dev is the only env you currently exercise | Test Lead / DBA pair |

---

## Gap 2 — BR-02 (⏸ DEFERRED BY DECISION 2026-09-10)

> **Measured by Tier X scenario 01** `01_sqlite_schema_structure`, then
> **deferred by [ADR-0001](adr/0001-postgresql-first.md)**: PostgreSQL first, with
> the lessons applied to other engines afterwards.
>
> The recommendation below — Tier X scenarios per engine, cheapest first — remains
> the right approach for when this resumes, and scenario 01 for SQLite is already
> built. It is simply not scheduled. Tier X stays in the repository but is out of
> CI; run it with `make evals-engines`.

### Requirement

> The framework shall support **six database engines** — PostgreSQL, MariaDB, SQLite, InfluxDB, Redis, Teradata — through adapter scripts.

### What's already verified

- Adapter scripts exist at `build/adapters/adapter_<engine>.sh` for all six engines.
- Engine-specific DDL exists at `build/schema/<engine>/`.
- PostgreSQL is fully verified (Tier S asserts `142/142 PASS` post-deploy).

### What's NOT verified

- **No test runs any adapter besides PostgreSQL.** MariaDB, SQLite, InfluxDB, Redis, and Teradata adapters are documented as supported but have zero automated coverage.
- A breaking change to the MariaDB DDL would not be detected.

### Risk if unaddressed

| Scenario | Likelihood | Impact |
|----------|-----------|--------|
| A user follows the README, chooses MariaDB via `setup.sh`, and the adapter fails on first run | High (if anyone tries it) | High — first-run failure for the user, reputational risk for the framework |
| Schema drift between PG and MariaDB introduces semantically different tables | High over time | Medium — multi-engine claim becomes false |

### Recommended verification

**Method:** Test (T). Add **Tier X** (cross-DB equivalence) scenarios incrementally, in order of cheapness:

| Order | Engine | Why first | Setup cost |
|-------|--------|-----------|-----------|
| 1 | **SQLite** | Embedded — no service to run | Zero — file-based |
| 2 | **MariaDB** | Wire-compatible with MySQL; docker container available | ~10 min — `docker run mariadb` |
| 3 | **InfluxDB** | Time-series — fundamentally different model, may need separate eval shape | Medium |
| 4 | **Redis** | Key-value — same caveat | Medium |
| 5 | **Teradata** | Requires Vantage Express VM | High — possibly only verify in pre-release |

**Per-engine scenario template:** for each engine, scenario `tier_x/0X_<engine>_fresh_deploy/`:

1. Deploy via the engine's adapter.
2. Query the engine's information schema (or equivalent — `sqlite_master`, `INFORMATION_SCHEMA.COLUMNS` for MariaDB, etc.).
3. Compare structural signature against the PostgreSQL reference.
4. For Influx/Redis where structure doesn't translate, assert that the seed data lands in the expected key namespaces / measurement names.

### Effort & priority

| Effort | Priority | Owner |
|--------|----------|-------|
| ~1 day per relational engine (SQLite + MariaDB); 2-3 days each for the NoSQL engines | **Low-Medium** — depends on whether multi-DB is a near-term commitment. The project README's evals package explicitly states "PostgreSQL only" for now. | Backend / DBA |

---

## Gap 3 — BR-15 (✅ RESOLVED)

> **Closed by assertion S10** in
> `tests/suites/test_05_schema_and_business_rules.sql`, which reads
> `pg_roles.rolconnlimit` and compares it against the environment's
> `conn_limit`. Implemented as the "even cheaper alternative" sketched below.

### Requirement

> Each environment shall enforce a **connection limit** appropriate to its workload: Dev=10, Test=15, Staging=20, Prod=50.

### What's already verified

- The `\set conn_limit` value is set per env in the respective `build/environments/env_<env>.sql` files.

### What's NOT verified

- **No test confirms PostgreSQL actually applies the configured connection limit to the role.** A typo in `env_prod.sql` setting `conn_limit` to `5` instead of `50` would pass all current tests.

### Risk if unaddressed

| Scenario | Likelihood | Impact |
|----------|-----------|--------|
| Production rolconnlimit is silently wrong; users hit unexpected `too many connections` errors | Low-Medium | High — production incident, slow to diagnose |

### Recommended verification

**Method:** Test (T). Add 4 assertions to `tests/suites/test_05_schema_and_business_rules.sql` — one per environment.

```sql
-- Conceptual SQL (each env asserts its own expected value)
PERFORM :"schema_name".assert_equals(
    'schema_business_rules',
    'conn_limit_dev',
    10::int,
    (SELECT rolconnlimit FROM pg_roles WHERE rolname = :'app_user')
);
```

Since the SQL test suite is invoked once per environment by `tests/run_tests.sh`, each invocation will pick up the env-specific `:'app_user'` and `conn_limit` via `\set`.

**Even cheaper alternative** — verify once via Tier I extension: in `_run_deploy_dev_twice` (or a new sibling), after the second deploy, query `pg_roles` and assert `rolconnlimit = 10` for `te_dev_user`.

### Effort & priority

| Effort | Priority | Owner |
|--------|----------|-------|
| **~1 hour** | **High** — cheapest gap to close. No dependencies. Catches a real production failure mode. | Anyone |

---

## Gap 4 — BR-21 (❌ Deferred by design)

### Requirement

> Cross-engine schema equivalence verification — MariaDB / SQLite / Teradata structurally equivalent to PostgreSQL.

### Decision

- **Status:** Deferred. Recorded in `evals/FAILURE_MODES.md` "What this catalogue does NOT yet cover" and in `evals/HANDOFF.md` "What's deferred to a later round".
- **Rationale:** "Deferred until PG is locked in" — the team explicitly chose to stabilise the PostgreSQL eval suite before expanding the matrix.
- **Owner of the decision:** Recorded as project-level scope decision.

### When to revisit

When at least one non-PG engine becomes a delivery commitment to a real customer. Tracking criteria:

- Has anyone deployed via `setup.sh --engine mariadb` in production? → If yes, BR-21 is overdue.
- Has the README's "Six DB engines" claim been challenged in a code review? → If yes, time to test.

### Effort if revived

This is essentially **BR-02 + a diff engine**. See Gap 2.

---

## Gap 5 — BR-22 (❌ Deferred by design)

### Requirement

> Performance at scale — the framework shall ingest ≥ 1 M rows within a defined time budget.

### Decision

- **Status:** Deferred. Recorded in `evals/HANDOFF.md`: *"Would need a fixture generator — separate round."*
- **Rationale:** No performance SLO has been agreed; defining one without a stakeholder is premature.

### When to revisit

When any of the following happen:

- A stakeholder cites a row-count target (e.g. "we need to load the 2.3 M-row payroll snapshot in under 10 minutes").
- A production user reports a slow load.
- A budget for performance test infrastructure becomes available.

### Effort if revived

| Activity | Effort |
|----------|--------|
| Build a CSV fixture generator (1 K → 10 K → 100 K → 1 M → 10 M rows) | 1-2 days |
| Add a perf tier to `evals/runner.py` that measures load wall-clock and emits structured timing | 1 day |
| Define and codify a performance SLO (rows/sec, p95 wall-clock) | 0.5 day with stakeholder |
| Total | ~4 days |

---

## Remediation roadmap

If you wanted to close all three actionable gaps in one mini-sprint, the sequence and total cost are:

```text
Day 0.1  BR-15: add 4 conn_limit assertions to tests/suites/test_05_*.sql      (~1 hour)
Day 1    BR-01: scaffold Tier E + 01_envs_have_identical_structure scenario   (~1 day)
Day 2    BR-02: scaffold Tier X + 01_sqlite_fresh_deploy scenario              (~1 day)
Day 3    BR-02: 02_mariadb_fresh_deploy                                         (~1 day)
```

Result: VCRM coverage moves from **77 % → 91 %** (BR-15, BR-01, and 2/5 engines of BR-02 closed; BR-21 and BR-22 still deferred by design).

Closing the remaining 3 engines of BR-02 (Influx, Redis, Teradata) would take another ~6-9 days because of the heavier setup and the conceptual gap (NoSQL doesn't translate structurally — those assertions need a different shape).

---

## Decision log

| Date | Decision | Recorded in | Owner |
|------|----------|------------|-------|
| 2026-05-26 | Defer Tier X (cross-DB equivalence) | `evals/PLAN.md` | Project team |
| 2026-05-26 | Defer Tier E (cross-environment parity) | `evals/HANDOFF.md` | Project team |
| 2026-05-26 | Defer performance suite | `evals/HANDOFF.md` | Project team |
| 2026-06-01 | BR-15 (conn_limit verification) flagged as cheap actionable gap | this file | (pending) |
| 2026-06-01 | BR-01 (cross-env structural parity) flagged as medium-priority gap | this file | (pending) |
| 2026-09-10 | BR-15 resolved — assertion S10 added to SQL suite 05 | `docs/VCRM.md`, `docs/RECONCILED_GAPS.md` | Amarnath |
| 2026-09-10 | BR-01 resolved — Tier E scenario 01 built | `docs/VCRM.md`, `docs/RECONCILED_GAPS.md` | Amarnath |
| 2026-09-10 | **BR-02 deferred by decision — PostgreSQL first, multi-engine after the PG milestone** | [`docs/adr/0001-postgresql-first.md`](adr/0001-postgresql-first.md) | Amarnath |
| 2026-09-10 | Tier X retained in repo but removed from CI, per the decision above | `.github/workflows/*`, `Makefile` (`evals-engines`) | Amarnath |

Append to this log whenever a gap is accepted as risk, scheduled for verification, or marked won't-fix.

---

## Coverage note — frontend (not a BR, recorded for completeness)

`csv-table-hub-main/` has **not been independently audited** and no BR covers it.
Two specific risks follow from that, both recorded rather than measured:

- **CSV parser parity.** The frontend parses CSV in TypeScript; the backend path
  uses `build/csv/validator.py` (shell/eval-covered) and `api/services/csv_parse.py`
  (API path). Nothing asserts the implementations agree on delimiter detection,
  quoted fields with embedded newlines, BOM handling, or type inference. A file
  the browser previews as valid could be rejected server-side, or worse, loaded
  with different column typing than the preview showed.
- **CORS wiring end to end.** `settings.CORS_ORIGINS` is env-driven and the
  allowed methods and headers are pinned in `api/main.py`, but no test drives a
  real browser preflight against a running API.

Cheapest useful coverage would be a shared fixture set: a directory of CSV files
with one expected-parse JSON each, asserted by both a TypeScript test and a Python
test. That turns parity from an assumption into a check without merging the two
parsers.

---

*Companion documents:*

- `docs/VCRM.md` — full Verification Cross Reference Matrix (all 22 requirements)
- `docs/TEST_CONDITIONS.md` — every test condition catalogued in detail
- `docs/ARCHITECTURE.md` — the three-layer model (build / tests / evals)
- `evals/FAILURE_MODES.md` — failure-mode catalogue at the eval layer
- `evals/HANDOFF.md` — deferred-items log for the eval pa
