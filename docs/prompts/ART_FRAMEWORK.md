# ART Framework v2: Altitude, Range and Technical Depth

**Target repository:** `PostgreDataMigrationAppWithCSVLoader`
**Path (confirmed 2026-10-25):** `C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader`
**Product owner:** Amarnath (Amar). Scope, requirement wording and direction are his decisions.

Use this framework to guide all analysis, design, implementation and validation of the CSV Import, Review, Deduplication and Audit capability. This is an **extension of an existing platform**, not a new build.

---

## Decisions already taken (2026-10-25). Do not re-ask these

| # | Decision | Consequence |
|---|---|---|
| D1 | The platform becomes **customer-facing with multi-tenant isolation**. | Tenant isolation is a core requirement, not an option. |
| D2 | **Full-dataset cell editing** is in scope. | Edits are stored as versions over the preserved original, never in place. |
| D3 | An **approval workflow** is in scope. | Import requires an explicit approval step. |
| D4 | Imports become **staged, approved and transactional**, with every imported row traceable to its approved version. This means threading the database connection (or an equivalent transactional boundary) through the loaders. | Supersedes the current post-commit upload-audit design. Record as an ADR (see Milestone 0). |
| D5 | Every new requirement gets a **BR ID in `docs/VCRM.md`** and is tracked there from day one. | Status starts as "Not started", never "Verified" without a test run. |
| D6 | A **data-classification and sovereignty constraint** applies (see Range). | No runtime dependency on external services. |
| D7 | The audit trail is **append-only, enforced at the database level**. | Convention alone does not satisfy the requirement. |

### Decisions that remain in force. Do not reopen
- **ADR-0001, PostgreSQL first.** Do not add DDL for other engines, rewrite BR-02, or re-add Tier X to CI.
- **"Production-grade" README framing.** Risk accepted by the product owner.
- Requirements marked "Deferred by decision" in `docs/VCRM.md` (BR-02, BR-21, BR-22) stay deferred.

---

## A — Altitude: business objective and desired outcomes

Work at the right level of abstraction before making implementation decisions.

### Business objective

Extend the existing CSV-to-PostgreSQL migration platform into a secure, reliable, customer-facing, multi-tenant web application. Customers must be able to:

- upload arbitrary CSV files
- inspect and review the complete dataset
- identify duplicate files and records
- include or exclude rows
- edit values
- obtain approval
- import the approved data into PostgreSQL

The platform keeps its existing freeform and strict (T&E schema) import modes.

The application must preserve the original uploaded data and keep a traceable history of every upload and material change. Its audit reports must establish what was uploaded, what was changed, who approved it, what was imported, and who performed each action.

### Desired outcomes

1. Customers can understand and validate their data before it enters the target database.
2. Repeated uploads are supported without silently overwriting previously imported data.
3. Duplicate files and records are identified transparently, with configurable handling rules.
4. Customers can correct or exclude unsuitable data before import.
5. Every material review decision, approval and data modification is traceable.
6. Imports are reliable, recoverable and protected against unintended data loss.
7. One tenant can never see or affect another tenant's data.
8. The system is maintainable, testable, secure and suitable for future enhancements.

### Success measures

Define measurable acceptance criteria for each of these areas:

- completeness of the data preview
- accuracy of duplicate detection
- import reconciliation
- audit coverage
- data integrity
- tenant isolation
- performance
- security
- test results

Record each criterion against its BR ID in the VCRM.

Successful execution is not the same as business success. Show that each requirement is met through evidence from automated tests and end-to-end workflows.

---

## R — Range: scope, constraints and boundaries

Define the scope explicitly before implementation.

### Included scope

Each item maps to a provisional requirement ID. **Before assigning IDs, read `docs/VCRM.md`.** Where an item is already covered by an existing BR (for example, SHA-256 file deduplication or import audit history), map it to that BR instead of creating a duplicate. Then number genuinely new items from the next free ID.

