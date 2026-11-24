# Decision: Main branch protection (Quality Gate required)

Status:  Applied 24 Nov 2026 by the owner, with the `browser` and accessibility jobs added as required checks (see "Applied, 24 Nov 2026"). From 2 Nov to 24 Nov it was decided but not applied (see "Correction, 18 Nov")
Date:    2026-11-02
Review:  On trigger (see below)

## Choice

Branch protection on main:
- All three Quality Gate checks required: python-validator-tests, free-tier (unit, lint, health, evals-p), integration (postgres service)
- PR required (0 approvals needed for solo)
- strict: true (branches must be up to date before merge)
- enforce_admins: true (gate applies to admins)
- allow_force_pushes: false, allow_deletions: false

## Context

#51 raised this on 2026-10-25. The integration job had been red on main for at least two months with merges going through regardless. The hedge in option (b) was against #45, which was already closed 7 days before this decision.

## Reasoning

- The last 8 merges on main all show all three checks SUCCESS. Formalising reflects practice, not disrupting it.
- Two months of unprotected red integration is the precedent for why unprotected main is unsafe.
- Solo project discipline requires enforce_admins: true â€” admin bypass defeats the purpose of the gate for a one-person team.

## Trade-offs accepted

- No admin bypass means emergency merges require temporarily removing protection (deliberate â€” see escape hatch below).
- strict: true forces a pull-and-re-check on stale branches. Small friction, catches merge-main-into-feature drift.
- Required 0-approval PR means you merge your own PRs; the gate is CI, not review.

## How it was meant to be applied (this was never live)

A JSON payload with required_status_checks (strict + 3 contexts), enforce_admins true, 0-approval PR required, no force-push, no deletion, was PUT to the main branch protection endpoint via:
    gh api --method PUT /repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main/protection --input <json-file>

Verify with:
    gh api /repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main/protection

## Emergency escape hatch

To remove protection in a genuine emergency:
    gh api --method DELETE /repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main/protection
To restore afterwards: re-run the apply command (see above).

## Reopen trigger

Reconsider if any of:
- A required check becomes unreliable (flaky, infra-dependent in a way that blocks real merges)
- The project adds people and the review model needs to change
- A check added later becomes required (new row to be added to contexts)

## Correction, 18 Nov 2026: this was never applied

This record said the protection was applied on 2 Nov, and `claude/project-status.md` said it was verified live. It was not live. Checked read-only on 9, 16 and 18 Nov:

- `GET /branches/main` returns `protected: false` with no required checks; the branch listing still shows `protected: false` on 18 Nov (`main` at `75a9c16`).
- On 9 Nov, `GET /branches/main/protection` returned 404 ("Branch not protected") and the only ruleset (`ConsolidatedPostgreDataMigrationApp`, id 20365935) was `enforcement: disabled`.
- Whether it was never applied or later removed cannot be told from the API.

PR #197 merged on 4 Nov with two checks still running because nothing required them (#198).

**What is waiting to be applied** (prepared 17 Nov on the owner's 16 Nov decision; a Claude session could not write it because its proxy refuses the branch-protection API path, HTTP 403, so a repository admin has to):

| Setting | 2 Nov record above | Prepared 17 Nov |
|---|---|---|
| Required checks | the 3 below | those 3 **plus** `accessibility (Playwright + axe-core, WCAG 2.1 AA)` |
| `strict` (branch must be up to date) | true | false |
| `enforce_admins` | true | false |
| Pull request required | yes, 0 approvals | no |
| Force-push, deletion | refused | refused |

The right-hand column is the narrower set (checks required, no required reviews, so the owner can still merge their own PRs). It is not decided between the two columns which the owner wants, and either is fine: `strict` forces a CI re-run on every open PR each time another one merges, which is the main reason it was left out. Say which, and this record should then be edited to match.

**To apply it in the browser (about two minutes):** repository **Settings**, **Branches**, **Add branch protection rule** (the classic rule), then:

1. Branch name pattern: `main`.
2. Tick **Require status checks to pass before merging**, and add `free-tier (unit, lint, health, evals-p)`, `integration (postgres service)`, `python-validator-tests` and `accessibility (Playwright + axe-core, WCAG 2.1 AA)`. A check only appears in the search box if it has run in the last week; all four ran on PR #262.
3. Leave **Require a pull request before merging** unticked (tick it, and **Do not allow bypassing**, only if choosing the 2 Nov column), and leave the force-push and deletion options unticked.
4. **Create**.

Or, with an admin token, save the prepared settings as `protection.json` and run `gh api -X PUT repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main/protection --input protection.json`. The JSON is in the 17 Nov comment on #198. To undo: `gh api -X DELETE` on the same path.

**To check it took:** `gh api repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main --jq '.protected, .protection.required_status_checks.contexts'` should print `true` and the four names. A session without admin rights can still read `protected` from the branch listing.

## Disposition, 20 Nov 2026: tracked here, not as a requirement

The T&E audit review of 20 Nov proposed this as requirement BR-60. The product owner decided on 20 Nov to track it as an action on this decision instead (`docs/VCRM.md` §6.4), because it controls the process rather than product behaviour. The action is still open: `main` reported `protected: false` at review time, and the setting needs a repository admin (the owner) to apply one of the two columns above. Close the action when the check under "To check it took" prints `true` and the required check names, and record which column was chosen.

`claude/project-status.md` (session of 2 Nov, "D8" and "Live policy change") still says protection was applied; both places now carry a correction note pointing here.

## Applied, 24 Nov 2026

The owner chose the 2 Nov column, with the `browser` and accessibility jobs added as required checks, and applied it in the browser as the classic rule for `main` (a Claude session still cannot write this API path). Read back on 24 Nov with `gh api repos/amar-python/PostgreDataMigrationAppWithCSVLoader/branches/main/protection`:

| Setting | Live value |
|---|---|
| Required checks, each bound to GitHub Actions (app 15368), so another app cannot post a passing result under the same name | `python-validator-tests`, `free-tier (unit, lint, health, evals-p)`, `integration (postgres service)`, `browser (Playwright, e2e/)`, `accessibility (Playwright + axe-core, WCAG 2.1 AA)` |
| `strict` (branch must be up to date with `main`) | true |
| `enforce_admins` (no bypass, admins included) | true |
| Pull request required | yes, 0 approvals |
| Force-push, deletion | refused |

Why these checks: all five run on every push and pull request with no path filters, so none can leave a PR waiting on a check that never runs. `integration (postgres service)` is the summary job (`if: always()`) over the integration shards, the egress-blocked shards and the coverage gate, so one name covers every database job, including documentation-only PRs where the shards are skipped. Over the 60 Quality Gate runs before 24 Nov, `accessibility` passed 60 of 60 and `browser` 58 of 60: one failure was a real regression it caught (on the #289 branch) and one was a superseded run cancelled, so neither job is flaky. Median times 2 and 4 minutes.

What it means day to day: every change reaches `main` through a pull request, and merges only when all five checks pass on a branch that is up to date with `main`; with `strict`, a PR has to be brought up to date (and re-run) whenever another merges first. The escape hatch above is unchanged.

The open action in `docs/VCRM.md` (BR-60, §6.4) is met by this read-back.

## Related

- #51 (closed with this decision)
- #45 (closed 7 days earlier): made option (a) viable
- 26 Oct 2026 closure rule â€” this decision applies the equivalent discipline to merges