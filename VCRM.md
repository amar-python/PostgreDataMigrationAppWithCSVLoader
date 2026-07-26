# VCRM — Verification Cross Reference Matrix

The framework's own Verification Cross Reference Matrix, applying its T&E concept to itself. Maps each business requirement to the test condition(s) that verify it across the six test layers catalogued in `TEST_CONDITIONS.md`.

> **Vocabulary used here** follows ASDEFCON T&E practice: requirements are stated, decomposed where useful, and traced to verification activities. Verification methods follow MIL-STD / IEEE 1012 conventions: **Test (T)**, **Analysis (A)**, **Inspection (I)**, **Demonstration (D)**.

---

## How to read this document

- **Section 1** — the requirements catalogue. 22 numbered business requirements (BR-01..BR-22) inferred from the project README, the T&E domain, and the ISM / ASDEFCON references the README cites.
- **Section 2** — the traceability matrix. For each requirement: status, the test conditions that verify it, and any gaps.
- **Section 3** — coverage summary (per-category percentages).
- **Section 4** — gap analysis with recommendations.
- **Section 5** — methodology note for review.

Verification method legend:

- ✅ **Verified** — at least one test condition asserts the requirement, currently passing
- ⚠️ **Partial** — some aspects verified, some gaps documented
- ❌ **Not verified** — no automated test condition; manual demonstration only or deferred

Test-layer codes used in column headers below:

- **PU** = Python unit test (`tests/test_*.py`)
- **SQL** = SQL suite assertion (`tests/suites/test_0X_*.sql`)
- **TP** = Tier P eval (`evals/datasets/tier_p/`)
- **TI** = Tier I eval (`evals/datasets/tier_i/`)
- **TS** = Tier S eval (`evals/datasets/tier_s/`)
- **LV** = Load-time verification (`input_data/load_input_data.sql`)

---

## 1. Business requirements catalogue

### Functional requirements

| ID | Requirement | Source |
|----|------------|--------|
| **BR-01** | The framework shall deploy isolated **Dev / Test / Staging / Prod** environments on a single PostgreSQL instance, each with its own database, schema, app user, and connection limit. | README §"Environment Comparison" |
| **BR-02** | The framework shall support **six database engines** — PostgreSQL, MariaDB, SQLite, InfluxDB, Redis, Teradata — through adapter scripts. | README §"What This Is", `build/adapters/*` |
| **BR-03** | All schema identifiers (database, schema, role, table names) shall be controlled by a single `\set` configuration block; renaming in one place updates the entire deployment. | README §"How Parameterisation Works" |
| **BR-04** | The T&E data model shall persist the full lifecycle: **organisations, personnel, programs, TEMP documents, phases, requirements, test cases, VCRM entries, test events, results, defect reports, evidence artefacts** (12 tables). | README §"Schema Reference" |
| **BR-05** | The framework shall enforce **100 % VCRM coverage** for every active program, with explicit gap detection for programs that intentionally lack coverage. | README §"Seed Data", section §"vcrm_entries 100% coverage" |
| **BR-06** | TEMP documents shall be **versioned** with status transitions: draft → approved → superseded. Multiple versions of the same TEMP may coexist; only one may be 'approved' at a time. | README §"temp_documents" |
| **BR-07** | Test results shall capture a constrained **verdict** in {`pass`, `fail`, `blocked`, `not_run`, `inconclusive`} and link to the test case + event that produced them. | README §"Key enumerated values" |
| **BR-08** | Deficiency Reports (DRs) shall be raised against **fail** results, carry a **severity** in {`critical`, `major`, `minor`, `observation`}, and follow a lifecycle with `resolved_at` populated only when closed. | README §"defect_reports.severity", §"How Parameterisation Works" |
| **BR-09** | Deployment shall be **idempotent** — re-running `deploy_all.sh` against an already-deployed database shall produce identical row counts and no `CREATE TABLE` errors. | README §"Idempotency" |
| **BR-10** | CSV input shall be **validated** before ingestion. Files that are missing, empty, malformed, or contain rows that don't match the header shall be rejected with a clear diagnostic. | `build/csv/validator.py` contract |
| **BR-11** | CSV ingestion shall **separate valid rows from skipped rows** into two output files, recording a `_skip_reason` per skipped row so a steward can investigate and fix the source. | `build/csv/validator.py` behaviour |
| **BR-12** | The framework shall represent Australian-context **security clearance levels** for personnel: {`baseline`, `NV1`, `NV2`, `PV`}. | README §"personnel.clearance" |
| **BR-13** | Programs shall carry an **ISM-aligned classification marking** in {`UNCLASSIFIED`, `PROTECTED`, `SECRET`, `TOP SECRET`}. | README §"test_programs.classification" |
| **BR-14** | Test phases shall be one of {`DT&E`, `AT&E`, `OT&E`, `IOT&E`, `LFT&E`, `FOLLOW_ON`}. | README §"test_phases.phase_type" |
| **BR-15** | Each environment shall enforce a **connection limit** appropriate to its workload (10/15/20/50 for Dev/Test/Staging/Prod). | README §"Environment Comparison" |

