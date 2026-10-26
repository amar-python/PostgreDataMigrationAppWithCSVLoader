# ADR-0002 — Transactional, staged, approved import

- **Status:** Accepted (product owner, 2026-10-26)
- **Date:** 2026-10-26
- **Decision maker:** Amarnath Rasineni
- **Affects:** BR-24, BR-32, BR-33, BR-34, BR-35; `api/services/dynamic_loader.py`, `api/services/te_loader.py`, `api/services/audit.py`
- **Supersedes:** the post-commit upload-audit design documented in `api/services/audit.py` (O-04)

---

## Context

Decision D4 (2026-10-25) requires imports to be staged, approved and transactional, with every imported row traceable to its approved version.

Today an upload is loaded the moment it arrives:

- **Dynamic mode** parses, casts and inserts in one psycopg2 transaction, then commits (`dynamic_loader.py:131-356`).
- **T&E mode** inserts with savepoints so failing rows are skipped and the rest commit (`te_loader.py`, commit at line 301). Partial import is by design.
- **Audit row** is written afterwards in a separate transaction (`csv_routes.py:86-93`). A crash between the two leaves an import with no audit row. A failed audit write is logged, never raised (`audit.py:9-22`).

There is no staging, no approval step and no link from an imported row back to its source row.

**Correction to the ART prompt.** The prompt assumes the API shells out to the bash loaders. It does not: `api/` contains no `subprocess` calls. The bash loaders in `build/csv/` serve only the batch pipeline and e2e tests. So the choice is about restructuring Python code the API already owns, not about wrapping shell scripts.

## Options

### A. API-owned transaction: COPY to staging, then promote (recommended)

1. **On upload:** store the original bytes and parsed source rows (insert-only tables). No target-table writes.
2. **During review:** record decisions and edits as rows, never updates.
3. **On approved import:** one transaction does all of the following, then commits:
   - `COPY` the effective rows (source, minus exclusions, plus the latest edits) into a staging table using psycopg2 `copy_expert`.
   - Validate types and keys in SQL.
   - `INSERT ... SELECT` into the versioned target table with `_source_row_id` and `_import_id`.
   - Write the `imports` record with reconciliation counts.
   - Write the audit events.
4. **Idempotency:** a client-supplied `Idempotency-Key`, with a UNIQUE constraint on `imports(upload_id, approval_id)`. A retry after a failure re-runs cleanly; a retry after success returns the original result.

- **For:** one atomic unit, so data, lineage and audit commit together or not at all. COPY is the fastest load path in PostgreSQL. It reuses `csv_parse.py` and the current identifier safety. There is nothing new to deploy.
- **Against:** the largest change to the loaders. Long imports hold one transaction open, which needs a statement timeout and a row cap (the current 100,000-row cap stays).

### B. Thread the connection through the existing loaders

Pass the caller's cursor into `upload_dynamic` and `upload_te`, so the audit INSERT joins the load transaction.

- **For:** small, contained change. It closes the post-commit audit window.
- **Against:** it covers none of staging, approval, lineage or edits. It would only be a step on the way to A.

### C. Bash loaders write to staging, API promotes

- **Against:** it adds a shell-out the API does not have today, splits one transaction across two processes, and puts untrusted CSV through bash. Rejected.

### D. Background import worker with a job table

The import runs in a worker process, with the job state in PostgreSQL. Promotion is transactional as in A.

- **For:** handles large files and concurrency without tying up API requests.
- **Against:** a new process to deploy and monitor, which counts against the air-gapped simplicity goal. Not needed at the current 100,000-row cap.

## Decision

**Adopt A.** Keep D as the documented upgrade path if decision 1 (file size and concurrency) later rises beyond what one request transaction can handle.

T&E mode moves to the same flow. Its row-level error isolation becomes a review-time result (rows flagged and excluded before approval) instead of a load-time skip. That honours decision 4's recommended default of no partial imports.

## Consequences

- `audit.py`'s "known limitation" goes away. `record_audit` (separate transaction) is retired in favour of in-transaction writes.
- Loader signatures change. The existing `/api/csv/upload` stays as a compatibility path until the frontend moves to the review flow, and is then removed in a later milestone.
- Needs Alembic migrations first (assessment finding F4).
- Tests must include failure injection mid-import (no partial target rows, no audit row), a retry after failure, and a retry after success (no duplicate rows).
