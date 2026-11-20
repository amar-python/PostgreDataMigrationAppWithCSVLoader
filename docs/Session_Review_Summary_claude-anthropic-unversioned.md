# Session review summary: independent T&E audit review, 2026-11-20

## Reviewer identity

- Claude, a model made by Anthropic, running as the Abacus.AI agent.
- The exact model name and version string is **not available** to the reviewer. The file name therefore uses the suffix `claude-anthropic-unversioned` rather than a precise model ID.
- The tracker is named `Outstanding Items Tracker_Grok.txt` because the user asked for that name. "Grok" is not an attribution.

## Scope and baseline

- Repository: `amar-python/PostgreDataMigrationAppWithCSVLoader` (found with the GitHub connector's `list_my_repos`; admin/push permission).
- Reviewed: `main` at `68399af365d6c076b0fc43ce5c91f3165e44844d` (merge of PR #284, 2026-11-19T15:58:43Z).
- Open PRs: none. 40 branches are fully merged; 7 have unmerged commits and are not counted as delivered (`docs/AUDIT_RECONCILIATION_2026-11-20.md` §1).
- Reviewed against: `docs/VCRM.md` (T&E requirements and master traceability), `docs/art/milestone-0-assessment.md` (milestone plan and decisions), `docs/HANDOFF-20261104.md` §7, `docs/SECURITY_REVIEW_PACK.md` §8, `docs/GAP_ANALYSIS.md`, CI workflows, migrations, deployment config and the code under `api/`.
- Changes: documentation only, on branch `docs/te-audit-review-20261120`. No application code, tests or workflows were changed.

## Checks executed

| Check | Where | Result |
|---|---|---|
| Quality Gate run 44560865716 at baseline | GitHub API | success: integration, browser, free-tier, accessibility |
| Python Validator Tests run 44560865884 | GitHub API + job log | success: 875 passed, 467 deselected (Windows) |
| Branch protection on `main` | GitHub API | `protected: false`, no required checks |
| Free tier (`test_report.py`, unit/regression/security/snapshot) | Local, PG 16.16 | 870 passed, 0 failed, 0 skipped |
| `make lint`, `make health` | Local | exit 0, exit 0 |
| Evals Tiers P, I, S, E | Local | 27/27; Tier S 159/159 SQL assertions |
| `deploy_all.sh` dev, test, staging, prod | Local | all exit 0 |
| Full suite (`not accessibility`, strict) | Local | 1337 collected, 1324 passed, 0 failed, 0 skipped, 13 deselected |
| Egress-blocked system tests | Local | exit 0 |
| Coverage gate + floors | Local | passed; api 94.4 %, streamlit_app 97.5 %, build/csv 0 %, evals 63.5 % |
| vitest (frontend) | Local | 196/196 |
| Perf, 100,000 rows | Local, non-reference VM | 9.96 s stage-to-imported; indicative only |
| R1: concurrent `alembic upgrade head` ×5 | Local | one of two failed in 5/5 trials |
| R2: T&E upload of content identical to a dynamic dataset | Local, TestClient | table dropped; HTTP 200; destructive flag off |

The local environment was Python 3.11.17 on Linux, not the owner's Windows / Python 3.12 setup. Local results are reviewer evidence, not CI results.

## Not verified or blocked

- Live Azure state; real IdP (#113); clean-VM offline install (#60); Windows and macOS container hosts (BR-38); penetration test.
- Accessibility and browser e2e tests were not re-run locally. Their CI jobs passed at the baseline.
- R1 exercised `alembic upgrade head` directly, not two full API processes.
- The Claude Artifact tracker referenced by `claude/project-status.md` could not be accessed.

## Findings

### Confirmed defects

1. **OIT-001 (High).** Concurrent start-up migrations fail.
   - Evidence: reproduction R1; `alembic/env.py:33-40`; `api/db.py:234-246`.
2. **OIT-002 (High).** A T&E upload drops a dynamic dataset's table without `API_ALLOW_DESTRUCTIVE`.
   - Evidence: reproduction R2; `te_loader.py:88-118`; `destructive_ops.py:48-51`.
3. **OIT-003 (High).** On the direct upload path, the registry row, original and audit row are written after commit, and errors are swallowed. No test exercises those failure branches.
   - Evidence: `csv_routes.py:120-147`; `originals.py:84-95`; `audit.py:103-122`; coverage report.
4. **Security pack F1 to F11 are all still open.** See OIT-005 to OIT-015.
5. **OIT-016.** Branch protection is off on `main`.
6. **OIT-017 and OIT-018.** The VCRM is internally inconsistent, and the Tier S threshold is still 142 against 159 actual assertions.

### Unverified risks

- OIT-014: live Azure exposure.
- OIT-023: performance on reference hardware.
- OIT-024 and OIT-025: portability, real IdP and offline install.
- OIT-028: fallback audit table.

### Reconciliation outcome

- **HANDOFF §7:** most items are resolved. F5 is now confirmed. F8 and F11 are open. F9, C3, C4 and B4 are partial.
- **Security pack:** 11 of 11 findings are open.
- **M0:** F1 to F4 are resolved. Decisions 1, 4, 7 and 8 are only partly implemented or verified.
- **GAP_ANALYSIS:** G5 is superseded.

## Documents changed

- `docs/VCRM.md`: appended §6. It contains re-verification, errata E-01 to E-08, and PROPOSED BR-50 to BR-60, with method, acceptance criteria, evidence, Owner, Date and Detector. Nothing above §6 was changed.
- `docs/AUDIT_RECONCILIATION_2026-11-20.md`: new file.
- `docs/HANDOFF-20261104.md` and `docs/SECURITY_REVIEW_PACK.md`: short reconciliation pointer appended at the end.
- `docs/Outstanding Items Tracker_Grok.txt`: new file, 32 items.
- `docs/Session_Review_Summary_claude-anthropic-unversioned.md`: this file.

## Recommended next actions for the owner

1. Fix OIT-002 and OIT-001. Both have a clear acceptance test.
2. Decide the direct upload path (OIT-003, OIT-004): retire it in favour of the staged flow, or make it atomic.
3. Apply branch protection (OIT-016).
4. Disposition the VCRM errata and PROPOSED BR-50 to BR-60.
5. Complete the security review record (OIT-031).
