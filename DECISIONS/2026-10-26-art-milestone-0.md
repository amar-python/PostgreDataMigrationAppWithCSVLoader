# Decision: ART Milestone 0 approval

Status:  Decided
Date:    2026-10-26
Decided by: Amarnath Rasineni (product owner)
Source:  `docs/art/milestone-0-assessment.md` §6, PR #85, issue #53

## Approved

- **ADR-0002**, transactional staged import: option A (an API-owned transaction with COPY to staging, then promote). Option D (background worker) is the documented upgrade path.
- **ADR-0003**, customer-facing multi-tenant scope, including authentication by OIDC against a deployment-controlled IdP, with a local-account fallback for air-gapped installs.
- **The M1–M7 milestone plan.**

## The nine open decisions, all taken at the recommended default

| # | Decision | Outcome |
|---|---|---|
| 1 | Max file size and concurrency | 50 MB and 100,000 rows; 4 concurrent imports per API instance |
| 2 | Repeated uploads of the same filename | Versioned datasets (`<name>_v<n>`); never overwrite |
| 3 | Duplicate-record rule and policy | Exact whole-row match; policy **flag**, the user decides per row |
| 4 | Partial imports | Not permitted. All approved rows import or none do |
| 5 | Uploader approving own data | Not allowed by default; per-tenant setting for single-user tenants |
| 6 | Tenant model | Schema per tenant |
| 7 | Classification and retention | Design target OFFICIAL: Sensitive. Raw uploads kept until a recorded purge. Audit kept 7 years by default (configurable; confirm against the client's records authority) |
| 8 | Performance targets and environment | 100,000-row import under 60 s; first preview page under 2 s on 2 vCPU / 4 GB. Azure Container Apps plus on-prem docker compose. BR-22 stays deferred |
| 9 | PR #40 and csv-table-hub PR #1 | Close both (outside the React/TS constraint) |

## Unchanged

ADR-0001, the "production-grade" README framing, and the deferral of BR-02, BR-21 and BR-22.
