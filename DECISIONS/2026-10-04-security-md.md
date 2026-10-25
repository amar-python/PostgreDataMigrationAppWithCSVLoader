# Decision: SECURITY.md

Status:  Decided
Date:    2026-10-04
Review:  2027-01-04 (quarterly audit cycle)

## Scope

Narrow and conventional. Reporting procedure, supported versions,
response commitment. No architecture/threat-model content —
that stays out until there's a separate posture doc (not planned
in current roadmap).

## Reporting channel

Email only. Address TBD at machine. GitHub PVR not enabled.

Mitigation for email-only risk: set the chosen address to
auto-forward to primary inbox with a filter flagging security
keywords. Do this when at machine.

## Response commitment

Standard open-source SLA (72hr ack / 7 day triage / 90 day
disclosure / severity-based fix targets). Phrased as best-effort
to acknowledge solo-maintainer reality.

Risk accepted: missed SLAs are publicly observable and could
be used by a reporter to signal broken commitment hygiene.
Mitigation is the auto-forward above.

## Content choices

- PGP paragraph: kept (offers path, no commitment to maintain)
- Safe Harbour: kept (standard, low-cost signal)
- Hall of Thanks: kept
- Scope section: kept (reduces triage noise)

## Last-audited field

Added. Convention: bump quarterly even if no changes made.

Applying SECURITY.md is tracked in #57 (waits on the contact address).