| Provisional ID | Requirement |
|---|---|
| BR-23 | Upload registry: unique ID, original filename, SHA-256, uploader, tenant, timestamp, processing status |
| BR-24 | Original uploaded file and parsed source data preserved immutably, separate from edits and approved data |
| BR-25 | Interactive preview of all rows and columns, with column type inference and validation |
| BR-26 | Row inclusion and exclusion, recorded with actor and reason |
| BR-27 | Cell editing stored as versions over the original, with original value, new value, actor, timestamp and reason |
| BR-28 | Exact-file duplicate detection using SHA-256, within and across uploads, per tenant |
| BR-29 | Configurable duplicate-record detection within and across uploads |
| BR-30 | Safe filename-derived PostgreSQL table naming, with support for repeated uploads of the same filename |
| BR-31 | Schema compatibility checks and import conflict handling, with no destructive schema changes |
| BR-32 | Approval workflow: submit, approve or reject, with recorded approver and decision |
| BR-33 | Staged, transactional, idempotent import with safe retries; every imported row traceable to its source row and approved version |
| BR-34 | Import reconciliation: rows in, excluded, edited and imported all account for each other |
| BR-35 | Append-only audit events enforced at the database level; filterable audit reports; exports protected against spreadsheet formula injection |
| BR-36 | Authentication, role-based authorisation and tenant isolation |
| BR-37 | Data classification and sovereignty (see Constraints) |

Automated tests, documentation and deployment instructions are part of every requirement, not separate items.

### Constraints

**Technology**
- React and TypeScript frontend, FastAPI and Python backend, PostgreSQL storage.
- The existing Lovable frontend (`csv-table-hub-main/`) is the React/TS baseline.

**Reuse before rebuild**
- Inspect the live repository before changing anything.
- Reuse working components and established conventions.
- Existing capabilities to assess first:
  - the `api/routers/` and `api/services/` structure
  - SHA-256 duplicate detection
  - `api/services/audit.py`
  - the freeform and strict import modes
  - the VCRM traceability view
  - the API key gate
  - `api/ratelimit.py`
  - the bash loaders in `build/csv/`

**Security**
- Treat uploaded files as untrusted input.
- Protect against:
  - SQL injection
  - malformed files
  - unsafe database identifiers
  - resource exhaustion
  - unauthorised and cross-tenant access
  - spreadsheet formula injection in exported reports

**Data preservation**
- Preserve original data and import history.
- Never silently discard columns, truncate values, overwrite earlier imports or make destructive schema changes.

**Data classification and sovereignty**
- Uploaded data, derived data and audit records must stay inside the deployment boundary.
- Prohibited at runtime:
  - external SaaS calls
  - telemetry
  - CDN assets
  - third-party AI or processing services
- The full stack must remain installable and runnable on-premise, including in air-gapped environments. This supports the 2026-11-15 offline-install commitment.
- Classification level is to be confirmed. Design so that data handling can be tightened per deployment without code changes.

**Append-only audit**
- Enforce immutability in the database. Options include:
  - a dedicated audit role with no UPDATE or DELETE grant
  - triggers that reject modification
  - a hash chain over events

  Propose the mechanism and test it, including a negative test that attempts an update and a delete.

### Unresolved decisions. Raise these in Milestone 0 with a recommended default for each

1. Maximum file size and expected concurrency.
2. Repeated uploads of the same filename: append to the same table, or create versioned datasets.
3. Default duplicate-record matching rule and resolution policy (skip, flag, or merge).
4. Whether partial imports are permitted.
5. Approval separation of duties: can an uploader approve their own data?
6. Tenant model: schema-per-tenant, database-per-tenant, or row-level security.
7. Data classification level, and the retention and privacy rules for raw uploads and audit records.
8. Performance targets and deployment environment.
9. **Frontend PRs:** close or keep PR #40 in this repo (the plain-HTML frontend at `/app`, which is outside the React/TS constraint) and PR #1 in `csv-table-hub`.

Do not ask about anything listed under "Decisions already taken".

Separate essential requirements from optional enhancements and future work. Do not expand scope beyond this document without explaining the benefit and cost, and getting approval.

---

## T — Technical depth: detail, verification and evidence

Work at the technical depth needed to implement, test and maintain a production-quality solution.

### Architecture and design depth

Document:

- system architecture and component responsibilities
- database entities, relationships, indexes and constraints
- API endpoints, request and response schemas, and error contracts
- CSV parsing, normalisation and type inference rules
- file-level and row-level duplicate detection algorithms
- safe filename-to-table-name mapping
- staging, approval, transaction and retry strategies
- audit event structure, immutability controls and reporting
- authentication, authorisation and tenant isolation
- logging, monitoring, performance and recovery mechanisms

