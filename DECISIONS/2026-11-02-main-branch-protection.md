# Decision: Main branch protection (Quality Gate required)

Status:  Decided and applied
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

## How it was applied

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

## Related

- #51 (closed with this decision)
- #45 (closed 7 days earlier): made option (a) viable
- 26 Oct 2026 closure rule â€” this decision applies the equivalent discipline to merges