# VCRM — Verification Cross Reference Matrix

The framework's own Verification Cross Reference Matrix, applying its T&E concept to itself. Maps each business requirement to the test condition(s) that verify it across the six test layers catalogued in `docs/TEST_CONDITIONS.md`.

> **Single source of truth (2026-11-19):** this file is the master traceability record. `docs/VCRM_GAPS.md` and `docs/RECONCILED_GAPS.md` are superseded by it and kept only as history.
>
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
- **LV** = Load-time verification (`input_data/load_input_data.sql`). *That file is not in the repository, so nothing in this column can be re-run (erratum E-08, §6.5).*

---

## 1. Business requirements catalogue

### Functional requirements

| ID | Requirement | Source |
|----|------------|--------|
| **BR-01** | The framework shall deploy isolated **Dev / Test / Staging / Prod** environments on a single PostgreSQL instance, each with its own database, schema, app user, and connection limit. | README §"Environment Comparison" |
| **BR-02** | The framework shall support **six database engines** — PostgreSQL, MariaDB, SQLite, InfluxDB, Redis, Teradata — through adapter scripts. **⏸ Deferred by decision 2026-09-10** — PostgreSQL first; see [ADR-0001](adr/0001-postgresql-first.md). Requirement wording retained unchanged; it states the eventual target, not the current milestone. Per-engine measured state in [`ENGINE_PARITY_TODO.md`](ENGINE_PARITY_TODO.md). | README §"What This Is", `build/adapters/*` |
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
| **BR-19** | The build, test, and eval layers shall be **physically segregated** so a change to one cannot inadvertently break the others' contract. | `docs/ARCHITECTURE.md` |
| **BR-20** | The full SQL test suite shall reach **159 of 159 assertions passing** (100.0 % pass rate) on every release. *(Count changed from 142 on 2026-11-24, erratum E-05, §6.5; the suite has had 159 since suite 06 was added.)* | README §"159-assertion SQL test suite", `tests/run_all_tests.sql` |

### ART extension requirements (added 2026-10-26)

