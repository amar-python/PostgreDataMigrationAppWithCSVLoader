# Decision: Consolidate PostgreDataMigrationAppWithCSVLoader and te-csv-migration

Status: Decided, direction only. Action deferred to machine access.
Date:   2026-10-04
Review: 2026-10-18 (fallback trigger)

## Context

Two public GitHub repos cover overlapping scope:

- amar-python/PostgreDataMigrationAppWithCSVLoader — bash/SQL batch
  core with FastAPI translator layer, Terraform IaC, 142 SQL
  assertions, 23 Tier P eval scenarios, VCRM/ASDEFCON design
  framing. 38 commits.
- amar-python/te-csv-migration — FastAPI + React rebuild started
  2026-09-24. 24 passing tests, clean secrets pattern, Lovable
  frontend decision in progress. ~10 days old.

The research review (2026-10-04) flagged this as a drag:
  "Two public repos with overlapping scope double the surface a
   reviewer can find stale."

## Decision

**Path C: merge both into a new canonical repo.**

Reasoning: neither existing repo is clearly ahead; merging forces
intentional selection of what carries forward and drops accumulated
debt from both.

## Fallback

If no merge work has begun by **2026-10-18** (two weeks), default to
**Path A**: PostgreDataMigrationAppWithCSVLoader remains canonical,
te-csv-migration gets archived with a banner pointing to the sister
repo. Valuable patterns from te-csv-migration (secrets validator,
test discipline, clean config module, Lovable frontend adoption)
get ported manually.

Fallback chosen over Path B because the sister project holds the
irreplaceable domain depth (SQL assertions, eval scenarios,
Terraform, ASDEFCON design decisions). te-csv-migration's assets
are younger and easier to port forward than the reverse.

## Trigger for fallback

"Started" means a new empty repo exists on GitHub with at least
one commit pulling content from either source repo. Not planning,
not scoping — a real commit.

## Related

- Research review 2026-10-04 (strategy and blind-spot analysis)
- te-csv-migration issue #4 (frontend decision, closed with Lovable
  adoption recommendation)

## Outcome (2026-10-26)

No merge repo existed on GitHub by 2026-10-18. The fallback applied and
was confirmed by the product owner on 2026-10-26: **Path A**.
PostgreDataMigrationAppWithCSVLoader is canonical. Archiving
te-csv-migration and disposing of its open issues is tracked in #72.
