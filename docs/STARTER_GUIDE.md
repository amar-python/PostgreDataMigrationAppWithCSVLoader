# Starter Guide

Welcome. This doc is the front door for anyone new to
`PostgreDataMigrationAppWithCSVLoader` — what the project does, the two or
three ideas you need before the code makes sense, how to get it running, and
where to go next depending on what you're trying to do.

If you just want the fastest path to a running app, skip to
[Get it running](#get-it-running). Everything else here is context that makes
the rest of the docs click.

---

## What this project does

It's a web app for getting CSV files into PostgreSQL, built for Test &
Evaluation (T&E) programme management. A user drops a CSV in a browser, the
backend validates and loads it, and the row counts / errors show up in the
UI. The browser never talks to PostgreSQL directly — every read and write
goes through the FastAPI backend (`api/`).

There are three layers, and it helps to know which one you're touching:

| Layer | Where | Answers |
|---|---|---|
| Backend | `api/` (FastAPI + psycopg2) | How is a CSV parsed, validated, and inserted? |
| Frontend | `csv-table-hub-main/` (React 19 + TanStack) | What does the user click, and what do they see? |
| Database | `build/` (schema) + `infra/` (deployment) | What does the data look like, and where does it live per environment? |

For the full "every file belongs to exactly one category" breakdown, see
`docs/ARCHITECTURE.md`.

## The one concept that unlocks everything: two upload modes

Every CSV upload picks one of two modes, and most confusion about "why did
this table get created" or "why did my upload get rejected" traces back to
which mode was used:

- **Dynamic mode** — the CSV can be *anything*. The backend infers column
  types from the data and auto-creates a new table (`csv_<hash>`) to hold it.
  No schema to match. This is the "just import my spreadsheet" path.
  Implemented in `api/services/dynamic_loader.py`.

- **T&E mode** — the CSV must match one of the 12 fixed T&E tables
  (`organisations`, `test_programs`, `test_cases`, `defect_reports`, etc. —
  full list in the main `README.md`). Columns are validated against that
  table's schema and inserted row-by-row, with bad rows isolated rather than
  failing the whole file. This is the "load real programme data into the
  real schema" path. Implemented in `api/services/te_loader.py`.

Both modes go through the same `POST /api/csv/upload` endpoint, with a
`mode: "dynamic" | "te"` field distinguishing them — see
`docs/API_INTEGRATION.md` for the full request/response shapes.

## Multi-environment by design

The same codebase runs against four isolated databases — Dev, Test, Staging,
Prod — each with its own database name, schema, and app user (table in the
main `README.md` under "Multi-Environment Setup"). Staging and Prod are never
seeded with sample data; `tests/environments/` enforces that automatically.
If you're not sure which environment a command is touching, check
`docs/DATABASE_ENVIRONMENTS.md` and `docs/ENV_VARIABLES.md` before running
anything destructive.

---

## Get it running

Full step-by-step instructions (prerequisites, provisioning the dev
database, starting both servers, verifying end to end) live in
**`docs/QUICKSTART.md`** — follow that doc directly rather than a summary
here, since it's the one kept current with exact commands and Windows-specific
gotchas.

The short version, once you've followed QUICKSTART: two terminals running
(`.\scripts\start-api.ps1` and `.\scripts\start-frontend.ps1`), UI open at
`http://localhost:8080`, API health check green at
`http://localhost:8000/api/health`.

## Your first change: a guided walkthrough

Once the app is running locally, this sequence exercises both modes and the
test suite in about ten minutes — a good way to confirm your setup actually
works, not just that servers started.

1. **Upload a CSV in dynamic mode.** Any small CSV works — three columns,
   a few rows. Drop it on the upload area, preview it, confirm the import.
   Check the Migrated Files table for the new `csv_<hash>` table and row
   count.
2. **Upload a CSV in T&E mode.** Pick one of the 12 T&E tables (e.g.
   `organisations`), match your CSV's headers to its columns, and import.
   This exercises the validation path dynamic mode skips.
3. **Re-upload the same file.** Confirm duplicate detection kicks in
   (content-hash based, not filename based).
4. **Run the fast test suite** to confirm the backend is sane:
   ```powershell
   python -m pytest tests\ -m "unit or regression or security or snapshot" -q
   ```
5. **Run the frontend tests:**
   ```powershell
   cd csv-table-hub-main
   npm test
   ```

If all five pass/succeed, your environment is a faithful match for CI.

---

## Where to go next, by task

| I want to... | Read |
|---|---|
| Set up my dev environment from scratch | `docs/QUICKSTART.md` |
| Understand the repo's folder structure and why it's split that way | `docs/ARCHITECTURE.md` |
| See every frontend↔backend API call and its shape | `docs/API_INTEGRATION.md` |
| Look up an environment variable | `docs/ENV_VARIABLES.md` |
| Understand Dev/Test/Staging/Prod differences | `docs/DATABASE_ENVIRONMENTS.md` |
| Deploy to Azure | `docs/AZURE_DEPLOY.md` (non-prod) / `docs/PROD_DEPLOY.md` (prod) |
| Trace a business requirement to its test coverage | `docs/VCRM.md` |
| Check known gaps against the VCRM | `docs/VCRM_GAPS.md` |
| See the project's own standards self-audit | `docs/STANDARDS_AUDIT.md` |

## Conventions worth knowing before you write code

These aren't optional style preferences — they're enforced by tests or exist
because of a specific past incident:

- **All SQL identifiers (table/column names) go through
  `psycopg2.sql.Identifier()`** — never f-string interpolation. This is
  AST-checked by `tests/test_security.py`.
- **pytest markers matter**: `unit`, `integration`, `e2e`, `regression`,
  `security`, `snapshot`, `parity`. Run `unit` (and friends) for a fast,
  DB-free sanity check; `integration` and `e2e` need a live, provisioned
  PostgreSQL. See `pytest.ini` for the full marker list.
- **Staging and Prod are never seeded** — if you're touching provisioning
  scripts, don't make that possible even accidentally; there's a contract
  test for it in `tests/environments/`.

## If something doesn't work

`docs/QUICKSTART.md` has a troubleshooting table for the common local setup
failures (wrong PG password, port mismatch, API not running, etc.) — check
there first. For anything else, `docs/BUG_REPORT.md` and
`docs/DEFECT_INSERTED_ROWS.md` document known issues and their status.
