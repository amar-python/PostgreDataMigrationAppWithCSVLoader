# ADR-0003 — Customer-facing, multi-tenant scope

- **Status:** Accepted (product owner, 2026-10-26)
- **Date:** 2026-10-26
- **Decision maker:** Amarnath Rasineni
- **Affects:** BR-23 to BR-37 (new); `api/auth.py`, `api/config.py`, `api/db.py`; the frontend; deployment docs
- **Records:** decisions D1 to D3 taken on 2026-10-25 (see `docs/prompts/ART_FRAMEWORK.md`)

---

## Context

The platform was built as an **internal T&E migration tool for one operator**:

- One shared `X-API-Key` (`api/auth.py:21-26`), optional in `dev`.
- One uploads schema for everything (`settings.UPLOADS_SCHEMA`).
- No users, roles or tenants. The audit log records actions without an actor.
- Loads happen immediately on upload.
- The frontend's audit view reads browser `localStorage`.

On 2026-10-25 the product owner decided:

- **D1:** the platform becomes customer-facing with multi-tenant isolation.
- **D2:** full-dataset cell editing is in scope, stored as versions.
- **D3:** an approval workflow is in scope.

This ADR records that positioning change and what follows from it.

## Decision

The platform is repositioned from a single-operator internal tool to a **multi-tenant web application used by external customers**. It keeps its two import modes (freeform and strict T&E schema) and its T&E/V&V framing.

## Consequences

**Identity and access (BR-36)**
- Per-user authentication replaces the shared key for interactive use. The key gate can remain for service-to-service calls.
- Roles at minimum: *uploader*, *reviewer/approver*, *tenant admin*, *auditor (read-only)*.
- The sovereignty constraint (D6) rules out SaaS identity providers at runtime. Approved approach (2026-10-26): OIDC against an IdP the deployment controls, plus a local-account fallback for air-gapped installs.

**Tenant isolation (BR-36)**
- Approved model (2026-10-26): schema per tenant (Milestone 0, decision 6). Dynamic tables already live in a configurable schema, so this extends an existing pattern.
- Every request resolves to exactly one tenant, and the database session is scoped to it.
- Cross-tenant read and write attempts are standing negative tests from Milestone 2 onwards.

**Data handling (BR-24, BR-37)**
- Customer data must be preserved: the original file and source rows are kept, edits are versioned, and nothing is overwritten. The current `overwrite` path, which drops the prior table, is retired.
- Classification and retention rules become per-deployment configuration (decision 7, #49).

**Workflow (BR-26, BR-27, BR-32)**
- Upload no longer means import. Data passes review and approval first (ADR-0002).
- Separation of duties defaults to "the uploader cannot approve" (decision 5).

**Audit (BR-35)**
- Every event carries tenant and actor. The trail becomes append-only at database level, and reports come from the server, not the browser.

**What does not change**
- ADR-0001 (PostgreSQL first) and the deferred BR-02, BR-21 and BR-22 stay as they are.
- The README's "production-grade" framing stays (risk accepted, 2026-10-04).
- The React/TypeScript frontend (`csv-table-hub-main/`) remains the baseline. The plain-HTML frontend (PR #40) is outside this scope (decision 9, #50).

**Risk**
- Customer-facing use raises the cost of a defect. Assessment findings F1 to F4 should be fixed in Milestone 1 before any customer data arrives.
- A security review of the threat model is recommended before the first external tenant.