The loaders currently own their own transactions, and the API shells out to them. For D4, present the options with trade-offs for product-owner approval. Do not implement before approval. Options include:

- moving the load into Python using psycopg `COPY` inside an API-owned transaction
- having the loaders write only to staging tables, with the API promoting the data transactionally
- other options you identify

Explain significant design decisions and their alternatives, especially where they affect data integrity, scalability, tenant isolation or auditability.

### Data integrity and audit depth

- Every upload has a unique identifier and keeps its tenant, original filename, content hash, uploader, timestamp and processing status.
- Original source data is held separately from proposed edits and from approved import data.
- Each material change records:
  - upload and import identifiers
  - row and column references
  - original and new values, where appropriate
  - actor and timestamp
  - reason and outcome
- Every imported row can be traced back to its source row and its approved version.
- Transactions, explicit failure handling and idempotency controls prevent partial or repeated imports from silently corrupting the target dataset.

### Testing and verification depth

Create automated unit, integration, API, database and end-to-end tests. Cover ordinary workflows and these edge cases:

- identical files uploaded repeatedly
- same filename with different contents
- duplicate records within and across uploads
- invalid CSV structures and encoding problems
- conflicting columns and incompatible data types
- edited and excluded rows
- approval rejected, then resubmitted
- failed imports, retries and concurrent requests
- unauthorised access and cross-tenant access attempts
- attempts to update or delete audit rows
- audit completeness and export correctness, including formula-injection payloads
- large-file processing and resource limits

Follow the repository's no-skip policy: a missing prerequisite fails with remediation text rather than skipping.

### Evidence rules

- A requirement is "Verified" only when a test run proves it. Quote the actual command and the actual pass, fail and skip counts.
- Documents such as `VCRM.md`, `FIXES_APPLIED.md` and `API_INTEGRATION.md` are claims, not evidence. `API_INTEGRATION.md` describes a superseded API.
- If something could not be run (for example, no database available), say so plainly.
- When searching the repository, exclude the stale worktree `.claude/worktrees/velvety-chasing-badger/`. It holds an old copy of `api/`.

### Implementation discipline

Deliver in small, complete, verifiable milestones. For each milestone:

1. State the objective and the BR IDs covered.
2. Explain the design and the expected changes.
3. Implement the change on a branch and open a PR. Never commit directly to `main`.
4. Run the relevant tests and inspect the actual results.
5. Update the documentation and the VCRM rows.
6. Identify unresolved defects and remaining work.

Do not claim that unimplemented or untested functionality is complete.

Every command given to the product owner states where to run it. Use a PowerShell `cd` with a quoted Windows path in the same block.

---

## Milestone 0: assess and plan (no production code changes)

1. **Baseline.** Run the existing test suite and lint. Record the commands and the actual counts.
2. **Assess the live code** against BR-23 to BR-37. For each item, record:
   - status: Exists, Partial or Missing
   - file and line evidence
   - the test that proves it, if any
3. **Draft VCRM rows** for the new requirements, mapped to existing BRs where they overlap. All start as "Not started" or "Partial", with the reason.
4. **Draft ADRs** for product-owner approval:
   - **ADR-0002, transactional staged import (D4).** This supersedes the post-commit audit design and presents the loader options.
   - **ADR-0003, customer-facing multi-tenant scope (D1–D3).** This records the positioning change from an internal T&E migration tool and its consequences.
5. **Propose the design** and a milestone plan, ordered so that each milestone is independently verifiable.
6. **Ask** only the unresolved decisions listed under Range, each with a recommended default and its trade-off.

Then **stop and wait for approval** before writing production code.

---

## ART decision rule

- Use **Altitude** to judge whether the solution achieves the intended business outcome.
- Use **Range** to judge whether a proposed feature or design is within the agreed scope and constraints.
- Use **Technical depth** to judge whether the implementation is detailed, secure, testable and evidenced enough.

When these dimensions conflict, explain the trade-off and recommend the simplest solution that meets the agreed requirements. Get approval before materially changing scope.