Added by ART Milestone 0 (#53) and approved by the product owner on 2026-10-26. Source: [`docs/art/milestone-0-assessment.md`](art/milestone-0-assessment.md), [ADR-0002](adr/0002-transactional-staged-import.md), [ADR-0003](adr/0003-customer-facing-multi-tenant.md), [`DECISIONS/2026-10-26-art-milestone-0.md`](../DECISIONS/2026-10-26-art-milestone-0.md).

| ID | Requirement | Source |
|----|------------|--------|
| **BR-23** | Every upload shall be registered with a unique ID, original filename, SHA-256, uploader, tenant, timestamp and processing status. | ART v2 |
| **BR-24** | The original file and its parsed source rows shall be preserved immutably, separate from edits and approved data. | ART v2, D2 |
| **BR-25** | Users shall be able to page through every row and column of an upload, with inferred types and validation results. | ART v2 |
| **BR-26** | Rows shall be includable or excludable; each decision records actor and reason. | ART v2 |
| **BR-27** | Cell edits shall be stored as versions over the original, with old and new value, actor, time and reason. | ART v2, D2 |
| **BR-28** | Exact-file duplicates shall be detected by SHA-256 within and across uploads, per tenant. | ART v2 |
| **BR-29** | Duplicate records shall be detected within and across uploads using a configurable rule (default: exact match, flagged). | ART v2, decision 3 |
| **BR-30** | Table names shall be safely derived from filenames, and repeated uploads of a filename create versioned datasets without overwriting. | ART v2, decision 2 |
| **BR-31** | Imports shall check schema compatibility and never make destructive schema changes. | ART v2 |
| **BR-32** | Imports shall require submission and an approve or reject decision with a recorded approver; by default an uploader cannot approve their own data. | ART v2, D3, decision 5 |
| **BR-33** | Imports shall be staged, transactional and idempotent with safe retries; every imported row traces to its source row and approved version; partial imports are not permitted. | ART v2, D4, ADR-0002, decision 4 |
| **BR-34** | Rows in, excluded, edited and imported shall reconcile exactly and be persisted per import. | ART v2 |
| **BR-35** | Audit events shall be append-only at database level; reports shall be filterable; exports shall neutralise spreadsheet formula injection. | ART v2, D7 |
| **BR-36** | Users shall authenticate; access shall be role-based; no tenant shall read or affect another tenant's data. | ART v2, D1, ADR-0003, decision 6 |
| **BR-37** | Data shall stay inside the deployment boundary, with no runtime external services, and the stack shall install offline. | ART v2, D6, decision 7 |
| **BR-38** | The platform shall install and run without internet access on Windows, macOS and Linux hosts that have a container runtime (Docker or Podman) installed. | Product owner, 27 Oct 2026; #128 |

### Out of scope (recorded for completeness)

| ID | Requirement | Status / why |
|----|------------|---------|
| **BR-21** | Cross-engine schema equivalence (MariaDB/SQLite/Teradata produce structurally equivalent tables to PostgreSQL). | Deferred — declared out of scope per `evals/FAILURE_MODES.md` |
| **BR-22** | Performance at scale (≥ 1 M rows loaded within a defined time budget). | Deferred — declared out of scope per `evals/HANDOFF.md` |

---

## 2. Traceability matrix

For each requirement, the columns mark which test layer verifies it. Numbers in cells are scenario/test IDs from `docs/TEST_CONDITIONS.md`. **Status** is the worst-case across the cells (a requirement is ⚠️ if any aspect is partial, ❌ if no automated coverage exists).

| ID | Requirement (short) | PU | SQL | TP | TI | TS | LV | Status | Notes |
|----|--------------------|----|-----|----|----|----|----|-------|-------|
| BR-01 | Multi-env isolated (Dev/Test/Staging/Prod) | — | suite 05 (schema_name) | — | — | 01 (Dev) | **Tier E 01** | ✅ | Tier E `01_envs_have_identical_structure` deploys all four environments and compares column signatures against Dev. Resolved 2026-09-10. First real run passed in CI run [40186756039](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/40186756039) on `main` 59aab1a, 2026-10-25. |
| BR-02 | Six DB engines via adapters | — | — | — | — | — | Tier X 01 (SQLite, not in CI) | ⏸ | **Deferred by decision** (ADR-0001): PostgreSQL first. Tier X `01_sqlite_schema_structure` exists and passes but is not run in CI. Measured state: PG 12 tables, SQLite 7, MariaDB 7, Teradata 12 (`CREATE SET TABLE`; never run against a Teradata server); InfluxDB and Redis ship seed data with no DDL. *(Teradata corrected from 1 on 2026-11-24, erratum E-09, §6.5.)* |
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
| BR-15 | Per-env connection limits | — | suite 05 (S10, `pg_roles.rolconnlimit`) | — | — | 01 | — | ✅ | Assertion S10 compares the app role's `rolconnlimit` with the environment's `conn_limit`. Passed in CI run [40186756039](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/40186756039) on `main` 59aab1a, 2026-10-25. |
| BR-16 | Automated single-command regression | — | — | All TP (single `runner.py` invocation) | 01 | 01 | — | ✅ | Combined `runner.py --tiers p,i,s` is the entry point. |
| BR-17 | Graceful degradation when PG unavailable | 9, 11 | — | — | (skip behaviour) | (skip behaviour) | — | ✅ | Python unit tests directly assert the skip path. |
| BR-18 | Machine-readable JSON report per run | 5, 6 | — | — | — | — | — | ✅ | Verified by `_load_expected` and `discover_scenarios` unit tests; the report write itself is exercised by every Tier P run. |
| BR-19 | Build / tests / evals physically segregated | — | — | — | — | — | — | ✅ | Verified by `docs/ARCHITECTURE.md` + the directory layout + the green test runs after the refactor. (Verification method = Inspection.) |
| BR-20 | 159 / 159 SQL assertions pass | — | (all 6 suites) | — | — | **01 (asserts `min_total_assertions: 159`, `min_pass_rate_percent: 100`)** | — | ✅ | Tier S is the headline gating check. Count updated from 85 → 142, and on 2026-11-24 from 142 → 159 (E-05): Tier S observed 159 of 159 on PostgreSQL 16 (local run, 24 Nov; per file 23, 25, 23, 38, 33, 17). Threshold raised from 142 to 159 on 2026-11-25 (#303, OIT-018): with one assertion removed, Tier S fails (`total_assertions: expected >= 159, got 158`), and `tests/unit/test_tier_s_threshold.py` fails if the threshold and the suite's count differ. |
| BR-21 | Cross-engine schema equivalence | — | — | — | — | — | — | ❌ | Deferred. Tier X. |
| BR-22 | Performance at ≥ 1 M rows | — | — | — | — | — | — | ❌ | Deferred. No perf tier exists. |

### Bonus: data-load layer (orthogonal to the T&E requirements above)

The `input_data/` loader has its own implicit requirements — verified end-to-end by the 5-section verification block at the bottom of `load_input_data.sql`.

> **Erratum E-08 (applied 2026-11-24, §6.5):** `input_data/load_input_data.sql` is not in the repository (`git ls-files`), so the ✅ below cannot be re-run and is kept as the historical record only. These rows are not counted in §3.

| ID | Implicit requirement | LV section | Status |
|----|---------------------|------------|--------|
| BR-D1 | All staging rows reach the target table (or are reported as dropped) | 3 (reconciliation) | ✅ |
| BR-D2 | Aggregates on the loaded data match expectations | 2 (aggregates) | ✅ |
| BR-D3 | No NULL appears in a NOT NULL column post-load | 5 (NULL audit) | ✅ |
| BR-D4 | Duplicate primary keys in source are reported, not silently dropped | 4 (duplicate detection) | ✅ |
| BR-D5 | Loaded data is browsable (sample peek) | 1 (sample rows) | ✅ |

### ART extension and later requirements, traceability (BR-23 to BR-38)

Status as assessed on 2026-10-26 at `main` 032b522. None of these is "Verified" until a test run proves it (D5).

| ID | Status | Reason | Planned verification | Milestone |
|----|--------|--------|----------------------|-----------|
| BR-23 | ✅ | Every upload attempt gets an `uploads` row (M3b, #107): id, original filename, SHA-256, uploader, timestamp and outcome (imported, partly_imported, failed, duplicate, rejected). The tenant is the schema the row lives in (decision 6), not a column. Registry UNIQUE hash and name from M1 (#87). `test_preserved_uploads.py`. Direct upload path: since #321 (`eac1a06`, 23 Nov) the registry row, original and audit row are written in the load's transaction (`api/routers/csv_routes.py`, `on_commit=record_with_load`), so erratum E-06 is not applied (§6.5) | Integration + DB constraint tests | M1, M3 |
| BR-24 | ⚠️ Partial | Original bytes (`upload_blobs`) and parsed rows (`source_rows`) kept for every upload, including failed ones and files later overwritten or deleted (M3b, #107). Triggers reject UPDATE, DELETE and TRUNCATE (`test_preserved_uploads.py`, 7 tests), and the API's runtime role has no UPDATE, DELETE or TRUNCATE grant on them (M3d, `test_runtime_role.py`). Still to do: show edits kept separate once they exist (M4) | DB negative tests | M3 |
| BR-25 | ✅ | `GET /api/csv/uploads/{id}/rows` pages through every stored row and column (up to 500 a page), with column types and each row's validation errors, including rows beyond the 200 errors reported at upload (M4a, `test_review.py`). The review screen pages through them with types and invalid cells marked (M4b, `review-table.test.tsx`, e2e `scripts/e2e/m4-review.js`). #108 | API paging + e2e | M4 |
| BR-26 | ✅ | Include or exclude a row with a required reason; actor and time recorded; insert-only history, latest wins; audited with before and after (M4a, `test_review.py`). The review screen does it, shows it after reload and lists the history (M4b, e2e `scripts/e2e/m4-review.js`). Applied to imports in M6 (decision 1 on #108) | API + e2e | M4 |
| BR-27 | ✅ | Cell edits are insert-only versions in `cell_edits` with old and new value, actor, time and a required reason; the original in `source_rows` is unchanged; edited values are revalidated; each edit is audited (M4a, #108, `test_review.py`: API and DB tests). The screen to make edits arrives in M4b | API + DB tests | M4 |
| BR-28 | ✅ | Race guard enforced by UNIQUE constraints (M1: #87, `tests/test_migrations.py`). Every request dedups within its own registry: a tenant's, or the deployment's default registry for a request with no session. The same file in two tenants is not a duplicate (M2: #100, `test_duplicate_detection_is_per_tenant`), and a repeat with no session is refused without matching any tenant's files (M5, #109: `test_versions_and_dedup_are_independent_per_tenant_and_without_a_session`). `overwrite` no longer bypasses it (`test_overwrite_flag_does_not_bypass_exact_file_dedup`) | Concurrency + cross-tenant tests | M1, M5 |
| BR-29 | ⚠️ Partial | Exact whole-row match within a file, and across the earlier versions of the same dataset (M5, #109): a repeated row is loaded but flagged (`row_flags`, insert-only), shown on the review page, and the user excludes or keeps it per row with the M4 decision (`test_versioned_datasets.py`, 6 tests). Still to do: the configurable rule (key columns per dataset), and matching across different datasets | Unit + integration | M5 |
| BR-30 | ✅ | A repeated filename becomes the next version, `csv_<slug>_v<n>`; no version is overwritten, and the `overwrite` flag is ignored (M5, #109, decision 2). The slug is lower-case ASCII, 40 characters at most, behind a fixed `csv_` prefix and `_v<n>` suffix, so a filename can't name a registry table (`test_versioned_datasets.py`; migration 0009 backfills existing uploads, `test_migrations.py`). Concurrent same-name uploads get distinct versions (`test_registry_race.py`) | Unit + integration | M5 |
| BR-31 | ⚠️ Partial | A new version's columns are compared with the previous version's and the difference is reported (added, removed, retyped); the previous table is never altered, and the overwrite path that dropped tables is gone (M5, #109, `test_versioned_datasets.py`). T&E mode still checks against its fixed schema. Open: a T&E upload with identical content to a dynamic dataset still replaces that entry and drops its table (permission-gated, #175); the comparison reports only, it doesn't block | Integration | M5 |
| BR-32 | ⚠️ Partial | Submit, approve and reject for dynamic-mode uploads (M6, #110): a reviewer decides, a rejection needs a reason, and a rejected upload can be reviewed again and resubmitted; the approver is recorded in `approvals` and the audit log. A signed-in member can't approve data they uploaded or submitted unless the tenant allows it (decision 5). `test_staged_import.py`: reject-then-resubmit, self-approval (5 tests). Open: `POST /api/csv/upload` and T&E mode still import without approval until the frontend moves to this flow | API + e2e | M6 |
| BR-33 | ⚠️ Partial | The staged import (M6, #110, ADR-0002) COPYs the approved rows into a staging table, promotes them, and commits the data, registry row, import record and audit row in one transaction; every imported row carries `_source_row_id` and `_import_id`. Failure injected at three steps leaves nothing behind and the same-key retry then succeeds; a repeat after success returns the original; concurrent imports import once (`test_staged_import.py`, `AllOrNothing`). It works as the restricted runtime role (`test_runtime_role.py`). Open: the direct upload path and T&E mode aren't staged | Integration incl. failure injection | M6 |
| BR-34 | ⚠️ Partial | Total, inserted, duplicate and failed counts persisted per import (M1: #90, `tests/test_import_counts.py`); an upload where every row fails is reported as failed and saves nothing, and partial failures are shown on the files list (#123, `tests/test_failed_uploads.py`); over-wide rows reported, not dropped (M1: #88, `tests/test_ragged_rows.py`); excluded and edited rows are now counted: each staged import stores rows in, excluded, edited, duplicate and imported, and the database checks that in = excluded + duplicate + imported (M6, #110, migration 0011, `test_staged_import.py`, `test_migrations.py`). Open: the direct upload path and T&E mode don't record excluded or edited | Integration | M1, M6 |
| BR-35 | ✅ | Export formula injection neutralised (M1: #86, `export.test.ts`). Audit log append-only (M3a, #107): triggers reject UPDATE, DELETE and TRUNCATE for every role; actor recorded; hash chain checked by `GET /api/audit/verify` (`test_audit_append_only.py`, 7 tests). The API's runtime role can only read and insert it, and can't disable its triggers (M3d, `test_runtime_role.py`). Reports are filterable on the server (M7, #111): `GET /api/audit/events` filters by actor, action, file, table and time, with a formula-safe CSV download, and `GET /api/csv/uploads` filters and gives each failed attempt's stored reason (`test_reports_and_policy.py`, 23 tests). The React audit page shows the server events in a "Server audit events" panel (`ServerAuditEvents.tsx`, used by `routes/audit.tsx`, f99c7c1), and the Streamlit Import history page has the same view. *(Corrected 2026-11-24, erratum E-04: this said the frontend didn't call them yet.)* | DB negative tests + unit | M1, M3, M7 |
| BR-36 | ⚠️ Partial | Done in M2:<br>• local accounts with lockout (#98, #103)<br>• OIDC (#105)<br>• per-tenant schemas, T&E tables included (#100, #104)<br>• role matrix in `docs/ROLES.md` (#101)<br><br>Tests: `tests/test_accounts.py`, `test_tenant_isolation.py`, `test_roles.py`, `test_oidc.py`, `test_password_reset.py`. Each failed with its control removed.<br>• frontend sign-in; the browser no longer holds the shared key (#115)<br>• password change, admin reset and break-glass reset (#117; `tests/test_password_reset.py`)<br>• the database enforces tenant isolation: one role per tenant, `SET ROLE` per request, so a cross-tenant query fails with `InsufficientPrivilege` (#297; `DECISIONS/2026-11-24-per-tenant-db-roles.md`; `test_tenant_isolation.py`, `test_runtime_role.py`).<br>• shared API key retired (#298, OIT-013, SEC F8; merged in #401, 24 Nov 2026): every data request needs a session, so it is tenant-scoped, role-checked and audited under the user's name; anonymous access only for local dev by explicit opt-in (`API_ALLOW_ANONYMOUS=1` with `API_ENV=dev`); `tests/test_sessions_required.py`<br><br>Open: security review (#112; the pack to review against, with 11 findings from the author's own pass, is `docs/SECURITY_REVIEW_PACK.md`); real-IdP OIDC check (#113): the https key fetch, key rotation, an untrusted certificate and an IdP that is down or hangs are now tested against a local TLS IdP (`test_oidc_https.py`, 12 tests; the key fetch now times out after 5 s instead of 30), and `scripts/check_oidc.py` with `docs/OIDC_REAL_IDP_CHECK.md` is the check to run once against the real IdP | Cross-tenant negative tests; role matrix tests | M2 |
| BR-37 | ⚠️ Partial | Automated now (M7, #111, `docs/SOVEREIGNTY.md`): a static scan of the API and frontend source (`tests/unit/test_sovereignty.py`); the API tests run with non-local connections refused and any attempt failing the run (`make test-egress-blocked`, a CI step; negative control checked), and the same tests run as a throwaway user whose network is blocked at the firewall, so child processes and libpq are covered too (`scripts/egress_firewall.sh`, a CI step with its own negative control, #310); a built-bundle scan, clean on the client and server bundles (`scripts/check_bundle_egress.py`). Classification is marked on every response and the retention is configurable (decision 7). The only external call is the OIDC key fetch, to a deployment-controlled IdP and off unless configured. Open: the offline install dry run on a clean VM (#60); the network-level block runs only in CI (a hosted runner, not an on-premises rehearsal) | Egress-blocked run + offline dry run | M7 |
| BR-38 | ⚠️ Partial | Done (#245, CI run 44079821960): the container bundle (`container/`): three images, `install.sh` (macOS, Linux) and `install.ps1` (Windows), and the 7-check smoke test. 7 of 7 with the containers cut off from the internet on Linux amd64 and arm64 with Docker and on amd64 with Podman, in CI; the CI-built bundle was also installed by hand: 7 of 7.<br><br>Open: the same run on Windows and macOS, and `install.ps1` on Windows PowerShell 5.1 (not run anywhere yet). The run sheet and the evidence to attach are in `docs/BR38_EVIDENCE.md` | Offline smoke test 7/7 on Windows, macOS and Linux | #128 |

### Traceability additions (BR-45 to BR-49) and owner re-raise, added 2026-11-19

BR-39 to BR-44 stay reserved for the proposals awaiting disposition (accessibility, disposal, backup; `docs/HANDOFF-20261104.md` item 28), so the next free numbers are BR-45 onwards. Method uses ASDEFCON vocabulary: Test (T), Analysis (A), Inspection (I), Demonstration (D). "Local run" below means a run on the author's machine on 2026-11-19 (PostgreSQL 17, not the CI PostgreSQL 16 service); it is evidence, not a CI result.

| ID | Requirement | Method | Status | Evidence / gap | Owner | Date | Detector |
|----|-------------|--------|--------|----------------|-------|------|----------|
| BR-45 | The upload audit record, and on the direct upload path also the registry (`uploads`) row and the preserved original, shall be atomic with the load, or a crash between load commit and any of those writes shall be detected and recovered (a reconciliation check lists any committed load without them), with the recovery verified. *(Widened 2026-11-20 to absorb proposed BR-52; see §6.4.)* | T (fault injection between load commit and the audit, registry and original writes; must fail, not skip) + A | ✅ Verified (2026-11-25) | Met by #321 (`eac1a06`, merged 23 Nov; #288, OIT-003): on the direct `POST /api/csv/upload` path and in T&E mode the registry row, the original and the audit row are written on the load's own cursor before its commit (`on_commit` hook; `api/routers/csv_routes.py` `record_with_load`), so they commit together or not at all, and a failure returns `record_failed` with nothing committed. `tests/system/test_upload_atomic_records.py` (6) injects a fault into the original's writer and into the audit writer, for both modes: no registry row, dataset table, T&E rows, imported `uploads` row or `upload` audit row is left, and the response is not ok. All four fault tests failed on `main` before the fix (PR #321). The "detected and recovered" alternative is not needed, since nothing commits without its records. Quality Gate run [45385799328](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/45385799328) on PR #408, 24 Nov, integration shards with `--strict`: no test skipped or not run. *(20 Nov evidence, superseded: the except branches of `record_upload` and `record_audit` were never executed; the direct path wrote the audit row in a separate transaction.)* | Amarnath Rasineni | 2026-11-19 | F11 in `docs/HANDOFF-20261104.md` (related to M0 F1, baseline 032b522) |
| BR-46 | Every export path shall neutralise spreadsheet formulas: a text cell starting with `=`, `+`, `-`, `@`, tab or CR is written with a leading `'`; plain numbers are unchanged. | T + I | ✅ Verified (frontend, local run) | Implemented in `csv-table-hub-main/src/lib/export.ts` (CSV and XLSX), `streamlit_app/exports.py` and `api/services/reports.py`. `export.test.ts` passed in the local vitest run (196 of 196); `tests/unit/test_streamlit_exports.py` passed in the DB-free run; `tests/system/test_reports_and_policy.py` passed locally. Refines BR-35's export clause. | Amarnath Rasineni | 2026-11-19 | M0 F3 (#83), baseline 032b522 |
| BR-47 | Failure reasons for every upload attempt shall be persisted server-side and displayed from the server, independent of the uploading browser. | T + D | ⚠️ Partial (remaining scope deferred to M7) | Done in M3b/M3c (#107, closed): `uploads.row_errors` and `uploads.logs` (migration 0007), read by the Migrated files Preview (`stored-row-errors.test.tsx`, passed locally; `tests/system/test_preserved_uploads.py` and `test_failed_uploads.py`, passed locally). Open: the Import history and `/audit` page still read browser `localStorage`; row errors are capped at `API_MAX_ROW_ERRORS` (default 200). | Amarnath Rasineni | 2026-11-19 | README claims review 2026-11-19 |
| BR-48 | The coverage gate shall measure `api/` (which holds the loader path in `api/services`) as well as `build/csv` and `evals`, with branch coverage. | I + T | ⚠️ Partial | `Makefile` `test-gate`/`test-all` pass `--cov=api --cov=build/csv --cov=evals --cov-branch`; `.coveragerc` sets the same source and `branch = True`. CI measures `api`, `streamlit_app`, `build/csv` and `evals` with branch coverage (the same `COVERAGE_SCOPE` in the `Makefile`, `.coveragerc` and the integration shards), and `scripts/check_coverage_floors.py` gates per-loader floors in `api/services` and package floors for `api/` (90 %) and `streamlit_app/` (92 %). Open: no floor for `build/csv` or `evals` (#304, OIT-019). *(Corrected 2026-11-24, erratum E-07: this said the integration job measured `api/services` only.)* | Amarnath Rasineni | 2026-11-19 | Gate scope review 2026-11-19 |
| BR-49 | `preflight.ps1` shall parse and run on Windows PowerShell 5.1 and 7, with PG checks optional and the port label following `PGPORT`. | I (static) + T (Windows run) | ⚠️ Partial | `tests/unit/test_preflight_ps1.py`: the static Inspection tests (no `??` or other PS 7-only syntax, no BOM, defaults, exit codes) pass in the DB-free run on Linux. The Windows execution tests are collected only where `powershell.exe` exists and were not run for this entry. | Amarnath Rasineni | 2026-11-19 | PR #145 regression (fix a83a1a4) |
| BR-21 (re-raised) | Cross-engine schema equivalence. | T (Tier X) | ⏸ Deferred by decision | No owner was recorded. Revisit trigger unchanged (Section 4). | Amarnath Rasineni | 2026-11-19 | Owner review 2026-11-19 |
| BR-22 (re-raised) | Performance at ≥ 1 M rows within a defined time budget. | T (`tests/performance/`) | ⏸ Deferred by decision | No owner was recorded. `tests/performance/test_import_scale.py` exists but no ≥ 1 M-row budget is asserted. 2026-11-20: proposed BR-59 merged here (§6.4). On reactivation (M7) this requirement also covers the decision-8 targets: `PERF_ENFORCE=1 PERF_ROWS=100000` passing on the reference instance (2 vCPU / 4 GB), timings recorded per release. Today `PERF_ENFORCE` is not set in CI (`tests/performance/test_import_scale.py:4-7`); an indicative 9.96 s was measured on a non-reference VM. | Amarnath Rasineni | 2026-11-20 | Owner review 2026-11-19; disposition 2026-11-20 |

### Approved additions (BR-50, BR-51, BR-53, BR-54, BR-55, BR-58), disposition 2026-11-20

Approved by the product owner on 2026-11-20 from the proposals in §6.3 (dispositions of all eleven are in §6.4). The numbers are kept as proposed, so the IDs quoted in `docs/Outstanding Items Tracker_Grok.txt` stay valid; BR-52, BR-56, BR-57, BR-59 and BR-60 are retired as IDs and are not reused. None of these is met yet.

| ID | Requirement | Method | Status | Evidence / gap | Owner | Date | Detector |
|----|-------------|--------|--------|----------------|-------|------|----------|
| BR-50 | Schema migrations run at API start shall be safe when two or more API processes start together against the same database. | T (concurrent start, fresh and at-head DB) + I | ✅ Verified (2026-11-25) | Met by #320 (`9c70921`, merged 23 Nov; #286, OIT-001): `alembic/env.py` takes a session-level advisory lock before `CREATE SCHEMA` and the migrations. `tests/system/test_concurrent_migrations.py` starts two processes at the same moment, 10 trials on a fresh schema and 10 on one a revision behind: both exit 0 and `alembic_version` is head in every trial. Before the fix both scenarios failed 10 of 10 (`UniqueViolation`, `DuplicateColumn`; PR #320). Quality Gate run [45385799328](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/45385799328) on PR #408, 24 Nov, integration shards with `--strict`: no test skipped or not run. *(20 Nov: reproduction R1, one process failed in 5 of 5 trials.)* | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 (HANDOFF F5) |
| BR-51 | No upload shall drop or replace another dataset's table unless the caller has delete permission **and** `API_ALLOW_DESTRUCTIVE` is enabled; the shared-key path shall not bypass this. | T | ✅ Verified (2026-11-25) | Met by #319 (`79a3f7b`, merged 23 Nov; #287, OIT-002): a T&E upload whose content is already a dynamic dataset is refused (`duplicate_file`, `existingMode: dynamic`) before anything is written, and the T&E cleanup no longer drops any table. `tests/system/test_te_cannot_drop_dataset.py`, with `API_ALLOW_DESTRUCTIVE` off, for a caller with no session and for a signed-in tenant admin (who holds delete permission): the dataset's table, rows and registry row survive, and no T&E rows or registry row land. Both tests failed on `main` before the fix (table dropped, HTTP 200; PR #319). The shared-key path no longer exists: the key was retired in #298, so every data request needs a session. Quality Gate run [45385799328](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/45385799328) on PR #408, 24 Nov, integration shards with `--strict`: no test skipped or not run. *(20 Nov: reproduction R2, table dropped, HTTP 200.)* | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 (related #175, BR-31) |
| BR-53 | The API shall reject a request body larger than the configured limit before parsing it. | T | ✅ Verified (2026-11-25) | Met by #290 (OIT-005; PR #367, merged to `main` through batch PR #378, `7fd7b5a`, 23 Nov): `BodyLimitMiddleware` answers 413 on a `Content-Length` over the cap without reading the body, and counts a chunked or mis-declared body as it streams, stopping at the cap; the handler is not entered. `tests/unit/test_body_limit.py` covers a body of 2 × `MAX_UPLOAD_BYTES` with an honest, a missing and a wrong `Content-Length`, at the ASGI level and through the real app. Seven mutations of the fix each turn a test red (PR #367). Passed locally 25 Nov and in the free-tier job. *(20 Nov: the size was checked after the Pydantic parse.)* | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 (SEC F1) |
| BR-54 | Unauthenticated endpoints shall not disclose database name, host, port, server version or schema outside `dev`; `/docs`, `/redoc` and `/openapi.json` need auth or are off in `prod`. | T + I | ✅ Verified (2026-11-25) | Met by #291 (OIT-006; PR #366, through #378, 23 Nov): with `API_ENV` anything but `dev`, `/api/health` returns only `status`, and `/docs`, `/redoc` and `/openapi.json` are not served (404); `dev` is unchanged. `tests/unit/test_prod_health_and_docs.py` (12); nine failed on the old code and four mutations each turn a test red (PR #366). Passed locally 25 Nov and in the free-tier job. *(20 Nov: `api/main.py` returned the database name, host, port, version and schema.)* | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 (SEC F2) |
| BR-55 | Secrets shall never be logged, in whole or in part. | I + T | ✅ Verified (2026-11-25) | Met by #292 (OIT-007; PR #365, through #378, 23 Nov): the start-up log contains no part of `API_KEY`. Since #298 retired the key, an install that still sets it gets a warning that it is unused, still without any part of it. `tests/unit/test_api_key_not_logged.py` runs the real `lifespan` with a known key and checks every substring of four or more characters; three mutations (first four characters put back, the whole key logged, its length logged) each turn a test red (PR #365). Passed locally 25 Nov and in the free-tier job. *(20 Nov: `api/main.py` logged the first four characters.)* | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 (SEC F10) |
| BR-58 | Import concurrency shall be bounded per API instance (decision 1: 4 concurrent imports). | T + A | ✅ Verified (2026-11-25) | Met by #307 (OIT-022; PR #374, through #378, 23 Nov): `api/concurrency.py` `import_slot` admits `API_MAX_CONCURRENT_IMPORTS` (default 4) uploads, stages and imports at once per process and refuses the next at once with 503 and `Retry-After`; `0` turns it off. `tests/unit/test_concurrent_import_limit.py` (17): on each of the three routes 4 concurrent requests are admitted, the 5th gets 503, and a slot frees when a request ends or fails; 12 of 12 mutations turn a test red (PR #374). Pool exhaustion is documented in `docs/ENV_VARIABLES.md` (`API_POOL_GETCONN_TIMEOUT`, `API_MAX_CONCURRENT_IMPORTS`: 4 imports leave 4 of the pool's 8 connections for everything else; the limit is per process). Passed locally 25 Nov and in the free-tier job. *(20 Nov: no limit in `api/`.)* | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 (M0 decision 1) |

---

## 3. Coverage summary

### By layer

| Layer | Requirements with at least one cell ticked | % of in-scope requirements (BR-01..BR-20) |
|-------|-------------------------------------------|-------------------------------------------|
| Python unit (PU) | 4 (BR-10/11/17/18) | 20 % |
| SQL suites (SQL) | 12 (BR-01/03/04/05/06/07/08/12/13/14/15/20) | 60 % |
| Tier P (TP) | 3 (BR-10/11/16) | 15 % |
| Tier I (TI) | 4 (BR-04/09/16/17) | 20 % |
| Tier S (TS) | 15 (BR-01/03/04/05/06/07/08/09/12/13/14/15/16/17/20) | 75 % |
| Load-verify (LV) | 5 implicit (BR-D1..D5) | n/a — separate domain |

Recounted from the §2 cells on 2026-11-24 (§6.5, E-10). PU listed four requirements but said 5; TP counted BR-18, whose TP cell is "—"; TS left out BR-17, whose TS cell (skip behaviour) is counted the same way in TI. BR-01's LV cell names Tier E, not load-time verification, so it is not counted under LV.

### By verification status

| Status | Count | Requirements |
|--------|-------|-------------|
| ✅ Verified | 34 | BR-01, BR-03, BR-04, BR-05, BR-06, BR-07, BR-08, BR-09, BR-10, BR-11, BR-12, BR-13, BR-14, BR-15, BR-16, BR-17, BR-18, BR-19, BR-20, BR-23 (M3b), BR-25, BR-26, BR-27 (M4), BR-28, BR-30 (M5), BR-35 (M7), BR-46 (added 2026-11-19), BR-45, BR-50, BR-51, BR-53, BR-54, BR-55, BR-58 (verified 2026-11-25) |
| ⚠️ Partial | 12 | BR-24, BR-29, BR-31, BR-32, BR-33, BR-34, BR-36, BR-37 (ART, added 2026-10-26), BR-38 (added 2026-10-27), BR-47, BR-48, BR-49 (added 2026-11-19) |
| ❌ Not started | 0 | — (BR-45, BR-50, BR-51, BR-53, BR-54, BR-55 and BR-58 were here until 2026-11-25) |
| ⏸ Deferred by decision | 3 | BR-02, BR-21, BR-22 |

Table brought up to date 2026-11-25 (seven requirements verified, see the 2026-11-25 headline); before that 2026-11-20 (erratum E-01 in §6.2 applied). Reserved BR-39 to BR-44 and the proposals mapped to them (§6.4) are not counted.

**Headline (2026-11-25):** the fixes for BR-45 (#321), BR-50 (#320), BR-51 (#319), BR-53, BR-54, BR-55 and BR-58 (#378) merged on 23 Nov. Each acceptance criterion was re-checked on 25 Nov against the merged tests, which failed before their fix and pass in CI on `main`'s code (§2 rows), and the seven are now verified. So **34 of 49 (69 %)** are verified, 3 are deferred by decision, and the other 12 are partial or not started.

**Headline (2026-11-20):** the product owner disposed of the eleven proposals in §6.3 (§6.4). BR-50, BR-51, BR-53, BR-54, BR-55 and BR-58 were approved as new requirements, and none is met yet; BR-52 was merged into BR-45 (wording widened) and BR-59 into the deferred BR-22; BR-56 and BR-57 were mapped to the reserved BR-39 to BR-44 set and stay uncounted; BR-60 is a decision action, not a requirement. So **27 of 49 (55 %)** are verified, 3 are deferred by decision, and the other 19 are partial or not started.

**Headline (2026-11-19):** BR-45 to BR-49 were added (#272): BR-46 is verified, BR-47, BR-48 and BR-49 are partial, and BR-45 is not started. So **27 of 43 (63 %)** are verified, 3 are deferred by decision, and the other 13 are partial or not started.

**Headline (2026-11-10):** M7 (#111) verifies BR-35, so **26 of 38 (68 %)** are verified, 3 are deferred by decision, and the other 9 are partial or not started; BR-37 stays partial until the offline install dry run (#60). Before that, with BR-28 and BR-30 verified by M5 (#109; full suite 418 passed, 0 failed, 0 skipped), **25 of 38 (66 %)** are verified, 3 are deferred by decision, and the other 10 are partial or not started. M6 (#110) moved BR-32 from not started to partial; BR-32, BR-33 and BR-34 stay partial until the direct upload path and T&E mode go through the approval flow.

**Headline (2026-10-28):** with BR-23 verified by M3b (#107) and BR-25, BR-26 and BR-27 by M4 (#108), **23 of 38 (61 %)** are verified, 3 are deferred by decision, and the other 12 are partial or not started.

**Headline (2026-10-26):** with the 15 ART requirements added, **19 of 37 (51 %)** are verified, 3 are deferred by decision, and the other 15 are partial or not started.

**Headline before ART:** **19 of 22 (86 %)** business requirements are fully verified by at least one automated test condition, up from 17 of 22 (77 %).

*Superseded 2026-11-24 (erratum E-02, §6.5): the paragraph below was true before ART. Since 2026-10-26 requirements that are partial or not started, and are not a recorded decision, have existed; the status table above is the current count.*

**There are no longer any unverified requirements that are not a recorded decision.** The three remaining are deferred deliberately: BR-02 by ADR-0001 (PostgreSQL first), BR-21 and BR-22 by earlier project decisions. That distinction matters in review — an unverified requirement is a gap, a deferred one is a choice with a revisit trigger.

Changed 2026-09-10:

- **BR-01** ⚠️ Partial → ✅ Verified. Tier E `01_envs_have_identical_structure`.
- **BR-15** ❌ Not verified → ✅ Verified. Assertion **S10** in `tests/suites/test_05_schema_and_business_rules.sql` reads `pg_roles.rolconnlimit`.
- **BR-02** ❌ Not verified → ⏸ Deferred by decision. See ADR-0001.

Confirmed in CI 2026-10-25 (CI run [40186756039](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/40186756039) on `main` 59aab1a, 2026-10-25):

- Evals Tiers P, I, S, E: 26 of 26 passed, including Tier E `01_envs_have_identical_structure` (O-07) on its first real run. #45 is resolved.
- `scripts/test_report.py --strict` against PostgreSQL 16: 238 collected, 238 passed, 0 failed, 0 skipped. This includes the `mode=te` integration tests and the audit-trail tests.
- The BR-15 matrix row above previously still read ❌ although this summary counted it as verified; it now shows the S10 evidence.

---

## 4. Gap analysis

### Genuine gaps

*Superseded 2026-11-24 (erratum E-03, §6.5): genuine gaps exist again. The open ones are the requirements that §3 counts as partial or not started; issue-level detail is in `docs/Outstanding Items Tracker_Grok.txt` and the GitHub issues it cites. The text below is the 2026-09-10 record.*

**None outstanding as at 2026-09-10.** All three gaps previously listed here have
been closed or converted into a recorded decision. The table is retained as the
history of what was addressed and how.

| Req | Gap (historical) | What was done | Status |
|-----|------------------|---------------|--------|
| **BR-01 partial** | Test/Staging/Prod were deployable but their structural equivalence to Dev was not asserted. A change in `env_test.sql` drifting from `env_dev.sql` would not be caught. | Built Tier E scenario `01_envs_have_identical_structure`: deploys all four environments, reads `information_schema.columns` per environment, reduces each to a table → ordered `column:type:nullability` fingerprint excluding the schema name, and compares the other three against Dev. Reordered columns count as drift. Comparison logic unit-tested in `tests/test_evals_tier_e_x.py` with negative controls. | ✅ Resolved |
| **BR-02** | The framework claimed 6 DB engines via adapters, but no test ran against MariaDB / SQLite / etc. | Built Tier X scenario `01_sqlite_schema_structure`, which executes the SQLite DDL and pins its structure. It measured a shortfall the requirement's wording does not admit — PG 12 tables, SQLite 7, MariaDB 7, InfluxDB and Redis no DDL at all. (It also recorded Teradata as 1; the file defines 12 with `CREATE SET TABLE`, erratum E-09, §6.5.) A decision was then taken to pursue PostgreSQL first. | ⏸ Deferred by decision — [ADR-0001](adr/0001-postgresql-first.md) |
| **BR-15** | The per-environment `conn_limit` lived in `env_*.sql` but no test confirmed it was applied. | Added assertion **S10** to `tests/suites/test_05_schema_and_business_rules.sql`, reading `rolconnlimit` from `pg_roles` and comparing it against the environment's `conn_limit` forwarded via `set_config('te.conn_limit')`. A typo such as `conn_limit=5` in `env_prod.sql` now fails the suite. | ✅ Resolved |

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

1. **Requirements extraction** — read `README.md`, `docs/ARCHITECTURE.md`, `evals/PLAN.md`, `evals/FAILURE_MODES.md`, `evals/HANDOFF.md`, `docs/TEST_CONDITIONS.md`. Identified statements of intent that could be operationalised as testable conditions.
2. **Domain inference** — supplemented the documented requirements with industry-standard T&E concerns referenced in the README (ASDEFCON, ISM, MIL-STD-882, ISO 31000). These appear in BR-12, BR-13, BR-14, BR-15.
3. **Traceability** — for each requirement, walked through all six test layers and recorded the specific test condition(s) that assert it. Where multiple test conditions touched the same requirement, all are recorded.
4. **Coverage classification** — applied the ✅ / ⚠️ / ❌ legend uniformly: a requirement is ✅ only if every aspect is verified; ⚠️ if some aspects are tested and some are gaps; ❌ if nothing tests it.

**Known limitations of this VCRM:**

- The requirements catalogue (Section 1) is **inferred from documents**, not derived from a formal Statement of Requirement. In a production T&E setting it would be reviewed and ratified by the customer / stakeholders.
- Requirements are at a high level. A formal SRS / TRD would decompose each into 5-20 sub-requirements and the matrix would grow accordingly.
- Verification method is implicitly **Test (T)** for every cell with an automated test ID. **Inspection (I)** is used for BR-19. **Analysis (A)** and **Demonstration (D)** methods aren't used because every requirement has either Test coverage or is deferred. *(Superseded 2026-11-24, erratum E-03: the BR-45 onwards rows in §2 name I, A and D as well as T.)*

**Recommended review actions:**

1. Stakeholder review of Section 1 — confirm the 20 in-scope requirements really are the right ones.
2. ~~Triage the 3 genuine gaps (BR-01-partial, BR-02, BR-15)~~ — **done 2026-09-10.** BR-01 and BR-15 are
   verified; BR-02 is deferred by ADR-0001. Confirm the deferral still reflects intent at each milestone review,
   using the revisit triggers in that ADR.
3. Re-verify after each release: re-run all test layers, update this matrix if any cell flips status.

---

*Companion documents:*

- `docs/ARCHITECTURE.md` — the three-layer model (build / tests / evals)
- `docs/TEST_CONDITIONS.md` — every test condition catalogued in full detail
- `evals/FAILURE_MODES.md` — failure-mode catalogue at the eval layer
- `evals/PLAN.md` — eval suite design rationale


---

## 6. Independent T&E audit review, 2026-11-20 (appended; nothing above was changed)

This section is an append-only addendum. No requirement above was deleted, renumbered or reworded. Where something above is now wrong, it is recorded as an erratum here (6.2) for the owner to apply or reject. *(2026-11-24: the errata were dispositioned and the accepted ones applied above, each marked where it changed; see §6.5. BR-20's count was reworded under E-05.)*

**Baseline.** `main` at `68399af365d6c076b0fc43ce5c91f3165e44844d` (merge of PR #284, 2026-11-19T15:58:43Z). Open PRs at review time: none. Unmerged branches are listed in `docs/AUDIT_RECONCILIATION_2026-11-20.md` §1; nothing on them is counted below.

**Reviewer (Detector).** Claude, an Anthropic model, running as the Abacus.AI agent. The exact model version string is not available to the reviewer, so none is given. Shown below as "Review 2026-11-20".

**Evidence used.**

- CI at the baseline: Quality Gate run [44560865716](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/44560865716) (integration, browser, free-tier and accessibility jobs: all success) and Python Validator Tests run [44560865884](https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader/actions/runs/44560865884) (Windows, 875 passed, 467 deselected).
- Local replay of the Quality Gate free-tier and integration steps on the review VM: PostgreSQL 16.16, Python 3.11.17, Linux. This is reviewer evidence, not a CI result.

| Step | Command (as in `quality-gate.yml`) | Result |
|---|---|---|
| Free tier | `scripts/test_report.py --markers "unit or regression or security or snapshot" --strict` | 870 passed, 0 failed, 0 skipped, 467 not run (marker filter) |
| Lint, health | `make lint`, `make health` | exit 0, exit 0 |
| Evals | `evals/runner.py --tiers p,i,s,e` | 27 of 27 passed; Tier S observed **159 of 159** SQL assertions, pass rate 100.0 % |
| Deploy | `build/deploy_all.sh` dev, test, staging, prod | exit 0 for all four |
| Full suite | `scripts/test_report.py --markers "not accessibility" --strict` | 1337 collected, 1324 passed, 0 failed, 0 skipped, 13 not run (accessibility, run in the CI accessibility job) |
| Egress blocked | `pytest tests/system --block-egress` | exit 0 |
| Coverage gate | `pytest --cov=api --cov=streamlit_app --cov=build/csv --cov=evals --cov-branch` + `scripts/check_coverage_floors.py` | api 94.4 % (floor 90), streamlit_app 97.5 % (floor 92), csv_parse 92.8 %, dynamic_loader 86.1 %, te_loader 97.4 %; build/csv 0 %, evals 63.5 % (no floor); gate passed |
| Frontend | `npm ci && npx vitest run` in `csv-table-hub-main` | 20 files, 196 of 196 passed |
| Perf (indicative only) | `scripts/perf_import.py --rows 100000` | stage→imported 9.96 s, preview 0.18 s; 32 vCPU / 248 GB VM, **not** the 2 vCPU / 4 GB reference instance |
| Reproduction R1 | two concurrent `alembic upgrade head` on a fresh database, 5 trials | **one of the two failed in 5 of 5 trials** (`UniqueViolation` on `pg_type_typname_nsp_index` for `alembic_version`, or on `pg_namespace` for `csv_uploads`) |
| Reproduction R2 | TestClient, no session, `API_ALLOW_DESTRUCTIVE` off: dynamic upload, then T&E upload of byte-identical content | **T&E upload returned 200 and the dynamic table `csv_repro_dyn_…_v1` was dropped** |

The two reproduction scripts were kept outside the repository (`review_work/`); R2 was copied into `tests/system/` only for the run and deleted afterwards. No application code was changed.

### 6.1 Re-verification of approved requirements at 68399af

"Re-run" means the named tests are present at the baseline and passed in both the local full suite and CI run 44560865716. "Inspected" means the reviewer also read the test and confirmed it exercises the requirement. Where only "Re-run" is shown, the test content was not independently re-inspected in this review, and the earlier assessment stands on its own evidence.

| ID | Status above | Re-verification 2026-11-20 | Result | Owner | Date | Detector |
|---|---|---|---|---|---|---|
| BR-01, BR-03 to BR-09, BR-12 to BR-15 | ✅ | Re-run: Tier S 159/159, Tier I, Tier E 2/2, deploy of all four environments | ✅ confirmed | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-10, BR-11, BR-16 to BR-19 | ✅ | Re-run: Tier P and unit tests in the free tier (870/870) | ✅ confirmed | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-20 | ✅ | Re-run: 159 of 159 pass. The requirement text says 142, and Tier S only asserts `min_total_assertions: 142`, so losing up to 17 assertions would not fail the gate | ✅ pass rate confirmed; count wording stale (E-05, OIT-018) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-23 | ✅ | Re-run `test_preserved_uploads.py`. On the direct `POST /api/csv/upload` path, `record_upload` runs after the load commits and swallows errors (`api/services/originals.py:84-95`); its except branch (lines 93-95) is never executed by any test (coverage). A committed load can exist with no `uploads` row | ⚠️ should be Partial for the direct path (E-06, OIT-003) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-24 | ⚠️ | Same window as BR-23: blob and source rows are stored by `record_upload` after commit | ⚠️ unchanged, extra gap (OIT-003) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-25 to BR-27, BR-29, BR-30 | ✅ / ⚠️ | Re-run `test_review.py`, `test_versioned_datasets.py`, `test_registry_race.py` (inspected: `threading.Barrier` + thread pool, concurrent identical uploads register once) | unchanged | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-28 | ✅ | Inspected `test_registry_race.py` (above) | ✅ confirmed | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-31 | ⚠️ | Reproduction R2: a T&E upload with content identical to a dynamic dataset drops that dataset's table (`api/services/te_loader.py:88-118`, called at 321). With no session the role check returns early (`api/services/destructive_ops.py:48-51`) and `API_ALLOW_DESTRUCTIVE` is not consulted (checked only at `api/routers/csv_routes.py:308`) | ⚠️ unchanged; open item is now a **confirmed defect** (OIT-002) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-32 to BR-34 | ⚠️ | Inspected `test_staged_import.py` `AllOrNothing` (failure injected at every step, retry succeeds). Direct path and T&E mode still bypass staging; T&E commits partial loads by design (`te_loader.py:278-343`), contrary to decision 4 | unchanged | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-35 | ✅ | Inspected `test_audit_append_only.py` (UPDATE, DELETE, TRUNCATE rejected; chain breaks detected; concurrent writers). The note "frontend audit page doesn't call them yet" is stale: `ServerAuditEvents.tsx` is used by `routes/audit.tsx:21,247` (commit f99c7c1). That component has no component test; only `auditEventsQuery` is unit-tested (`audit-events.test.ts`) | ✅ confirmed; note stale (E-04) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-36 | ⚠️ | Re-run tenant, role and OIDC tests. Real IdP (#113) not checkable from the review VM | unchanged | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-37 | ⚠️ | Egress-blocked run exit 0 locally and in CI. Clean-VM offline install (#60) not checkable here | unchanged | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-38 | ⚠️ | Container bundle workflow last ran 44231529683 on 8fba708 (success); `git diff 8fba708 68399af -- container/ api/ csv-table-hub-main/src` is empty, so that run still represents those paths. Windows and macOS hosts, and `install.ps1` on PowerShell 5.1, not run anywhere | unchanged | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-45 | ❌ | No test covers the window. Coverage shows `record_audit`'s except branch (`api/services/audit.py:117-118,122`) is never executed | ❌ unchanged (OIT-003) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-46 | ✅ | vitest 196/196 locally and in CI; `test_streamlit_exports.py` and `test_reports_and_policy.py` passed | ✅ confirmed | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-47 | ⚠️ | `/audit` still reads local jobs from browser storage (`routes/audit.tsx:7,49`); the server events are behind a collapsible panel | ⚠️ unchanged | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-48 | ⚠️ | The evidence text is stale: CI now measures `api`, `streamlit_app`, `build/csv`, `evals` with branch coverage and gates `api/` (90 %) and `streamlit_app/` (92 %). Still no floor for `build/csv` (0 %) or `evals` (63.5 %) | ⚠️ remains Partial; note stale (E-07) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-49 | ⚠️ | Windows job log of run 44560865884 shows `test_preflight_ps1.py` with 16 passing tests; 11 are collected on Linux, so by count the 5 Windows execution tests (parse under `powershell`, run with `-SkipPg`, port label, optional PG checks) ran and passed on `windows-latest`, where `powershell` is Windows PowerShell 5.1. The quiet-mode log does not name them individually. PowerShell 7 execution was not separately evidenced | Recommend ✅ for 5.1; owner to decide whether 7 needs its own run | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |
| BR-D1 to BR-D5 | ✅ | The evidence path `input_data/load_input_data.sql` does not exist in the repository | Unverifiable (E-08) | Amarnath Rasineni | 2026-11-20 | Review 2026-11-20 |

### 6.2 Errata to the sections above (for the owner to apply)

| Erratum | Where | What is wrong | Evidence |
|---|---|---|---|
| E-01 | §3 status table | Counts 26 verified, 9 partial, "❌ Not started 0"; BR-45 is ❌ and BR-46 to BR-49 are missing from it | §2 BR-45 row; headline 2026-11-19 |
| E-02 | §3, "There are no longer any unverified requirements…" | False since 2026-11-19: BR-45 is unverified and not a recorded decision | BR-45 row |
| E-03 | §4 "None outstanding as at 2026-09-10"; §5 "A and D aren't used" | Both stale: §2 now uses I, A and D, and genuine gaps exist (BR-45, OIT list) | §2 table 2026-11-19 |
| E-04 | BR-35 note | "The frontend audit page doesn't call them yet" is no longer true | `routes/audit.tsx:21,247`; f99c7c1 |
| E-05 | BR-20 wording and Tier S threshold | Suite has 159 assertions (README line 5 says 159); requirement and Tier S say 142 | Tier S report 2026-11-20; `evals/expected/tier_s/01_fresh_deploy_then_all_tests_pass.json:10` |
| E-06 | BR-23 ✅ | Holds for the staged flow, not for the direct upload path (post-commit, error-swallowing registry write) | `api/routers/csv_routes.py:120-133`; `api/services/originals.py:84-95` |
| E-07 | BR-48 evidence | Says CI integration job measures `api/services` only; now measures four packages with two package floors | `Makefile` `COVERAGE_SCOPE`; coverage gate output |
| E-08 | Layer legend LV and BR-D1 to BR-D5 | `input_data/load_input_data.sql` is not in the repository | `git ls-files` |

### 6.3 PROPOSED requirements (disposed by the product owner 2026-11-20; see §6.4)

BR-39 to BR-44 remain reserved for the proposals already awaiting disposition. These new proposals start at BR-50. The table is kept as raised on 2026-11-20 for the record; the Approval column now shows each disposition, and §6.4 gives the reasons. The IDs here keep "(proposed)" so the coverage count (`tests/unit/test_gap_registers_agree.py`) reads only the approved rows in §2.

| ID | Proposed requirement | Approval | Method | Acceptance criteria | Verification evidence today | Result | Owner | Date | Detector |
|---|---|---|---|---|---|---|---|---|---|
| BR-50 (proposed) | Schema migrations run at API start shall be safe when two or more API processes start together against the same database. | **APPROVED** 2026-11-20 as BR-50 (§2) | T (concurrent start, fresh and at-head DB) + I | 10 of 10 trials of two concurrent `bootstrap()` (or two API processes) on a fresh DB both start; `alembic_version` = head; no `UniqueViolation`. Test must fail with the fix removed | Reproduction R1: 5 of 5 trials, one process failed (`alembic/env.py:33-40`, no advisory lock; `api/db.py:234-246` only handles `OperationalError`, so `IntegrityError` aborts start-up) | ❌ Fails | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (HANDOFF F5) |
| BR-51 (proposed) | No upload shall drop or replace another dataset's table unless the caller has delete permission **and** `API_ALLOW_DESTRUCTIVE` is enabled; the shared-key path shall not bypass this. | **APPROVED** 2026-11-20 as BR-51 (§2) | T | With the flag off: T&E upload of content identical to a dynamic dataset leaves the dynamic table and registry row in place (or is refused with 403/409), with and without a session | Reproduction R2: table dropped, HTTP 200 | ❌ Fails | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (related #175, BR-31) |
| BR-52 (proposed) | On the direct upload path, the registry row, preserved original and audit row shall commit in the load's transaction, or a reconciliation job shall detect and report any committed load without them. | **MERGED** into BR-45 (wording widened) | T (fault injection) + A | Injected failure in `record_upload` and `record_audit` after the load: either nothing is committed, or a check lists the orphan load. Tests exercise `originals.py:93-95` and `audit.py:117-122` | Not covered (coverage report) | ❌ Not verified | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (refines BR-45, extends to BR-23/24) |
| BR-53 (proposed) | The API shall reject a request body larger than the configured limit before parsing it. | **APPROVED** 2026-11-20 as BR-53 (§2) | T | A body of `MAX_UPLOAD_BYTES` × 2 with an honest and with a missing `Content-Length` is refused with 413 without being fully buffered | Size checked after Pydantic parse (`api/routers/csv_routes.py:71,108`; `import_routes.py:61`) | ❌ Not met | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (SEC F1) |
| BR-54 (proposed) | Unauthenticated endpoints shall not disclose database name, host, port, server version or schema outside `dev`. | **APPROVED** 2026-11-20 as BR-54 (§2) | T + I | With `API_ENV=prod`, `/api/health` returns status only; `/docs`, `/redoc`, `/openapi.json` need auth or are off | `api/main.py:116-138` returns those fields | ❌ Not met | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (SEC F2) |
| BR-55 (proposed) | Secrets shall never be logged, in whole or in part. | **APPROVED** 2026-11-20 as BR-55 (§2) | I + T | Start-up log contains no substring of `API_KEY` (a hash prefix is acceptable) | `api/main.py:61` logs the first four characters | ❌ Not met | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (SEC F10) |
| BR-56 (proposed) | The on-premises/container deployment shall have a documented backup and restore procedure, with a restore test that proves the audit chain verifies after restore. | **MAPPED** to reserved BR-39..44 (backup); uncounted | D + T | Restore drill on the container bundle: data, uploads and `audit_log` restored; `GET /api/audit/verify` passes; RPO/RTO recorded | Only Azure PITR documented (`docs/PROD_DEPLOY.md`); no backup content in `container/` | ❌ Not met | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (may fold into reserved BR-39..44) |
| BR-57 (proposed) | Audit retention (decision 7) and raw-upload purge shall have a defined, tested operator procedure compatible with the append-only triggers. | **MAPPED** to reserved BR-39..44 (disposal); uncounted | I + D | Written procedure; a demonstration on a test DB that purges only rows older than `AUDIT_RETENTION_YEARS` and records the purge | `AUDIT_RETENTION_YEARS` is only validated (`api/policy.py:22-31`); triggers reject DELETE; no procedure found | ❌ Not met | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 |
| BR-58 (proposed) | Import concurrency shall be bounded per API instance (decision 1: 4 concurrent imports). | **APPROVED** 2026-11-20 as BR-58 (§2) | T + A | A 5th concurrent import waits or is refused; pool exhaustion behaviour documented | No semaphore or limit in `api/` (grep); pool fixed at 8 (`api/db.py:24`) | ❌ Not met | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (M0 decision 1) |
| BR-59 (proposed) | The decision-8 performance targets shall be measured on the reference instance and recorded per release. | **MERGED** into BR-22 (deferred to M7) | T (on reference HW) | `PERF_ENFORCE=1 PERF_ROWS=100000` passes on 2 vCPU / 4 GB; timings recorded in this VCRM | Not enforced in CI (`tests/performance/test_import_scale.py:4-7`); indicative 9.96 s on non-reference VM | ⚠️ Not verified | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 (M0 decision 8, M7) |
| BR-60 (proposed) | Changes to `main` shall pass the required CI checks before merge (branch protection enforced). | **DECISION ACTION**, not a BR | I (GitHub settings) + D | `GET /repos/.../branches/main` shows `protected: true` with the Quality Gate jobs required | API on 24 Nov: `protected: true`, five required checks (`python-validator-tests`, `free-tier`, `integration (postgres service)`, `browser`, `accessibility`), branch must be up to date, admins included; see "Applied, 24 Nov 2026" in `DECISIONS/2026-11-02-main-branch-protection.md`. Before that it was decided but not applied (#198) | ✅ Met (24 Nov) | Amarnath Rasineni (proposed; to confirm) | 2026-11-20 | Review 2026-11-20 |

### 6.4 Disposition of BR-50 to BR-60 (product owner, 2026-11-20)

Decided by Amarnath Rasineni (product owner) on 2026-11-20. Applied in this file in the same change as the 2026-11-20 headline (§3).

| Proposal | Disposition | Where it now lives | Reason |
|---|---|---|---|
| BR-50 (proposed) | Approved, new requirement | §2, BR-50 (❌ not started) | Reproduced defect (R1) with no parent requirement |
| BR-51 (proposed) | Approved, new requirement | §2, BR-51 (❌ not started) | Reproduced data-loss path (R2). Folding it into BR-31 as BR-31a was considered and rejected: it would hide a confirmed defect inside an already-partial requirement |
| BR-52 (proposed) | Merged | BR-45, wording widened to cover the registry row and preserved original as well as the audit row | Same defect class and same fix as BR-45 (writes after the load commit); one ID per fix |
| BR-53 (proposed) | Approved, new requirement | §2, BR-53 (❌ not started) | Security control (SEC F1) with no parent requirement |
| BR-54 (proposed) | Approved, new requirement | §2, BR-54 (❌ not started) | Security control (SEC F2) with no parent requirement |
| BR-55 (proposed) | Approved, new requirement | §2, BR-55 (❌ not started) | Security control (SEC F10) with no parent requirement |
| BR-56 (proposed) | Mapped to the reserved set | Reserved BR-39 to BR-44 (backup); stays proposed and uncounted | `docs/HANDOFF-20261104.md` item 28 already reserves numbers for backup; decide it with that set |
| BR-57 (proposed) | Mapped to the reserved set | Reserved BR-39 to BR-44 (disposal); stays proposed and uncounted | As BR-56, for disposal (audit retention, raw-upload purge) |
| BR-58 (proposed) | Approved, new requirement | §2, BR-58 (❌ not started) | Traces M0 decision 1, already approved |
| BR-59 (proposed) | Merged | BR-22 (re-raised row in §2), still deferred by decision; reactivation at M7 | Same subject as BR-22 (performance); a second ID would split one deferred decision |
| BR-60 (proposed) | Decision action, not a requirement | `DECISIONS/2026-11-02-main-branch-protection.md` and #198 | Process control, not product behaviour; applying it needs a repository-admin setting change by the owner |

The retired proposal IDs (BR-52, BR-56, BR-57, BR-59, BR-60) are not reused. When the reserved BR-39 to BR-44 set is decided, BR-56 and BR-57 take numbers from it.

Full issue detail, remediation and dependencies: `docs/Outstanding Items Tracker_Grok.txt`. Reconciliation of earlier audit findings: `docs/AUDIT_RECONCILIATION_2026-11-20.md`.

### 6.5 Disposition of errata E-01 to E-08, and new errata E-09 to E-10 (2026-11-24)

Checked against `main` at `6111019` (24 Nov 2026). Proposed by Claude Code for #302, #303 and #342 on the owner's instruction of 24 Nov; the owner's merge of the pull request that adds this section is the approval. Each applied erratum is marked in place above.

| Erratum | Disposition | What was done | Evidence on 24 Nov |
|---|---|---|---|
| E-01 | Already applied (2026-11-20) | None now. The §3 status table counts 27 verified, 12 partial, 7 not started, 3 deferred: the same as the §2 rows and the latest headline (`tests/unit/test_gap_registers_agree.py`) | §3 note "erratum E-01 in §6.2 applied" |
| E-02 | Accepted, applied | Superseded note above the §3 "no longer any unverified requirements" paragraph | 19 requirements are partial or not started |
| E-03 | Accepted, applied | Superseded notes on §4 "None outstanding" and on the §5 methods limitation | §2 rows BR-45 onwards use I, A and D |
| E-04 | Accepted, applied | BR-35 note corrected | `csv-table-hub-main/src/routes/audit.tsx:21,247` imports and renders `ServerAuditEvents` |
| E-05 | Accepted, applied (documents 24 Nov, threshold 25 Nov) | BR-20 wording and §2 row say 159; `docs/TEST_CONDITIONS.md`, `docs/ARCHITECTURE.md`, `docs/QUICKSTART.md`, `scripts/README.md`, `evals/PLAN.md`, `evals/HANDOFF.md` too. Threshold: `min_total_assertions` raised from 142 to 159 on 25 Nov on the owner's go-ahead (#303), with a negative control and a unit test that keeps it equal to the suite's count | Tier S on PostgreSQL 16, local run 24 Nov: 159 of 159, 100.0 %. 153 `assert_*` call sites plus suite 06's 6 `tf_record` assertions |
| E-06 | Rejected: fixed before disposition | BR-23 stays ✅; its row now cites the fix. The direct upload path writes the registry row, original and audit row in the load's transaction | #321 merged 23 Nov (`eac1a06`, closes #288, OIT-003); `api/routers/csv_routes.py` `record_with_load` passed as `on_commit`. `record_upload` is now used only for attempts that loaded nothing |
| E-07 | Accepted, applied | BR-48 evidence corrected; status stays ⚠️ Partial | `Makefile` `COVERAGE_SCOPE`; `scripts/check_coverage_floors.py` `PACKAGE_FLOORS`; no floor for `build/csv` or `evals` (#304) |
| E-08 | Accepted, applied | Note on the LV legend and on the BR-D1 to BR-D5 table: kept as history, not counted | `git ls-files` has no `input_data/` |
| E-09 (new) | Applied | BR-02 row and §4 BR-02 entry: Teradata defines 12 tables, not 1. Also corrected in ADR-0001 (amendment), `docs/RECONCILED_GAPS.md` and `docs/VCRM_GAPS.md`; `docs/ENGINE_PARITY_TODO.md` and `docs/GAP_ANALYSIS.md` were corrected on 23 Nov. BR-02 stays deferred | `build/schema/teradata/te_core_schema.sql`: 12 `CREATE SET TABLE` statements, one per reference table; the only `CREATE TABLE` match is the comment on line 32 (#342) |
| E-10 (new) | Applied | §3 "By layer" recounted from the §2 cells: PU 4 (was "5" beside four IDs), TP 3 (BR-18's TP cell is "—"), TS 15 (BR-17 was left out) | §2 matrix |

**Applied 2026-11-25 (owner's go-ahead of 24 Nov).** BR-45, BR-50, BR-51, BR-53, BR-54, BR-55 and BR-58 were re-checked against their acceptance criteria and are now ✅ in §2, with the evidence in each row and a new headline in §3. Earlier in this section they were listed here as found but not applied. The Tier S threshold (E-05) was raised from 142 to 159 in the same change, with a negative control: one assertion removed, Tier S failed with `total_assertions: expected >= 159, got 158`; `tests/unit/test_tier_s_threshold.py` now keeps the threshold equal to the suite's count.
