# ART Milestone 0 — Assessment and Plan

**Branch:** `art-milestone-0` · **Baseline commit:** `main` @ 032b522 · **Date:** 2026-10-26
**Prompt:** [`docs/prompts/ART_FRAMEWORK.md`](../prompts/ART_FRAMEWORK.md) (v2) · **Issue:** #53
**Status:** For product-owner approval. No production code has been changed.

This document covers Milestone 0 steps 1, 2, 3, 5 and 6. Step 4 is the two proposed ADRs:
[ADR-0002](../adr/0002-transactional-staged-import.md) and [ADR-0003](../adr/0003-customer-facing-multi-tenant.md).

---

## 1. Baseline

All counts below are from actual runs. Nothing has been inferred from documentation.

| Check | Command | Result | Where run |
|---|---|---|---|
| Python lint | `bash scripts/lint.sh` (flake8 + bandit) | Clean (flake8 clean, bandit clean) | Local, Python 3.13 |
| Python unit tests | `pytest -m "not integration and not e2e and not parity"` | 119 passed, 0 failed, 0 skipped, 120 deselected | Local (no PostgreSQL) |
| Full Python suite | `python3 scripts/test_report.py --strict` | 239 collected, 239 passed, 0 failed, 0 skipped | CI run 40245755345 on 032b522, PostgreSQL 16 |
| Evals | `evals/runner.py --tiers p,i,s,e` | 26 total, 26 passed, 0 failed, 0 skipped | CI run 40245755345 |
| Evals, offline tier | `evals/runner.py --tiers p` | 23 passed, 0 failed, 0 skipped | Local |
| Frontend tests | `npx vitest run` | 8 files, 102 passed | Local, Node 22 |
| Frontend types | `npx tsc --noEmit` | Exit 0 | Local |
| Frontend lint | `npx eslint .` | **524 errors, 2 warnings.** 517 are `prettier/prettier` formatting; 7 are code rules (4 `no-explicit-any`, 2 `no-unused-expressions`, 1 `no-unused-vars`) | Local |

**Reading the baseline:**

- The integration-dependent counts come from CI. No PostgreSQL was available in this assessment environment.
- Frontend lint is not gated in CI and has never been clean. It is pre-existing debt, not an ART regression. Recommendation: clear it once with `prettier --write` in its own PR before ART frontend work starts, so later diffs stay reviewable.

---

## 2. Live code against BR-23 to BR-37

**Correction to the prompt's premise.** The prompt says the API shells out to the bash loaders. It does not. Neither `api/` nor anything it imports uses `subprocess`. Uploads load in-process through `api/services/dynamic_loader.py` and `api/services/te_loader.py`, each inside its own psycopg2 transaction. The `build/csv/loader_*.sh` scripts are used only by the batch pipeline (`build/csv_loader.sh`) and the e2e tests. ADR-0002 reflects this.

**ID check.** `docs/VCRM.md` runs BR-01 to BR-22. None of the existing BRs covers SHA-256 deduplication, the upload registry or the audit log; those were tracked as gaps (O-02, O-04), not requirements. So the provisional IDs BR-23 to BR-37 stand. Overlaps with existing BRs are noted in step 3.

