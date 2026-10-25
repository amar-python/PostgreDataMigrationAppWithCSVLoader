# Decision: Sovereignty wording

Status:  Decided
Date:    2026-10-04
Review:  2026-11-15 (deadline for air-gapped install procedure)

## Framing (effective 2026-11-15)

> Australian-owned, NV2-cleared expertise. Deployable on
> HCF Certified Strategic cloud or fully offline.

## Interim framing (until 2026-11-15)

> Australian-owned, NV2-cleared expertise. Deployable on
> HCF Certified Strategic cloud or on-premise, including
> air-gapped environments.

## Reasoning

Each clause is checkable:

- "Australian-owned" — sole trader, Canberra-based
- "NV2-cleared expertise" — personal clearance, applies to
  delivery not software
- "HCF Certified Strategic" — Microsoft Azure (Australian
  regions) listed as Certified Strategic at
  hostingcertification.gov.au
- "Fully offline" — requires the install procedure below

Avoids the trap of claiming "sovereign cloud" (which a US-
headquartered hyperscaler cannot deliver) while still
foregrounding the real sovereignty signal (person, clearance,
jurisdiction).

## Commitment unlocking "fully offline"

By 2026-11-15, repository must contain:

- docs/offline-install.md with step-by-step procedure
  (vendored Python wheels, npm cache, container tarballs)
- One tested dry run on a clean no-internet VM
- README pointer to the procedure

If not met by 2026-11-15, continue using interim wording and
re-review deadline.

Tracked in #60.
