# Audit reconciliation, 2026-11-20

Reconciles every earlier audit finding against the code and test evidence at `main` `68399af365d6c076b0fc43ce5c91f3165e44844d`. Each finding is marked **Open**, **Resolved**, **Partial** or **Unverifiable**, using evidence from this review, not earlier claims.

- Reviewer: Claude, an Anthropic model, running as the Abacus.AI agent. The exact model version is not available to the reviewer, so none is given.
- Evidence key: **CI** = Quality Gate run 44560865716 and Python Validator Tests run 44560865884, both success at the baseline. **Local** = replay on the review VM (PostgreSQL 16.16), detailed in `docs/VCRM.md` §6. **R1**, **R2** = the two reproductions in `docs/VCRM.md` §6. **OIT-nnn** = item in `docs/Outstanding Items Tracker_Grok.txt`.
- Source reports: `docs/HANDOFF-20261104.md` §7 (baseline c7bebd1), `docs/SECURITY_REVIEW_PACK.md` §8, `docs/art/milestone-0-assessment.md` §2 and §6 (baseline 032b522), `docs/GAP_ANALYSIS.md`.
- The source reports are not rewritten. A short pointer to this file is appended at the end of the HANDOFF and the security pack.

## 1. What is merged and what is not

- Open pull requests: **none** (GitHub API, 2026-11-20).
- 40 remote branches are fully merged (0 commits ahead of `main`).
- Seven branches have commits that are not on `main`. None of their content is counted as delivered:

