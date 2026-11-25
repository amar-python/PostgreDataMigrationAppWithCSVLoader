# Project Status — PostgreDataMigrationAppWithCSVLoader

Living snapshot of the project state. Full detail lives in:
- Outstanding Items Tracker (Claude Artifact Doc, master cross-cutting view)
- DECISIONS/ in this repo (per-decision records)
- `docs/VCRM.md` (requirement status; the master traceability record)
- GitHub Issues and PRs (per-item work)

Last updated: 2026-11-24 (`main` at `948ba44`, merge of PR #403). Rewritten on that date; the 2 Nov session log is kept below as history, and git history has the earlier text.

---

## Current state (24 Nov 2026)

- **Branch protection: applied on `main`** (24 Nov, by the owner). Five required checks, each bound to GitHub Actions: `python-validator-tests`, `free-tier (unit, lint, health, evals-p)`, `integration (postgres service)`, `browser (Playwright, e2e/)`, `accessibility (Playwright + axe-core, WCAG 2.1 AA)`. Branch must be up to date (`strict`), admins included (`enforce_admins`), pull request required with 0 approvals, no force-push or deletion. Record and read-back: `DECISIONS/2026-11-02-main-branch-protection.md`, "Applied, 24 Nov 2026". `GET /branches/main` reports `protected: true`. #301 (OIT-016) closed 24 Nov. From 2 Nov to 24 Nov it was decided but not applied; this file said otherwise until 18 Nov.
- **Frontend: the Streamlit app is on `main`** (`streamlit_app/`): app shell, review screen, import history and upload screens (migration steps 1 to 4, #251 to #255, merged 19 Nov). The React app (`csv-table-hub-main/`) is still the default until cutover. Steps 5 (packaging, #256) and 6 (cutover and deletion, #257) are not started; step 5 waits for the offline dry run.
- **Streamlit migration decisions: all answered by the owner on 24 Nov** (`DECISIONS/2026-11-16-streamlit-migration-plan.md`, "Owner decisions"): whole-app cutover with React kept one release as rollback; no OIDC in the UI; saved mapping templates and the "App changelog" dropped; server audit events kept; no page for the audit log and its verification; about 116 MB more in the offline bundle accepted; the accessibility job scans Streamlit as well as React (#388); Azure host is Container Apps on the private network only (#394); `browser` and accessibility jobs required.
- **Tenant isolation at the database:** one PostgreSQL role per tenant, `SET ROLE` per request (#297, OIT-012, merged in PR #400, closed 24 Nov; `DECISIONS/2026-11-24-per-tenant-db-roles.md`).
- **Shared API key retired:** every data request needs a session (#298, OIT-013, merged in PR #401, closed 24 Nov). Follow-up PR #403 (container smoke test fails, not skips, without admin credentials) merged 24 Nov.
- **T&E audit review of 20 Nov:** most OIT fixes merged on 23 and 24 Nov (OIT-001 to OIT-016 apart from OIT-014, and others; see the tracker). `docs/VCRM.md` records seven of them as verified on 25 Nov (BR-45, BR-50, BR-51, BR-53, BR-54, BR-55, BR-58): 34 of 49 requirements verified, 3 deferred, 12 partial, none not started.
- **SQL suite:** 159 assertions in 6 suites, 159 of 159 pass (Tier S). The Tier S threshold was raised to 159 on 25 Nov, and a unit test keeps it equal to the suite's count (#303).
- Open issues: 50. Open PRs: 7 (#404 to #410, including this update), all opened on 24 Nov while several sessions work in parallel. Counted from the GitHub API on 24 Nov, 11:40 UTC.

## Open items (snapshot — the tracker is master)

### Streamlit migration
- #256 Package the Streamlit app for the offline bundle and Azure (step 5)
- #257 Switch the default frontend to Streamlit and retire React (step 6)

### Verification and T&E audit follow-ups
- #302 VCRM internal inconsistencies (OIT-017)
- #303 BR-20 and Tier S threshold (OIT-018)
- #304 No coverage floor for `build/csv` and `evals` (OIT-019)
- #305, #306 Backup/restore and audit-retention procedures (OIT-020, OIT-021)
- #308 React `/audit` page reads browser storage (OIT-026)
- #311 Unmerged branches (OIT-030)
- #313 This file (OIT-032)
- #314, #315, #316 Performance targets, BR-38 on Windows and macOS, real-IdP OIDC and clean-VM offline install (OIT-023 to OIT-025)
- #342 Teradata table count in the documents

### Security and infrastructure
- #299 Key Vault and ACR public access (OIT-014; PR #398 merged 24 Nov, the issue is still open)

### Software-engineering review (22 Nov) and CSV-loader CLI (23 Nov)
- #323 to #338: SE-02 to SE-16 and the SE-00 tracking issue
- #347 to #362: CLI-01 to CLI-16; #396 imports the CLI into this repository
- #383, #384: RV-00 and RV-03 (React still depends on Lovable)

## Not reopening (recorded)

Deferred-by-decision or risk-accepted; stay closed unless explicitly asked:
- BR-02 six-engine support (ADR-0001). Teradata's DDL defines all 12 tables; the earlier figure of 1 was a counting error (#342)
- Tier X engine evals in CI (ADR-0001)
- BR-21, BR-22 (deferred 4 Oct)
- "Production-grade" README framing (risk accepted 4 Oct)
- Hand-rolled rate limiter
- Resume review and C1-C6 items (out of scope, 28 Oct decision)

## Verification notes (24 Nov)

- Branch protection: `gh api repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main --jq .protected` printed `true`; the full read-back of the protection settings is in the decision record (an admin read; a Claude session cannot read or write that endpoint).
- Issue states (#297, #298, #301 closed; #302, #303, #313, #342 open) and the open counts are from the GitHub API, 24 Nov.

---

## History: session of 2026-11-02 (kept as written, with corrections)

Nine items closed. Four new issues filed. Six decision records committed.

### Closed

| Item | Resolution | Evidence |
|---|---|---|
| D3 | ReportLab for PDF generation | #67, DECISIONS/2026-11-02-pdf-library.md, PR #149 |
| S2 / #108 | ART M4 review accepted (full-dataset cell editing) | #108, PRs #142 and #143 verified against acceptance criteria |
| D4 | BYTEA for file storage (no local/prod split exists) | #68, DECISIONS/2026-11-02-file-storage-backend.md, PR #150 |
| D6 | End Lovable platform dependency | #69, DECISIONS/2026-11-02-end-lovable-dependency.md, PR #153 |
| #152 | Frontend direction: spike-then-decide in Streamlit | #152, DECISIONS/2026-11-02-frontend-spike-plan.md, PR #155 |
| D7 | Tracker long-term home: Doc as master, GitHub issues for work | #156, DECISIONS/2026-11-02-tracker-long-term-home.md, PR #157 |
| D8 | Main branch protection decided, with enforce_admins true. **Superseded:** it was recorded here as applied on 2 Nov, but was not live until 24 Nov (see "Current state") | #51, DECISIONS/2026-11-02-main-branch-protection.md, PR #158 |
| #56 | 4 of 5 README claims verified; 5th split to #159 | #56 closed with evidence table in the thread |
| #66 | Tier E/X eval status — already recorded in ADR-0001 | #66 closed as not planned |

### Filed

| Issue | Purpose | Label |
|---|---|---|
| #151 | Audit Terraform-provisioned storage accounts | housekeeping |
| #154 | Spike: rebuild M4 review screen in Streamlit (1-day time-box) | decision |
| #156 | D7 tracker-home decision (closed same session) | decision |
| #159 | Verify docs/VCRM.md against DID-V&V-DEF-VCRM content (split from #56) | verification |

### Policy change recorded that day (superseded)

The 2 Nov entry said branch protection was applied that day via `gh api PUT`. It was not: `main` reported `protected: false` on 9, 16, 18 and 20 Nov (#198). It was applied on 24 Nov, with two more required checks (`browser`, `accessibility`) than the 2 Nov decision named. See "Current state" and the decision record.

## Reference links

- Outstanding Items Tracker: https://claude.ai/artifact/KjdTM4cYCJLCpR2MtEfU7H
- Repo: https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader
