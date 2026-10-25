# Decision: README claims audit

Status:  Decided (eight claim decisions; five pending verification at the machine)
Date:    2026-10-04

The 2026-10-04 research review flagged README claims a sceptical reviewer
could disprove. Each was decided one by one.

## Decisions

| # | Claim | Decision |
|---|-------|----------|
| 1.1 | Audit log | D — verify at machine |
| 1.2 | "Production-grade" | D — keep (risk accepted) |
| 1.3 | DB deployment type | D — verify at machine |
| 2.1 | Dev password | B — sentinel REPLACE_ME |
| 2.2 | Machine-specific paths/ports | A — generic defaults |
| 3.1 | Test count framing | A — break down by tier (verify split) |
| 3.2 | FastAPI "latest" badge | A — pin and show real version |
| 3.3 | "ASDEFCON-aware" | A pending verify, with B/C fallbacks |

Option meanings, as presented in the session:

- 1.3 D: match the actual Terraform once verified. Suggested wording:
  "Dev deploys Postgres as a Container App with external access disabled.
  Prod uses Azure Database for PostgreSQL Flexible Server with private access."
- 2.2 A: default to port 5432 with a note for readers running several
  PostgreSQL instances, and remove machine-specific OS paths.
- 3.1 A: state scenarios per tier rather than one total.
- 3.2 A: show the real pinned FastAPI version instead of "latest".

## Detailed records

```
Claim 1.1 — Audit log claim
Decision:  D (verify at machine)
Trigger:   First time back at PostgreDataMigrationAppWithCSVLoader
Action:    Inspect api/services/ and api/routes/audit.py (or
           equivalent). Determine if the "every import is
           registered" claim is true, partial, or false.
Resolve to: A if false; B if partial; "fix API table description"
           if true.
Deadline:  Resolve before next external review of the README
```

```
Claim 1.2 — "Production-grade" framing
Decision:  D (keep as-is)
Date:      2026-10-04
Status:    Decided against Claude's recommendation and against
           the research review's finding
Risk accepted: Research identified this as the single most
           damaging line in the README. A sceptical Defence
           prime reviewer may use it as the signal to discount
           other claims. Explicitly accepted.
Review trigger: If any external reviewer flags this line, or
           if any job interview or presales conversation gets
           pushed back on it, revisit immediately.
```

```
Claim 2.1 — Dev password in README
Decision:  B (sentinel REPLACE_ME, matching sister project)
Date:      2026-10-04
Action:    Replace PGPASSWORD=devpassword123 with PGPASSWORD=REPLACE_ME
           Add one line: "See .env.example for the configuration
           template."
Related:   te-csv-migration PR #13 (2026-10-04) — same pattern
Future:    If/when pre-flight validator ported to this repo, sentinel
           will be caught at startup
```

```
Claim 3.3 — "ASDEFCON-aware"
Decision:  A (pending verification), with pre-committed fallbacks
Date:      2026-10-04
Trigger:   Next time at PostgreDataMigrationAppWithCSVLoader
Action:    - Cross-check current VCRM.md output against
             DID-V&V-DEF-VCRM content requirements (Strategic
             Materiel V5.x)
           - Required fields to check: Requirement ID,
             requirement text, verification method, test
             reference, result, artifact reference, status
Resolve to:
           - A if genuinely aligned: use specific DID reference
           - B if partially aligned: close the gap first, then
             use A; or fall back to "VCRM traceability" as interim
           - C if not aligned at all: drop the ASDEFCON phrase,
             make it a roadmap item
Deadline:  Before next external review of the README
Related:   Research C3 (positioning rigor); this is the
           single highest-leverage commercial differentiator
           in the whole README
```

The session gave claims 1.3, 2.2, 3.1 and 3.2 in the summary form above only.

## Verification results (2026-10-26, `main` @ 59aab1a)

Recorded on #56.

| Claim | Finding | Resolution |
|---|---|---|
| 1.1 | True. Every upload and delete writes an `audit_log` row (`api/services/audit.py`), paged by `GET /api/audit/log`. Row counts and timestamps are in the `csv_files` registry. | Fix the API table description |
| 1.3 | Dev (`infra/terraform`) runs `postgres:16-alpine` as a Container App with `external_enabled = false`. Test, staging and prod run Azure Database for PostgreSQL Flexible Server. | Rewrite to match |
| 3.1 | Tier P 23, I 1, S 1, E 1, X 1 (X not in CI per ADR-0001) | Use these counts |
| 3.2 | `fastapi>=0.140.7,<0.142.0` | Badge shows the pinned range |
| 3.3 | The phrase "ASDEFCON-aware" no longer appears in the README on `main`. DID alignment not checked. | Nothing to edit; alignment check stays open |