| BR | Requirement (short) | Status | Evidence (file:line) | Proving test today |
|---|---|---|---|---|
| BR-23 | Upload registry with ID, filename, SHA-256, uploader, tenant, timestamp, status | **Partial** | `csv_files` has id, file_name, file_hash, table_name, mode, row_count, column_names, created_at (`api/db.py:199-208`). No uploader, tenant or processing status. | `test_api_coverage.py` files-list tests (integration) |
| BR-24 | Original file and parsed source preserved immutably | **Missing** | The original file is never stored. Only cast, typed rows land (`dynamic_loader.py:300-319`). Rows that fail to cast are dropped from the data, with at most 200 reported (`dynamic_loader.py:268-277`). Overwrite runs `DROP TABLE` on the prior import (`dynamic_loader.py:159-168`, `194-203`). | None |
| BR-25 | Interactive preview of all rows and columns, with inference and validation | **Partial** | The preview returns 10 sample rows and infers types from the first 200 (`csv_parse.py:237`, `254-255`). Viewing an imported table is capped at 200 rows (`csv_routes.py:125`). No full-dataset paging. | `preview-contract.test.ts`, `test_api_coverage.py` preview tests |
| BR-26 | Row include/exclude with actor and reason | **Missing** | No code path. | None |
| BR-27 | Cell edits as versions over the original | **Missing** | No code path. | None |
| BR-28 | SHA-256 exact-file duplicate detection, within and across uploads, per tenant | **Partial** | Hash computed (`dynamic_loader.py:58`); checked against the registry (`171-191`). It is global, not per tenant. **Defect F1:** the race guard relies on "the registry's UNIQUE indexes" (`dynamic_loader.py:321-336`), but no unique index exists on `csv_files` anywhere in the repo (`db.py:199-208`; no Alembic migrations exist). | `test_overwrite_false_refuses_duplicate` (integration) |
| BR-29 | Configurable duplicate-record detection within and across uploads | **Partial** | Exact whole-row hash within one file (`dynamic_loader.py:281-289`, `ON CONFLICT (_row_hash)` at `312`). Each file gets its own table, so there is no cross-upload detection, and the rule is not configurable. | `test_in_file_duplicate_rows_are_skipped`, `test_row_hash_*` (integration) |
| BR-30 | Safe filename-derived table names; repeated same-filename uploads supported | **Partial** | Names are safe but content-derived, `csv_<sha256[:16]>` (`dynamic_loader.py:236`), not filename-derived. A repeat of the same filename is refused, or replaced destructively with `overwrite` (`144-168`). | `test_injection_shaped_names_are_not_served` (integration) |
| BR-31 | Schema compatibility checks; no destructive schema changes | **Partial** | T&E mode checks headers against the fixed schema (`te_loader.py:45-82`). Dynamic mode always creates a new table, so there is nothing to check against. Overwrite drops tables (see BR-24). | `test_te_loader_integration.py` |
| BR-32 | Approval workflow with recorded approver and decision | **Missing** | No code path. | None |
| BR-33 | Staged, transactional, idempotent import; rows traceable to source and approved version | **Partial** | A dynamic upload is one transaction (`Conn()` at `dynamic_loader.py:131`, commit at `356`). T&E mode isolates failing rows with savepoints and commits the rest, so partial import is by design (`te_loader.py`, commit at `301`). The audit row is written post-commit in a separate transaction (`csv_routes.py:86-93`; `audit.py:9-22`). No staging, no approval link, no source-row lineage. | Upload integration tests |
| BR-34 | Reconciliation: rows in, excluded, edited, imported account for each other | **Partial** | The response returns totalRows, insertedRows, duplicateRowsSkipped and failedRows (`dynamic_loader.py:359-372`), but they are not persisted; the registry keeps `row_count` only. **Defect F2:** cells beyond the header width are silently ignored in both modes (`dynamic_loader.py:263-264`, `te_loader.py:221`), so they appear in no count. | `test_issue_05_import_summary.py` |
| BR-35 | DB-enforced append-only audit; filterable reports; formula-safe exports | **Partial** | `audit_log` is an ordinary table (`db.py:215-223`). Only `upload` and `delete` are recorded (`audit.py:38`), with no actor. `GET /api/audit/log` pages but does not filter (`audit_routes.py:27-29`). The frontend audit page reads browser `localStorage`, not the server log. **Defect F3:** CSV export escapes quotes and commas but not leading `= + - @` (`csv-table-hub-main/src/lib/export.ts:43-46`). | `test_audit_*` (integration), `test_delete_appears_in_audit_log` |
| BR-36 | Authentication, role-based authorisation, tenant isolation | **Missing** (key gate only) | One shared `X-API-Key` compared in constant time (`api/auth.py:21-26`). The API refuses to start outside `dev` without it (`api/main.py`). No users, roles or tenants. | `test_csv_endpoint_still_requires_api_key_when_set` (integration) |
| BR-37 | Classification and sovereignty: no runtime external services; offline install | **Partial** | No outbound calls found in `api/`, and no CDN, analytics or telemetry references in `csv-table-hub-main/src` (grep, 2026-10-26). There is no automated check for this. The offline install doc does not exist (#60). Classification level is undecided (#49). | None |

**Defects found during the assessment.** These are real today, independent of ART, and each now has a GitHub issue:

- **F1 (#81). Registry race guard missing.** Concurrent identical uploads can both register, because the unique indexes the code relies on were never created.
- **F2 (#82). Extra cells silently dropped.** In both import modes, a data row wider than the header loses its extra values without being reported. This contradicts BR-10 and the ART data-preservation constraint.
- **F3 (#83). Spreadsheet formula injection in CSV export.** Error and audit report exports write user-supplied cells starting with `=`, `+`, `-` or `@` unchanged.
- **F4 (#84). No schema migration framework.** `alembic.ini` does not exist, so `bootstrap()` always takes the fallback path (`db.py:165-172`). Every ART schema change needs versioned migrations first.

---

## 3. Draft VCRM rows

Proposed additions to `docs/VCRM.md` §1 and §2. They are not applied yet, because requirement wording is the product owner's call. Each will be written to the VCRM when its milestone starts (D5).

| ID | Requirement | Overlaps | Initial status | Reason | Verification (planned) | Milestone |
|---|---|---|---|---|---|---|
| BR-23 | Every upload is registered with a unique ID, original filename, SHA-256, uploader, tenant, timestamp and processing status. | — | ⚠️ Partial | Registry exists without uploader, tenant, status | Integration + DB constraint tests | M1, M3 |
| BR-24 | The original file and its parsed source rows are preserved immutably, separate from edits and approved data. | — | ❌ Not started | Original never stored; overwrite drops data | DB negative tests (update/delete refused) | M3 |
| BR-25 | Users can page through every row and column of an upload, with inferred types and validation results. | BR-10 | ⚠️ Partial | 10-row sample, 200-row cap | API paging tests + e2e | M4 |
| BR-26 | Rows can be included or excluded; each decision records actor and reason. | BR-11 | ❌ Not started | No code | API + e2e | M4 |
| BR-27 | Cell edits are stored as versions over the original, with old and new value, actor, time and reason. | — | ❌ Not started | No code | API + DB tests | M4 |
| BR-28 | Exact-file duplicates are detected by SHA-256 within and across uploads, per tenant. | — | ⚠️ Partial | Global not per tenant; race guard missing (F1) | Concurrency + cross-tenant tests | M1, M5 |
| BR-29 | Duplicate records are detected within and across uploads using a configurable rule. | — | ⚠️ Partial | In-file exact match only | Unit + integration | M5 |
| BR-30 | Table names are safely derived from filenames, and repeated uploads of a filename are supported without overwriting. | — | ⚠️ Partial | Content-derived names; repeats refused or destructive | Unit + integration | M5 |
| BR-31 | Imports check schema compatibility and never make destructive schema changes. | — | ⚠️ Partial | T&E mode only; overwrite drops tables | Integration | M5 |
| BR-32 | Imports require submission and an approve or reject decision with a recorded approver. | — | ❌ Not started | No code | API + e2e | M6 |
| BR-33 | Imports are staged, transactional and idempotent with safe retries; every imported row traces to its source row and approved version. | BR-09 (idempotency, deploy level) | ⚠️ Partial | Single-transaction load, no staging or lineage | Integration incl. failure injection | M6 |
| BR-34 | Rows in, excluded, edited and imported reconcile exactly and are persisted per import. | — | ⚠️ Partial | Counts returned, not persisted; F2 | Integration | M1, M6 |
| BR-35 | Audit events are append-only at database level; reports are filterable; exports neutralise formula injection. | — | ⚠️ Partial | Plain table, no actor, no filters, F3 | DB negative tests + unit | M1, M3, M7 |
| BR-36 | Users authenticate; access is role-based; no tenant can read or affect another tenant's data. | — | ❌ Not started | Shared key only | Cross-tenant negative tests | M2 |
| BR-37 | Data stays inside the deployment boundary; no runtime external services; the stack installs offline. | — | ⚠️ Partial | No external calls found; no automated check; no offline doc | Egress-blocked test run + offline dry run | M7 |

**Success measures** (Altitude) map onto these rows: preview completeness → BR-25; duplicate accuracy → BR-28, BR-29; reconciliation → BR-34; audit coverage → BR-35; data integrity → BR-24, BR-33; tenant isolation → BR-36; security → BR-35, BR-36; sovereignty → BR-37. Performance targets wait on decision 8. **BR-22 (≥ 1 M rows) stays deferred by decision**; the ART targets apply to the capped path.

---

## 5. Proposed design

### Architecture

The current shape stays: React/TS frontend → FastAPI → PostgreSQL. Three additions:

- **Identity and tenancy layer.** Authenticated users carry a tenant and a role. Every request is scoped to one tenant's schema.
- **Dataset lifecycle.** An upload becomes a dataset version that moves through `uploaded → in_review → submitted → approved | rejected → imported | failed`.
- **Audit store.** Append-only, written in the same transaction as the change it records.

### Data model (per tenant schema, plus a shared `control` schema)

- `control.tenants`, `control.users`, `control.memberships(user, tenant, role)`
- `uploads`: registry. Columns: id, tenant, original_filename, sha256, uploader, created_at, status, byte_size, row_count. UNIQUE (sha256).
- `upload_blobs`: original file bytes. Insert only.
- `source_rows`: parsed rows as text, with row_number. Insert only. This is the immutable original.
- `row_decisions`: include/exclude, actor, reason, at.
- `cell_edits`: row, column, old, new, actor, reason, at. Versioned and never updated.
- `approvals`: submission, decision, approver, reason, at.
- `imports`: one row per approved import. Columns: idempotency key, counts (in, excluded, edited, imported), status, target table, lineage pointer.
- `audit_events`: tenant, actor, action, object references, before and after, at, prev_hash.
- Target tables: `<filename_slug>_v<n>`, with `_source_row_id` and `_import_id` columns for lineage.

### API (additions)

- `POST /api/uploads`: register and store the original.
- `GET /api/uploads/{id}/rows?page=`: full paging with validation flags.
- `PUT /api/uploads/{id}/rows/{n}/decision`, `PUT /api/uploads/{id}/cells`: review actions.
- `POST /api/uploads/{id}/submit`, `POST /api/uploads/{id}/approval`: workflow.
- `POST /api/uploads/{id}/import` with an `Idempotency-Key` header.
- `GET /api/audit/events?actor=&action=&from=&to=`: filtered reports.

Errors keep the existing structured `{status, reason, message}` contract. The existing `/api/csv/*` endpoints stay until the frontend moves over.

### Key mechanisms

- **Parsing.** Keep `csv_parse.py`, which is dependency-free and already mirrored in the frontend. Reject ragged rows instead of truncating them (F2).
- **File deduplication.** SHA-256 per tenant, enforced by a UNIQUE constraint rather than check-then-act (F1).
- **Record deduplication.** Default is an exact match on normalised whole-row content. The rule can be configured per dataset as a set of key columns. Matches across earlier imports of the same dataset are found through an indexed `_row_key` hash.
- **Naming.** Lower-case ASCII slug of the filename, truncated, then `_v<n>`, through `sql.Identifier`. Versioned datasets, never overwrite (decision 2).
- **Staging and import.** Per ADR-0002: the API owns one transaction. COPY into staging, apply decisions and edits, insert into the target, write the import record and audit events, then commit. Retries use the idempotency key.
- **Append-only audit.** A dedicated table owned by a migration role. The application role gets INSERT and SELECT only, with no UPDATE or DELETE grant. A trigger rejects UPDATE and DELETE even for the owner, and a `prev_hash` chain detects tampering. Negative tests attempt both.
- **Authentication.** Has to work offline, so no SaaS IdP. Recommended: OIDC against an IdP the deployment controls, such as Keycloak or Entra ID where the deployment allows, with a local-account fallback for air-gapped installs. This is open for your decision under ADR-0003.
- **Tenant isolation.** Schema per tenant (decision 6), using `SET LOCAL search_path` and per-tenant roles inside each request's transaction. Cross-tenant negative tests are part of every milestone from M2 onwards.
- **Operations.** Structured JSON logs with no row content. The existing `/api/health`. Rate limits stay; they are per instance, which is acceptable until scaling out. Recovery depends on the transaction plus the idempotency key, so a failed import leaves nothing behind.

---

## 5b. Milestone plan

Each milestone is one PR (or a small set), independently testable, and updates its VCRM rows with quoted run counts.

| # | Milestone | BRs | Verified by |
|---|---|---|---|
| M1 | **Foundations and defect fixes:** Alembic baseline of the current schema (F4); UNIQUE on registry hash (F1); reject ragged rows (F2); neutralise formula injection in exports (F3); persist import counts | BR-23 (part), BR-28 (part), BR-34 (part), BR-35 (part) | Migration up/down test; concurrent-upload test; ragged-row and formula unit tests |
| M2 | **Identity and tenancy:** users, roles, tenants, auth, schema-per-tenant routing | BR-36 | Cross-tenant read and write negative tests; role matrix tests |
| M3 | **Immutable source and append-only audit:** store blobs and source rows; `audit_events` with grants, trigger and hash chain | BR-23, BR-24, BR-35 | UPDATE and DELETE attempts fail; hash-chain verification test |
| M4 | **Review:** full paging, include/exclude, versioned cell edits (API and UI) | BR-25, BR-26, BR-27 | API tests + e2e |
| M5 | **Deduplication and naming:** per-tenant file dedup, configurable record dedup across uploads, versioned dataset naming, schema compatibility | BR-28, BR-29, BR-30, BR-31 | Repeated-file, same-name-different-content and cross-upload duplicate tests |
| M6 | **Approval and transactional import** (ADR-0002): submit/approve/reject, staged COPY and promote, idempotency, lineage, reconciliation | BR-32, BR-33, BR-34 | Rejected-then-resubmitted, failure injection mid-import, retry and concurrent import tests |
| M7 | **Sovereignty and reports:** offline install (#60), egress-blocked test run, classification settings, filtered audit reports, performance targets | BR-35, BR-37 | Offline dry run; test suite with network egress blocked; perf run |

M7's offline-install part can run in parallel with M1 to meet the 15 Nov deadline.

---

## 6. Decisions needed (with recommended defaults)

| # | Decision | Recommended default | Trade-off |
|---|---|---|---|
| 1 | Max file size and concurrency | Keep 50 MB and 100,000 rows (current config); 4 concurrent imports per API instance | Larger files need streaming upload and background jobs, a separate milestone |
| 2 | Repeated uploads of the same filename | **Versioned datasets** (`<name>_v<n>`); never overwrite | Users see several versions; an "append to dataset" option can come later |
| 3 | Duplicate-record rule and policy | Exact whole-row match; policy **flag**, with the user deciding per row | Merge needs per-column rules; skip hides data |
| 4 | Partial imports | **Not permitted.** All approved rows import or none do; exclusions are explicit | A file with bad rows needs review before import |
| 5 | Can an uploader approve their own data? | **No by default**; a per-tenant setting allows it for single-user tenants | Slower for small teams |
| 6 | Tenant model | **Schema per tenant** | Migrations run across N schemas; RLS on dynamically created tables would be harder |
| 7 | Classification and retention | Design target **OFFICIAL: Sensitive**; raw uploads kept until a recorded purge; audit kept 7 years by default (configurable, confirm against the client's records authority) | PROTECTED would add IRAP-assessed hosting and ISM PROTECTED controls (#49) |
| 8 | Performance targets and environment | 100,000-row import under 60 s and first preview page under 2 s on a 2 vCPU / 4 GB instance; Azure Container Apps plus an on-prem docker compose | Targets need a perf harness (M7); BR-22 stays deferred |
| 9 | PR #40 and csv-table-hub PR #1 | **Close both:** outside the React/TS constraint | Loses the plain-HTML fallback (#50) |

**Next step:** approve or amend ADR-0002, ADR-0003 and the nine decisions. M1 starts only after approval.
