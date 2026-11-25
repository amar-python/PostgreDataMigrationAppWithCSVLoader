# Plan: replace the Lovable-generated React frontend with the Claude-built Streamlit frontend (#257)

Status:  Proposed, for the owner to accept
Date:    2026-11-25
Review:  At each step's merge

## Where it stands

- The Claude-built frontend is the Streamlit app in `streamlit_app/`. The accepted plan is `2026-11-16-streamlit-migration-plan.md`. Its steps 1 to 4 are merged.
- Packaging (#256) is partly done, in a draft PR. The clean-VM dry run (#60) is not done.
- Cutover and deletion (#257) is not started.
- The Lovable-generated frontend is `csv-table-hub-main/`. `2026-11-02-end-lovable-dependency.md` already ends the platform dependency; this plan removes the code.
- The owner has asked for a full replacement. This plan is the checklist the work is held to.

## Working rules

Each step is one branch and one draft PR, worded "For #N" with no closing keyword. Tests come first and are shown failing, then passing. The assistant does not merge. Each step is ticked in #257 when it merges.

## Steps

| # | Step | Done when |
|---|---|---|
| 0 | Close the Dependabot PRs for `csv-table-hub-main/` (including #416) with a comment naming the replacement. This makes the lockfile commit cd914e4 on #416 moot. | The owner says go. The PRs are closed. |
| 1 | Inventory: list every `csv-table-hub-main` and Lovable reference by file and kind (CI, Docker, bundle, tests, docs, Dependabot), and a parity checklist of each React screen against its Streamlit counterpart. | The list is committed as a doc, with the grep command that reproduces it. |
| 2 | Parity gaps: each React behaviour with no Streamlit equivalent gets its own issue and PR, or a written "drop" from the owner. Known items: saved mapping templates (already decided in the migration plan), OIDC in the UI (not needed for parity). | The parity checklist has no unticked row without an owner decision. |
| 3 | Packaging (#256): finish the draft PR (Ubuntu bundle with `te-streamlit` on port 8501, Terraform for the API and Streamlit apps). | Merged. The owner runs the clean-VM dry run (#60) with the no-outside-connection check, and the Azure host, WebSocket and 50 MiB checks. The assistant cannot run these. |
| 4 | Accessibility job: re-point `accessibility` in `quality-gate.yml` from the React dev server to Streamlit. | The job scans only Streamlit and is green. |
| 5 | Switch the default: `container/frontend.Dockerfile`, `container-bundle.yml`, `scripts/offline/build_bundle.sh`, `scripts/start-frontend.ps1` and the README quick-starts start Streamlit. | A fresh checkout starts Streamlit by default. CI is green with React still present. |
| 6 | Delete React: remove `csv-table-hub-main/` and `csv-table-hub-main.zip`, its tests, its frontend/accessibility/bundle CI jobs, its Dependabot entry, and its `.dockerignore` and path rules. | `git grep -i -E "csv-table-hub\|lovable"` finds only history under `DECISIONS/`. A test fails if the folder returns. CI is green. |
| 7 | Docs sweep: `ARCHITECTURE`, `VCRM`, `STANDARDS_AUDIT` and the other docs listed in the step 1 inventory. Mark the 4 Oct 2026 Lovable-adoption decision fully superseded. | The grep above is clean outside `DECISIONS/`. |

## Open decisions for the owner

1. **Rollback.** The migration plan keeps React for one release before deleting it. Proposed default: delete in step 6 with no waiting release, and tag the last commit that contains React as the rollback. The owner confirms or asks for the one-release wait.
2. **Azure host.** Where Streamlit runs in Azure. Step 3 cannot finish without it.

## Out of scope

Merging any of these PRs, deleting anything before step 6 is approved, and claiming the offline or Azure checks passed without a run.
