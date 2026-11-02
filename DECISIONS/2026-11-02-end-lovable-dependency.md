# Decision: End Lovable platform dependency

Status:  Decided
Date:    2026-11-02
Review:  On trigger (see below), not scheduled

## Choice

**No further dependency on the Lovable platform.** Any Supabase instance behind the Lovable project is retired without migration. Future frontend work does not sync to or from Lovable.

## Context

#69 raised the question of what to do with any data stored in Lovable's Supabase backend. On investigation (`csv-table-hub-main/src` on `main` 59aab1a) the code calls the FastAPI backend and has no Supabase references. The product owner decided to end the Lovable relationship entirely rather than investigate what, if anything, is behind the Lovable project.

## Reasoning

- **Simpler ownership.** The code in-repo is self-contained; keeping a connection back to Lovable adds a sync and licensing dimension for no gain the project needs.
- **Fewer external dependencies.** Reinforces #60 (offline install, due 15 Nov) and the broader sovereignty positioning.
- **No evidence of value to preserve.** The frontend does not call Supabase today, so no live feature breaks when the Lovable connection ends.

## What this does and does not cover

- **Does:** retires Lovable Supabase without migration. Marks the 4 Oct Lovable-adoption decision as superseded regarding platform dependency.
- **Does not:** decide what to do with the Lovable-generated code already in `csv-table-hub-main/`. That is a separate architecture decision tracked in #152.

## Trade-offs accepted

- Any data in Lovable Supabase that has not been checked is lost (no evidence this matters).
- The 4 Oct decision to use the Lovable workflow for visual iteration no longer applies.

## Reopen trigger

Reconsider if the Lovable platform offers something no reasonable alternative provides and that becomes a project need.

## Related

- #69 (closed with this decision)
- #152 (frontend architecture decision, filed as the follow-up)
- 4 Oct 2026 decision: adopt Lovable frontend (now superseded on platform dependency)
- #60 (offline install, reinforced by this decision)