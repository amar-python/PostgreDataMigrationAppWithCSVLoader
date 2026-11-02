# Decision: Frontend direction — spike before committing

Status:  Decided (approach)
Date:    2026-11-02
Review:  After spike outcome

## Choice

Rebuild one representative screen in Streamlit as a 1-day spike. Decide the real frontend direction based on what the spike teaches, rather than committing up front.

## Context

4 Oct 2026 decided: adopt Lovable-generated frontend. Partially superseded 2 Nov 2026 by #69 (end Lovable platform dependency). The generated code (`csv-table-hub-main/`) still works, calling the FastAPI backend. Whether to keep that React code, replace with a Python-native alternative, or something else is #152.

Three frontend direction shifts occurred over two weeks: Lovable adoption → PR #40 plain HTML/JS attempt → Reflex lean (paused on Node-at-build caveat) → now this.

## Reasoning

When direction keeps shifting, pick the lowest-cost option to learn fast rather than the most ambitious option to commit hard. The product owner's stated driver (one language across the stack, easier for solo maintenance) points at Python-native. Three Python-native options: Streamlit (~1 day to rebuild one screen), NiceGUI (~2-3 days), Reflex (~4-5 days, Lovable-matching look).

Streamlit is the cheapest learning option. If it feels right, the learning transfers to a staged migration. If it feels wrong, only a day was spent and the React code stays as fallback.

## The spike itself

- **Target:** M4 review screen (the most interactive screen in the app)
- **Time-box:** 1 day, hard limit
- **Scope:** one screen, parallel to the live React implementation
- **Outcomes:** three possible outcomes documented on the spike issue, each with a defined next step

## What this doesn't decide

- Whether to migrate the whole frontend to Python-native (depends on spike outcome)
- Whether to keep the React code long-term (depends on spike outcome)
- Which Python-native framework to use for a real migration (Streamlit, NiceGUI, Reflex — depends on spike outcome)

## Trade-offs accepted

- One day of time spent on a spike that may lead to "none of the above"
- Delays a committed frontend decision by one more spike cycle (and possibly a second if Streamlit falls short but Python-native still appeals)
- Risk of indefinite deferral if the spike never happens — mitigated by the spike issue existing with a defined done-when

## Reopen trigger

- Spike completes → this decision is replaced by whichever outcome the spike produces
- Spike never happens for 3+ months → reconsider whether the current React code should just be formally adopted as the long-term choice (Option 1 from #152)

## Related

- #152 (closed with this approach)
- #69 (ended Lovable platform dependency)
- Spike issue (to be filed as a follow-up)
- 4 Oct 2026 decision: adopt Lovable frontend (now partially superseded)