# Which test verifies which issue

Every issue in the tracker at 9 Nov 2026 (46 closed, 23 open), with the test that fails if it comes back, or the reason there is none.
Hand-kept: when you close an issue, add its row. State as of 10 Nov 2026 (M5, M6, M7 and #229 merged). `docs/TEST_CASES.md` (generated) lists every pytest test; this file answers "is issue N guarded?".

Legend: **✅** guarded by a test · **⚠️** guarded, but the test is a known failure until the defect is fixed (strict, so it turns red when it is) · **📎** fix and tests are in an open PR, not on `main` yet · **👤** needs a person or another system · **—** nothing to test.

Frontend tests are vitest in `csv-table-hub-main/src/__tests__/` (`fe:` below). Browser tests are in `e2e/` and are not part of the default run (see `e2e/README.md`).

## Closed issues

| # | What | Status | Verified by |
|---|---|---|---|
| 99 | Per-tenant T&E tables | ✅ | `tests/system/test_tenant_isolation.py` (own tables, per-tenant counts, keys and triggers kept) |
| 102 | Lock accounts after failed sign-ins | ✅ | `tests/system/test_accounts.py` (`Lockout`) |
| 107 | Immutable source, append-only audit | ✅ | `tests/system/test_preserved_uploads.py`, `test_audit_append_only.py`, `test_original_bytes.py` |
| 108 | Review: paging, include/exclude, versioned edits | ✅ | `tests/system/test_review.py`, `test_review_cases.py`, `fe: review-table.test.tsx`, `e2e/test_streamlit_spike.py` |
| 114 | Delete merged branches | — | housekeeping |
| 116 | Local PostgreSQL not reachable on 5433 | 👤 | one dev machine's setup; closed on evidence attached to the issue |
| 117 | Password change and admin reset | ✅ | `tests/system/test_password_reset.py`, `fe: change-password.test.tsx` |
| 118 | "Failed to fetch" when the API is down | ✅ | `fe: session.test.ts` ("API unreachable"). The PowerShell start-up guard in `scripts/start-api.ps1` has no test |
| 119 | Upload times shown in UTC | ✅ | `fe: local-time.test.ts` |
| 120 | House writing style doc | — | docs |
| 123 | Every-row-rejected upload shown as migrated | ✅ | `tests/system/test_failed_uploads.py`, `fe: job-outcome.test.ts` |
| 130 | Frontend lock file out of sync | ✅ | `tests/unit/test_tooling_issues.py` (lock file agrees with `package.json`) |
| 132 | `npm audit` critical and high | ✅ / 👤 | `fe: table-rows-contract.test.ts` guards the zod 4 change. `npm audit` itself needs the registry and was not run |
| 133 | React hydration errors on `/auth` | ✅ | `fe: session.test.ts` |
| 151 | Terraform storage accounts audit | — | investigation |
| 152 | Frontend architecture decision | — | decision, see #154 and #212 |
| 154 | Streamlit spike | ✅ | `e2e/test_streamlit_spike.py` |
| 156 | Tracker home decision | — | decision |
| 162 | Cosmetic tracker doc edits | — | docs |
| 164 | Live pointers to superseded API doc | — | docs, closed not planned |
| 165 | STARTER_GUIDE dedup claim | — | docs, closed not planned |
| 166 | STARTER_GUIDE skips sign-in | — | docs |
| 169 | Test catalogue generator | ✅ | `tests/unit/test_tooling_issues.py` and the CI freshness step |
| 170 | All-failed T&E import removed the prior dataset | ✅ | `tests/system/test_te_reupload_registry.py` (`…keeps_a_prior_dynamic_table…`), `tests/system/test_failed_uploads.py` |
| 171 | `setup.sh` truncated the config on failure | ✅ | `tests/unit/test_tooling_issues.py` (runs the real config-write block) |
| 175 | An uploader could destroy a dataset through overwrite or a mode switch | ✅ | `tests/system/test_issue_regressions.py` (`UploadCannotDestroyAnExistingDataset`). Guarded by outcome: M5 (#109) stores a repeated filename as a new version and ignores `overwrite`, so the dynamic path no longer drops anything; the T&E path still needs delete permission and is tested as such |
| 176 | Browser history leaks across tenants | ✅ | `fe: tenant-isolation.test.tsx` (history and mapping templates, per tenant and user), `e2e/test_react_ui.py` (a second tenant in a real browser). Fixed in the React app; closed earlier as moot, the leak is closed in what ships |
| 177 | Composite FKs for program consistency | ✅ | `tests/suites/test_06_program_consistency.sql` (Tier S) |
| 178 | Distinct rows dropped as duplicates | ✅ | `tests/system/test_issue_regressions.py` (`RowDedupKeepsDistinctRows`) |
| 179 | Frontend lint baseline | — | not a test: `npm run lint` is the check, and is not in CI. Closed as moot |
| 180 | Tier I eval ignored SQL errors | ✅ | `tests/unit/test_tooling_issues.py` |
| 181 | SQL test wrapper exited 0 on failures | ✅ / 👤 | `tests/unit/test_tooling_issues.py` covers the wrapper. The second half (`ON_ERROR_STOP` on the Tier S psql calls in `evals/runner.py`, fix on the unmerged `fix/181-sql-suite-exit-code` branch) has no test: CI fails any skipped or expected-fail pytest test, so it can't be recorded as one |
| 182 | Offline bundle swallowed download failures | ✅ | `tests/unit/test_tooling_issues.py` (runs the real download block with a failing `apt-get`) |
| 183 | Rate limiter used the API key prefix | ✅ | `tests/system/test_issue_regressions.py` (`RateLimiterIdentity`) |
| 185 | Preserved original differed from uploaded bytes | ✅ | `tests/system/test_original_bytes.py`, `fe: file-bytes.test.ts` |
| 186 | Header mappings ignored | ✅ | `tests/system/test_header_mapping.py`, `fe: log-step-contract.test.ts` (the schema accepts the step it added) |
| 187 | Failed uploads unreachable from the browser | ✅ | `fe: upload-attempts.test.tsx`, `fe: files-refresh.test.ts`, `e2e/test_react_ui.py` |
| 188 | Cancel did not interrupt an import | ✅ | `fe: uploader-state-machine.test.ts`, `fe: job-outcome.test.ts`, `e2e/test_react_ui.py`. Server-side cancel was left for #110 (M6, now merged); not verified here |
| 189 | T&E errors named the wrong source row | ✅ | `tests/system/test_issue_regressions.py` (`TeDatabaseErrorsNameTheSourceRow`) |
| 190 | T&E review showed no validation errors | ✅ | `tests/system/test_review.py`, `tests/system/test_api_coverage.py`, `fe: review-table.test.tsx` |
| 191 | Registry race | ✅ | `tests/system/test_registry_race.py` |
| 192 | Ragged rows accounting | ✅ | `tests/system/test_ragged_rows.py` |
| 193 | Formula injection in exports | ✅ | `fe: export.test.ts` |
| 194 | Coverage floors for the loaders | ✅ | `tests/unit/test_tooling_issues.py` (the gate fails below a floor) |
| 207 | API doc covered 8 of 22 routes | ✅ | `tests/unit/test_tooling_issues.py` (the doc defers to the generated schema, which is served) |
| 215 | All-failed T&E re-upload overwrote the registry record | ✅ | `tests/system/test_te_reupload_registry.py`, `tests/system/test_te_loader_integration.py` |

## Open issues

| # | What | Status | Verified by |
|---|---|---|---|
| 31 | One-time cloud setup for terraform-test/staging | 👤 | cloud account work |
| 32 | `az` CLI SSL error on the dev machine | 👤 | one machine's setup |
| 34 | `terraform plan` provider handshake fails locally | 👤 | one machine's setup |
| 57 | Add SECURITY.md | ✅ | `tests/unit/test_open_issues.py`. The issue's done-when ("on `main`") is met, so it could be closed. The file still carries a placeholder address, noted in a comment inside it |
| 59 | Sample Migration Verification Report | — | docs, merged (#216). The issue is still open and could be closed |
| 60 | Air-gapped install procedure | ✅ / 👤 | `tests/unit/test_open_issues.py` (scripts parse, stop on error, guide names them). The offline dry run, due 15 Nov, is manual |
| 109 | ART M5: dedup and naming | ✅ | `tests/system/test_versioned_datasets.py` (merged, #226). The issue is still open |
| 110 | ART M6: approval and staged import | ✅ | `tests/system/test_staged_import.py` (merged, #227). The issue is still open. Server-side cancel (#188 option b) was meant to follow here; I did not check whether it landed |
| 111 | ART M7: sovereignty and reports | ✅ | `tests/performance/test_import_scale.py`, `tests/egress_guard.py` (merged, #228). Closed |
| 112 | Security review before the first external tenant | 👤 | review by a person; `docs/SECURITY_REVIEW_PACK.md` (merged, #229) is the input. The #176 tests are evidence for it (the leak is fixed) |
| 113 | Check OIDC sign-in against the real IdP | ✅ / 👤 | `tests/system/test_oidc_https.py`, `tests/system/test_check_oidc.py` (merged, #229) and `tests/unit/test_oidc_https_jwks.py` (https key fetch, rotation, certificate checks; overlaps the first). A sign-in against Keycloak or Entra ID stays manual: `docs/OIDC_REAL_IDP_CHECK.md`. Closed |
| 128 | Offline bundle for Windows, macOS and Linux | — | only the Ubuntu bundle exists |
| 159 | Verify `docs/VCRM.md` against the DID | 👤 | compare with an external document |
| 167 | Reorganise `tests/` into category folders | ✅ | Done on `main` (#221); `tests/README.md` says where a new test goes. The issue is still open, and could be closed |
| 168 | Accessibility CI job | ✅ | Done on `main` (#222): `tests/accessibility/` and its CI job. The issue is still open, and could be closed |
| 172 | Production database name disagreement | ✅ | `tests/unit/test_prod_db_naming.py` (merged, #213). The issue is still open |
| 173 | Cluster-wide `te_app` role | 📎 | PR #208 (`test_runtime_role_per_env.py`; it will need to follow the new `tests/` layout) |
| 174 | Docker image can bake local credentials | ✅ | `tests/test_docker_image_secrets.py` (merged, #204). Closed |
| 184 | Tenant T&E schemas have no upgrade path | ✅ | `tests/system/test_tenant_te_migrations.py` (merged, #213). The issue is still open |
| 195 | Confirm inferred types, provenance flag | ✅ | `tests/system/test_type_provenance.py` (merged, #213). The issue is still open |
| 198 | Track checks that completed after merging #197 | — | process |
| 210 | Background job queue for large imports | — | feature, not built |
| 212 | Plan the Streamlit migration | — | a plan. `e2e/test_streamlit_spike.py` is the baseline it must keep passing |

## Known failures on purpose

None. #176 was the only one; it is fixed. (A strict expected failure turns red when the defect is fixed, so its marker had to go: `it.fails` in vitest and `xfail` in the browser test are plain tests now. CI's `--strict` pytest report fails any skipped or expected-fail test, so none can live there.)

## Found while writing these tests

- **Every dynamic import in the React app showed as Failed** since #202: the app's response schema did not list the new `header_mapping` log step. Fixed in PR #223, with a test that checks the schema against every step the API can emit.