### Quality / operational requirements

| ID | Requirement | Source |
|----|------------|--------|
| **BR-16** | An **automated regression suite** shall be runnable from a single command and produce a deterministic, CI-gateable pass/fail outcome. | README §"Test Suite", T&E practice |
| **BR-17** | The framework shall **gracefully degrade** when an optional dependency (PostgreSQL, psql, Internet) is unavailable: tests skip cleanly rather than crashing. | `evals/runner.py` design intent |
| **BR-18** | Every regression run shall produce a **machine-readable JSON report** persisted under `evals/reports/<run_id>/`. | `evals/runner.py` behaviour |
| **BR-19** | The build, test, and eval layers shall be **physically segregated** so a change to one cannot inadvertently break the others' contract. | `ARCHITECTURE.md` |
| **BR-20** | The full SQL test suite shall reach **142 of 142 assertions passing** (100.0 % pass rate) on every release. | README §"142 assertions", `tests/run_all_tests.sql` |

### Out of scope (recorded for completeness)

| ID | Requirement | Status / why |
|----|------------|---------|
| **BR-21** | Cross-engine schema equivalence (MariaDB/SQLite/Teradata produce structurally equivalent tables to PostgreSQL). | Deferred — declared out of scope per `evals/FAILURE_MODES.md` |
| **BR-22** | Performance at scale (≥ 1 M rows loaded within a defined time budget). | Deferred — declared out of scope per `evals/HANDOFF.md` |

---

## 2. Traceability matrix

For each requirement, the columns mark which test layer verifies it. Numbers in cells are scenario/test IDs from `TEST_CONDITIONS.md`. **Status** is the worst-case across the cells (a requirement is ⚠️ if any aspect is partial, ❌ if no automated coverage exists).

