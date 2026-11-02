# Decision: Tracker long-term home

Status:  Decided
Date:    2026-11-02
Review:  Annually, or on trigger (see below)

## Choice

**The Outstanding Items Tracker Doc remains the master cross-cutting view.** GitHub issues are the master for individual work items. Each layer references the other.

## How the layers work

- **Tracker Doc** holds the cross-cutting view: all open decisions, deadlines, areas of work, presales, deferred items. One place to scan "what is still open."
- **GitHub issues** hold the per-item state: acceptance criteria, evidence, PRs, labels. Where the work actually happens.
- **`DECISIONS/` in the repo** holds resolved decisions as versioned records.
- **`claude/project-status.md`** holds the periodic snapshot and decision log.

## When each is used

- D-items get a GitHub issue when they have a done-when that needs evidence beyond "decided", have code work attached, or need to be visible to others
- Operational items (deadlines, bugs, reviews) always get issues; the tracker row is the index
- Deferred-by-choice items stay as tracker rows only, no issue, because the point is not to re-litigate

## Reasoning

- Operated this way for 5+ weeks; the pattern works at current scale
- 5 decisions closed on 2026-11-02 all followed this end-to-end
- Alternatives (repo file, GitHub-only, PROJECT_MEMORY.md, mirror) have real costs and no clear benefit at current scale

## Trade-offs accepted

- Tracker Doc depends on Anthropic hosting Artifacts (tail risk)
- Cross-session edits need an open Doc tab (manageable)
- Mitigation: export the tracker to a repo snapshot quarterly, so a historical record survives if the Doc becomes unavailable

## Reopen trigger

Reconsider if any of:

- Artifact hosting changes materially
- Project grows beyond solo and new people need write access that is harder in a Doc
- Tracker becomes too large to scan in one view

## Related

- 27 Oct 2026: `PROJECT_MEMORY.md` retired; tracker + `claude/project-status.md` became project memory
- D1 (Path A, 18 Oct 2026): the "once D1 settles" condition in the standing recommendation is met
- #156 (closed with this decision)