| Branch | Ahead / behind `main` | Assessment |
|---|---|---|
| `fix/gap-register-reconciliation-279` | 1 / 0 | Docs-only commit 274d3bd (2026-11-20) to `docs/GAP_ANALYSIS.md`. It links to `docs/GAP_REGISTER_RECONCILIATION.md`, which does not exist on that branch (dangling link). No PR is open. |
| `claude/streamlit-migration-plan` | 11 / 33 | Streamlit work. Equivalent features appear on `main` through later PRs; not compared line by line. |
| `fix/172-prod-db-naming` | 1 / 248 | Looks superseded: `main` has 468c2ae fixing #172. |
| `fix/181-sql-suite-exit-code` | 1 / 250 | Looks superseded: `main` has the #181 regression tests (`tests/unit/test_tooling_issues.py`). |
| `fix/test-staging-db-naming` | 2 / 248 | Stale; not assessed in detail. |
| `web-plain-frontend` | 1 / 399 | Parked (M0 decision 9). |
| `wip/cosmetic-sign-in` | 1 / 389 | Parked (#47). |

## 2. HANDOFF-20261104 §7

### 7A. Coverage and measurement

| ID | Status now | Evidence at 68399af |
|---|---|---|
| A1 | Resolved | CI and `Makefile` `COVERAGE_SCOPE` measure `api`, `streamlit_app`, `build/csv`, `evals` with branch coverage; `scripts/check_coverage_floors.py` gates loaders and packages. Local: api 94.4 %, loaders 92.8 / 86.1 / 97.4 % |
| A2 | Resolved | `evals/gap_report.py` now 81 % (local coverage JSON) |
| A3 | Open (accepted limitation) | `build/csv` measures 0 %: the validator runs as a subprocess; no floor (OIT-019) |
| A4 | Partial | Some scripts are now tested (for example `check_coverage_floors.py`, `check_oidc.py`); a full script inventory was not repeated |
| A5 | Unverifiable | No coverage tool for shell and PowerShell; not re-inventoried |
| A6 | Partial | vitest 196/196 locally and in CI; frontend line coverage not measured. `ServerAuditEvents.tsx` has no component test (OIT-026) |
| A7 | Resolved | Correction stands; loaders measured and gated |

### 7B. Defects from the feedback

| ID | Status now | Evidence |
|---|---|---|
| B1 | Resolved | `tests/system/test_registry_race.py` runs concurrent uploads behind a `threading.Barrier`; passed locally and in CI |
| B2 | Resolved | `tests/system/test_ragged_rows.py` passed; T&E path reports extra cells (`api/services/te_loader.py:243-247`) |
| B3 | Resolved | BR-46: CSV and XLSX guarded in `export.ts`, backend guarded in `api/services/reports.py` and `streamlit_app/exports.py`; tests passed |
| B4 | Partial | Dynamic mode now records confirmed types (`types_confirmed`, #195, `dynamic_loader.py:127,190`) and the staged flow needs approval; the direct `POST /api/csv/upload` path still creates a table without approval (BR-32 open) |

### 7C. Test document

| ID | Status now | Evidence |
|---|---|---|
| C1, C2, C5, C8 | Unverifiable | Owner decisions on the external source test document; not in the repo |
| C3 | Partial | The suite now records 159 assertion rows (Tier S report, local); BR-20 and Tier S still say 142 (OIT-018) |
| C4 | Partial | Hash chain exists (migration 0006; `test_audit_append_only.py` passed). `API_ALLOW_PROD_LOAD` appears nowhere except the HANDOFF itself (`git grep`), so ENV014 describes a feature that does not exist |
| C6 | Resolved | Entry points have been run: local full suite 1324 passed; CI success |
| C7 | Resolved for this review | This review pins `68399af…`; the source document is still the owner's to update |

### 7D. Tracking and process

| ID | Status now | Evidence |
|---|---|---|
| D1, D3 | Unverifiable | Owner decisions |
| D2 | Partial | This review adds a repo snapshot of the tracker (`docs/Outstanding Items Tracker_Grok.txt`), as `DECISIONS/2026-11-02-tracker-long-term-home.md` asks; the Claude Artifact tracker was not accessible to the reviewer |
| D4 | Unverifiable | Tooling of an earlier session |
| D5 | Resolved | `git check-ignore -v build/config.local.env` → `.gitignore:3:*.local.env` |

### 7E. Environment and CI

| ID | Status now | Evidence |
|---|---|---|
| E1 | Resolved | Integration job 135689468879 in run 44560865716: success |
| E2 | Unverifiable | Azure live state not accessible to the reviewer |
| E3 | Resolved | #180, #181, #182 regression tests in `tests/unit/test_tooling_issues.py` (classes `EvalRunnerStopsOnSqlErrors`, `SqlWrapperFailsOnAssertionFailures`, `OfflineBundleStopsOnDownloadFailure`) passed |

### 7F. Findings from the attached debate

| ID | Status now | Evidence |
|---|---|---|
| F1 | Resolved | See A1 |
| F2 | Resolved | `Makefile` lines 35-37 now state fail-not-skip |
| F3 | Resolved | `pytest.ini:17` `addopts = -ra -q --strict-markers` |
| F4 | Resolved (documented) | `env.dev.example:11` `PGPORT=5433`; README lines 194-195 and 310 name the template as authoritative and explain the 5432 fallback in `api/config.py` |
| F5 | **Open, now confirmed** | R1: two concurrent `alembic upgrade head` on a fresh DB, one fails in 5 of 5 trials. `alembic/env.py:33-40` has no advisory lock; `api/db.py:234-246` handles only `OperationalError`, so the `IntegrityError` aborts start-up (OIT-001, proposed BR-50) |
| F6 | Resolved | README line 5 now says "Not yet production-ready" |
| F7, F18 | Resolved | `.dockerignore:16,42-43` `**/*.tfvars`, `**/*.tfvars.json` (#280) |
| F8 | Open | `preflight.sh:108` still calls `timeout` with no macOS fallback (OIT-027) |
| F9 | Partial | `.coverage` still gitignored (`.gitignore:64-65`), but CI prints the coverage table and floors in the integration job log |
| F10 | Resolved (as a finding) | Default confirmed at `api/config.py:59` (100000) |
| F11 | **Open, confirmed in code** | `api/routers/csv_routes.py:120-147`: load commits, then `record_upload` (133), then `record_audit` (141), each in its own transaction and each swallowing errors (`audit.py:117-122`, `originals.py:93-95`); those except branches are never executed by any test (local coverage). The crash itself was not reproduced (OIT-003, BR-45, proposed BR-52) |
| F12 | Resolved | Owner and date recorded for BR-21 and BR-22 (VCRM §2, 2026-11-19); production claim withdrawn (F6) |
| F13, F14, F16, F17 | Resolved (unchanged) | Fixes still on `main`; BR-49 Windows run evidence in the Windows job log |
| F15 | Resolved (not a defect) | Unchanged |

## 3. SECURITY_REVIEW_PACK §8

The review record (§10) is still empty: no reviewer has decided fix, accept or defer for any finding (OIT-031).

| ID | Status now | Evidence at 68399af |
|---|---|---|
| F1 | Open | Size checked after Pydantic parse: `api/routers/csv_routes.py:71,98,108`, `import_routes.py:61,65`; no body-size middleware in `api/` (OIT-005, BR-53) |
| F2 | Open | `api/main.py:116-138` returns database, host:port, PostgreSQL version and schema; no `docs_url`/`openapi_url` override in `api/` (OIT-006, BR-54) |
| F3 | Open | `api/ratelimit.py:90-101` keys on peer IP and ignores `X-Forwarded-For`; counters per instance (OIT-008) |
| F4 | Open | `api/services/accounts.py:20` `_N, _R, _P = 2**14, 8, 1` (OIT-009) |
| F5 | Open | Lockout per username (`accounts.py:161-171`) (OIT-010) |
| F6 | Open | Fixed expiry at `accounts.py:153`; no idle timeout; no `DELETE` of sessions in `api/` or `scripts/` (OIT-011) |
| F7 | Open | One runtime role granted on every tenant schema (`api/db.py:288` `grant_runtime`) (OIT-012) |
| F8 | Open | Shared key path: `_require_delete` returns early when there is no session (`api/services/destructive_ops.py:48-51`). R2 shows a concrete consequence (OIT-013, OIT-002) |
| F9 | Open in code; live state Unverifiable | `infra/terraform-prod/main.tf:183,329` `public_network_access_enabled = true` with "flip to false after bootstrap" (OIT-014) |
| F10 | Open | `api/main.py:61` logs `API_KEY[:4]` (OIT-007, BR-55) |
| F11 | Open | `SECURITY.md:21-22` Gmail placeholder (#57) (OIT-015) |

## 4. Milestone 0 assessment

### Defects

| ID | Status now | Evidence |
|---|---|---|
| F1 (#81) | Resolved | UNIQUE constraints (migration 0002); `test_registry_race.py` passed |
| F2 (#82) | Resolved | `test_ragged_rows.py` passed |
| F3 (#83) | Resolved | BR-46 verified |
| F4 (#84) | Resolved | Alembic migrations 0001 to 0011; `test_migrations.py` passed. New related issue: migrations at start-up are not concurrency-safe (R1, OIT-001) |

### Milestone plan M1 to M7 against delivery

| Milestone | Status now | Evidence / gap |
|---|---|---|
| M1 | Delivered | F1 to F4 resolved; counts persisted (`test_import_counts.py`) |
| M2 | Delivered, open items | Real IdP (#113) unverified; shared key (SEC F8); per-tenant roles in the M0 design (§5, "per-tenant roles") not implemented (SEC F7) |
| M3 | Delivered for the staged flow | Direct path writes registry, original and audit after commit (OIT-003) |
| M4 | Delivered | BR-25 to BR-27 ✅; tests passed |
| M5 | Delivered with one confirmed defect | BR-31: T&E upload drops a dynamic table (R2, OIT-002) |
| M6 | Delivered for dynamic mode via the staged flow | Direct path and T&E mode bypass approval and staging; T&E commits partial loads (`te_loader.py:278-343`) contrary to decision 4 (OIT-004) |
| M7 | Partial | Filtered reports and egress-blocked run delivered. Offline clean-VM dry run (#60) not done; perf targets not measured on the reference instance (OIT-023) |

### Decisions 1 to 9 against implementation

| Decision | Status now | Evidence |
|---|---|---|
| 1 (50 MB, 100k rows, 4 concurrent imports) | Partial | Size and row caps present (`api/config.py:59`); no concurrent-import limit found in `api/` (OIT-022) |
| 2 (versioned datasets) | Implemented, one exception | T&E upload can still drop a dynamic version (R2) |
| 3 (exact match, flag) | Implemented | BR-29 partial for configurable rule |
| 4 (no partial imports) | Partial | Staged flow all-or-nothing (`AllOrNothing` tests); T&E direct path commits partial loads (OIT-004) |
| 5 (no self-approval) | Implemented | `test_staged_import.py` self-approval tests passed |
| 6 (schema per tenant) | Implemented | `test_tenant_isolation.py` passed; isolation is application-level (SEC F7) |
| 7 (classification, retention) | Partial | Classification checked at start-up; retention is a config value only, with no purge procedure compatible with the append-only triggers (OIT-021) |
| 8 (perf targets) | Not verified | `tests/performance/test_import_scale.py` asserts targets only with `PERF_ENFORCE=1`; indicative local run 9.96 s on non-reference hardware (OIT-023) |
| 9 (close PR #40 etc.) | Implemented | Branches parked, not merged |

## 5. GAP_ANALYSIS

| ID | Status now | Evidence |
|---|---|---|
| G1, G4 | Resolved (unchanged) | Per the document's own evidence; G4 re-confirmed by `git check-ignore` |
| G2 | Open, accepted | Windows CI runs 875 DB-free tests; DB-backed tests run on Ubuntu only (run 44560865884) |
| G3 | Closed by decision | ADR-0001 |
| G5 | **Superseded** | "BR-20 confirmed at 142" no longer matches: the suite records 159 (OIT-018) |

## 6. New findings from this review (not in any earlier report)

| Tracker | Finding | Class |
|---|---|---|
| OIT-001 | Concurrent start-up migrations fail (R1) | CONFIRMED (reproduced at the `alembic upgrade head` level; two full API processes not started) |
| OIT-002 | T&E upload drops a dynamic dataset table without `API_ALLOW_DESTRUCTIVE` (R2) | CONFIRMED (reproduced) |
| OIT-003 | Direct-path registry, original and audit writes are post-commit and error-swallowing; failure branches untested | CONFIRMED by code and coverage; crash window not reproduced |
| OIT-016 | Branch protection still off on `main`; `claude/project-status.md` lines 34 and 49 still say it was applied | CONFIRMED (GitHub API) |
| OIT-017 | VCRM internal inconsistencies (errata E-01 to E-08) | CONFIRMED (inspection) |
| OIT-018 | Tier S threshold 142 lets up to 17 assertions disappear unnoticed | CONFIRMED (inspection + local run) |
| OIT-020 | No backup and restore procedure or test for the container bundle | CONFIRMED absence (inspection); impact UNVERIFIED |
| OIT-022 | No concurrent-import limit (decision 1) | CONFIRMED absence (grep) |
| OIT-028 | Fallback bootstrap creates a non-append-only `audit_log` if `alembic.ini` is missing | UNVERIFIED risk (packaging-dependent) |