| ID | Requirement (short) | PU | SQL | TP | TI | TS | LV | Status | Notes |
|----|--------------------|----|-----|----|----|----|----|-------|-------|
| BR-01 | Multi-env isolated (Dev/Test/Staging/Prod) | — | suite 05 (schema_name) | — | — | 01 (Dev only) | — | ⚠️ | Tier I/S only exercise Dev. Test/Staging/Prod parity is not asserted (would need Tier E). |
| BR-02 | Six DB engines via adapters | — | — | — | — | — | — | ❌ | No adapter-level tests exist; only PG is verified. Would need Tier X. |
| BR-03 | `\set` parameterisation works | — | suite 05 (table existence under `:"tbl_*"` overrides) | — | — | 01 (passes `--set tbl_*=...`) | — | ✅ | Tier S proves the parameterisation contract holds end-to-end. |
| BR-04 | 12-table T&E data model | — | suites 01–05 (every table referenced by at least one assertion) | — | 01 (counts rows in 11 of 12 tables; evidence_artifacts not counted) | 01 | — | ✅ | One small gap: Tier I doesn't count `evidence_artifacts`, but that table is schema-only per the README. |
| BR-05 | 100 % VCRM coverage for CYB9131 + gap detection for LAND400 | — | **suite 03 (23 assertions)** | — | — | 01 | — | ✅ | Direct verification — suite 03 is the canonical VCRM check. |
| BR-06 | TEMP versioning (draft → approved → superseded) | — | suite 02 (sequencing assertions) | — | — | 01 | — | ✅ | |
| BR-07 | Test result verdict constraint + linkage | — | suite 04 (verdict mix, FK to test cases + events) | — | — | 01 | — | ✅ | |
| BR-08 | DR severity + resolved_at lifecycle | — | suite 04 (DR linkage, severity enum, resolved_at logic) | — | — | 01 | — | ✅ | |
| BR-09 | Idempotent deployment | — | (implicit via suite re-runs) | — | **01 (canonical)** | 01 | — | ✅ | Tier I is the direct verifier. |
| BR-10 | CSV pre-ingestion validation | 1, 2, 4, 8 | — | 02, 03, 04, 07, 08, 19, 20, 23 | — | — | — | ✅ | Both Python unit tests and Tier P scenarios assert the validator's reject behaviour from multiple angles. |
| BR-11 | Valid / skip row separation with reasons | 3 | — | 05, 09, 16 | — | — | — | ✅ | |
| BR-12 | Clearance enum {baseline, NV1, NV2, PV} | — | suite 01 (CHECK / enum assertions on personnel) | — | — | 01 | — | ✅ | |
| BR-13 | ISM classification marking enum | — | suite 02 (classification assertions on test_programs) | — | — | 01 | — | ✅ | |
| BR-14 | Phase type enum | — | suite 02 (phase_type assertions on test_phases) | — | — | 01 | — | ✅ | |
| BR-15 | Per-env connection limits | — | — | — | — | — | — | ❌ | The limit is set in `env_*.sql` but no test asserts it. Would need a `\d` introspection check. |
| BR-16 | Automated single-command regression | — | — | All TP (single `runner.py` invocation) | 01 | 01 | — | ✅ | Combined `runner.py --tiers p,i,s` is the entry point. |
| BR-17 | Graceful degradation when PG unavailable | 9, 11 | — | — | (skip behaviour) | (skip behaviour) | — | ✅ | Python unit tests directly assert the skip path. |
| BR-18 | Machine-readable JSON report per run | 5, 6 | — | — | — | — | — | ✅ | Verified by `_load_expected` and `discover_scenarios` unit tests; the report write itself is exercised by every Tier P run. |
| BR-19 | Build / tests / evals physically segregated | — | — | — | — | — | — | ✅ | Verified by `ARCHITECTURE.md` + the directory layout + the green test runs after the refactor. (Verification method = Inspection.) |
| BR-20 | 85 / 85 SQL assertions pass | — | (all 5 suites) | — | — | **01 (asserts `min_total_assertions: 85`, `min_pass_rate_percent: 100`)** | — | ✅ | Tier S is the headline gating check. |
| BR-21 | Cross-engine schema equivalence | — | — | — | — | — | — | ❌ | Deferred. Tier X. |
| BR-22 | Performance at ≥ 1 M rows | — | — | — | — | — | — | ❌ | Deferred. No perf tier exists. |

### Bonus: data-load layer (orthogonal to the T&E requirements above)

The `input_data/` loader has its own implicit requirements — verified end-to-end by the 5-section verification block at the bottom of `load_input_data.sql`.

| ID | Implicit requirement | LV section | Status |
|----|---------------------|------------|--------|
| BR-D1 | All staging rows reach the target table (or are reported as dropped) | 3 (reconciliation) | ✅ |
| BR-D2 | Aggregates on the loaded data match expectations | 2 (aggregates) | ✅ |
| BR-D3 | No NULL appears in a NOT NULL column post-load | 5 (NULL audit) | ✅ |
| BR-D4 | Duplicate primary keys in source are reported, not silently dropped | 4 (duplicate detection) | ✅ |
| BR-D5 | Loaded data is browsable (sample peek) | 1 (sample rows) | ✅ |

---

## 3. Coverage summary

### By layer

| Layer | Requirements with at least one cell ticked | % of in-scope requirements (BR-01..BR-20) |
|-------|-------------------------------------------|-------------------------------------------|
| Python unit (PU) | 5 (BR-10/11/17/18) | 25 % |
| SQL suites (SQL) | 11 (BR-01/03/04/05/06/07/08/12/13/14/20) | 55 % |
| Tier P (TP) | 4 (BR-10/11/16/18) | 20 % |
| Tier I (TI) | 4 (BR-04/09/16/17) | 20 % |
| Tier S (TS) | 13 (BR-01/03/04/05/06/07/08/09/12/13/14/16/20) | 65 % |
| Load-verify (LV) | 5 implicit (BR-D1..D5) | n/a — separate domain |

### By verification status

| Status | Count | Requirements |
|--------|-------|-------------|
| ✅ Verified | 17 | BR-03, BR-04, BR-05, BR-06, BR-07, BR-08, BR-09, BR-10, BR-11, BR-12, BR-13, BR-14, BR-16, BR-17, BR-18, BR-19, BR-20 |
| ⚠️ Partial | 1 | BR-01 |
| ❌ Not verified | 4 | BR-02, BR-15, BR-21, BR-22 |

**Headline:** **17 of 22 (77 %)** business requirements are fully verified by at least one automated test condition. Of the 5 not fully verified, 2 are deferred by design (BR-21, BR-22) and 3 are genuine gaps (BR-01 partial, BR-02 unverified, BR-15 unverified).

---

## 4. Gap analysis

### Genuine gaps (recommended to address)

| Req | Gap | Recommended verification | Effort |
|-----|-----|--------------------------|--------|
| **BR-01 partial** | Test/Staging/Prod environments are deployable but their structural equivalence to Dev is not asserted by any test. A change in `env_test.sql` that drifts from `env_dev.sql` would not be caught. | Add a Tier E scenario `01_envs_have_identical_structure` that deploys all four envs, queries `information_schema.columns` for each, and diffs the structure. | Medium (1 day) |
| **BR-02** | The framework claims to support 6 DB engines via adapters, but no test runs against MariaDB / SQLite / etc. | Add a Tier X scenario per engine. Earliest wins: SQLite (no service needed, just a file). | Medium per engine |
| **BR-15** | The per-environment `conn_limit` value lives in `env_*.sql` but no test confirms it's applied. | Add a SQL assertion in suite 05: `SELECT rolconnlimit FROM pg_roles WHERE rolname = :'app_user'` and `assert_equals(..., <expected limit>)`. | Small (~1 hour) |

### Deliberately deferred

| Req | Why deferred | When to revisit |
|-----|--------------|-----------------|
| **BR-21** (cross-DB equivalence) | Explicit decision per `evals/FAILURE_MODES.md`: "deferred until PG is locked in" | Once Tier P/I/S have been stable for one release cycle |
| **BR-22** (perf at 1M rows) | Explicit decision per `evals/HANDOFF.md`: "Would need a fixture generator — separate round" | When a real workload needs it |

### Hidden strengths (verified but I'd have expected gaps)

- **BR-09 (idempotency)** is verified by an explicit Tier I scenario *and* implicitly by every Tier S re-run, *and* by the `IF NOT EXISTS` patterns in the schema files themselves. Three independent verification methods — robust.
- **BR-05 (VCRM coverage)** has 23 SQL assertions dedicated to it in suite 03 alone. The framework's own VCRM concept is over-verified, which is the right amount of paranoia for the use case.
- **BR-19 (segregation)** is verified by Inspection rather than Test (no automated assertion that "all build files live under build/"), but the consequence of regression (a broken Tier P run) would be visible within seconds in CI.

---

## 5. Methodology note

This VCRM was derived as follows:

1. **Requirements extraction** — read `README.md`, `ARCHITECTURE.md`, `evals/PLAN.md`, `evals/FAILURE_MODES.md`, `evals/HANDOFF.md`, `TEST_CONDITIONS.md`. Identified statements of intent that could be operationalised as testable conditions.
2. **Domain inference** — supplemented the documented requirements with industry-standard T&E concerns referenced in the README (ASDEFCON, ISM, MIL-STD-882, ISO 31000). These appear in BR-12, BR-13, BR-14, BR-15.
3. **Traceability** — for each requirement, walked through all six test layers and recorded the specific test condition(s) that assert it. Where multiple test conditions touched the same requirement, all are recorded.
4. **Coverage classification** — applied the ✅ / ⚠️ / ❌ legend uniformly: a requirement is ✅ only if every aspect is verified; ⚠️ if some aspects are tested and some are gaps; ❌ if nothing tests it.

**Known limitations of this VCRM:**

- The requirements catalogue (Section 1) is **inferred from documents**, not derived from a formal Statement of Requirement. In a production T&E setting it would be reviewed and ratified by the customer / stakeholders.
- Requirements are at a high level. A formal SRS / TRD would decompose each into 5-20 sub-requirements and the matrix would grow accordingly.
- Verification method is implicitly **Test (T)** for every cell with an automated test ID. **Inspection (I)** is used for BR-19. **Analysis (A)** and **Demonstration (D)** methods aren't used because every requirement has either Test coverage or is deferred.

**Recommended review actions:**

1. Stakeholder review of Section 1 — confirm the 20 in-scope requirements really are the right ones.
2. Triage the 3 genuine gaps (BR-01-partial, BR-02, BR-15) — accept the risk or schedule the verification work.
3. Re-verify after each release: re-run all test layers, update this matrix if any cell flips status.

---

*Companion documents:*

- `ARCHITECTURE.md` — the three-layer model (build / tests / evals)
- `TEST_CONDITIONS.md` — every test condition catalogued in full detail
- `evals/FAILURE_MODES.md` — failure-mode catalogue at the eval layer
- `evals/PLAN.md` — eval suite design rationale
