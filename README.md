# PostgreDataMigrationAppWithCSVLoader

> A production-grade **CSV-to-PostgreSQL data migration platform** for
> **Test & Evaluation (T&E)** programme management — with a FastAPI backend,
> React frontend, and a 142-assertion SQL test suite.

[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%2B-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.140%E2%80%930.141-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-139%20vitest%20%7C%20142%20SQL%20assertions-brightgreen)](#test-suite)

---

## Status

- Actively developed by a single maintainer.
- PostgreSQL is the only supported engine for now. The other five engine
  adapters in `build/adapters/` are kept but not maintained
  ([ADR-0001](docs/adr/0001-postgresql-first.md)).
- CI (`.github/workflows/quality-gate.yml`) runs on every push to `main` and on pull requests:
  unit tests, lint and Tier P evals, plus an integration job that deploys all
  four environments to PostgreSQL 16 and runs eval Tiers P, I, S and E and the
  full pytest suite.
- Requirement-by-requirement verification status is in [`docs/VCRM.md`](docs/VCRM.md).

## Known Limitations

- **Engines:** six-engine support (BR-02) is deferred by decision. Tier X
  cross-engine evals run on demand only (`make evals-engines`).
- **Scale:** performance at ≥ 1 M rows (BR-22) and cross-engine equivalence
  (BR-21) are deferred and untested.
- **Audit timing:** the upload audit row is written after the load commits.
  A crash in that window leaves a loaded table with no audit row.
- **Authentication:** people sign in per user: local accounts with lockout,
  OIDC, four roles (`docs/ROLES.md`) and a schema per tenant. The shared
  `API_KEY` is for scripts and services only; the browser never holds it. The
  API refuses to start outside `dev` without `API_KEY`. Requests that use the
  key reach the default schemas, not any tenant's.
  Users change their own password from the header; a tenant admin can reset
  members of their own tenant only. A user who belongs to more than one tenant
  can be reset only by an operator with `scripts/reset_password.py` (#117).
- **Upload failure reasons:** the per-row reasons and step log for an upload
  are kept in the uploading browser's Import history, not on the server; the
  server keeps only the counts. Server-side storage is planned for M3 (#107).
- **Rate limiting:** in-process only, so it suits a single API instance.
- **Frontend audit page:** shows this browser's local import history, not the
  server audit log (see the naming note under Frontend Features).
- **Offline install:** procedure in `docs/offline-install.md`, rehearsed with networking off. The clean-VM dry run (#60) is still to do. It targets Ubuntu 24.04 only; an offline container bundle for Windows, macOS and Linux is tracked as #128 (BR-38).

## For Reviewers

| To check | Look at |
|---|---|
| Requirements traced to tests | [`docs/VCRM.md`](docs/VCRM.md) |
| Why things are the way they are | [`docs/adr/`](docs/adr/) and [`DECISIONS/`](DECISIONS/) |
| Eval scenarios and expected outcomes | `evals/datasets/` and `evals/expected/` |
| SQL assertion suites | `tests/suites/` |
| What CI actually runs | `.github/workflows/quality-gate.yml` and the Actions tab |

---

## What This Is

A unified platform combining a T&E database framework with a browser-based
CSV migration UI. The browser never talks to PostgreSQL directly — every read
and write goes through the FastAPI backend.

**Key capabilities:**

- Upload any CSV — auto-creates a typed PostgreSQL table from the shape of your
  data (dynamic mode)
- Upload into fixed T&E tables — validates columns against one of the 12 core
  T&E tables and inserts row-by-row with error isolation (T&E mode)
- Preview data before importing — see headers, inferred types, and sample rows
- Audit log — every import is registered with file name, row counts, and
  timestamp
- Duplicate detection — re-uploading the same file is detected by content hash
- Multi-environment — Dev, Test, Staging, and Prod with isolated databases,
  schemas, and users

---

## Repository Structure

```text
PostgreDataMigrationAppWithCSVLoader/
│
├── api/                              ← FastAPI backend
│   ├── main.py                       ← app entrypoint, CORS, lifespan
│   ├── config.py                     ← env-var settings, TE_TABLES list
│   ├── db.py                         ← psycopg2 connection pool
│   ├── auth.py                       ← optional X-API-Key guard
│   ├── routers/
│   │   ├── csv_routes.py             ← /api/csv/* (upload, preview, files, rows)
│   │   └── te_routes.py              ← /api/te/tables (T&E table row counts)
│   ├── services/
│   │   ├── csv_parse.py              ← CSV parser + type inference
│   │   ├── dynamic_loader.py         ← creates csv_<hash> tables from any CSV
│   │   └── te_loader.py              ← loads CSV into fixed T&E tables
│   └── requirements.txt
│
├── csv-table-hub-main/               ← React 19 + TanStack frontend (Lovable)
│   ├── src/routes/
│   │   ├── _authenticated/index.tsx  ← main upload + migration UI (13 features)
│   │   └── audit.tsx                 ← audit log page
│   ├── src/lib/
│   │   ├── export.ts                 ← CSV / XLSX / PDF export
│   │   ├── mapping-templates.ts      ← saved column mapping templates
│   │   └── csv-preview.ts            ← CSV parsing utilities
│   ├── src/__tests__/                ← 139 vitest tests
│   ├── .env.local                    ← VITE_API_BASE (not committed)
│   └── package.json
│
├── build/                            ← SQL schema, loaders, deployment scripts
│   ├── te_core_schema.sql            ← 12-table T&E schema
│   ├── te_seed_data.sql              ← realistic Australian T&E seed data
│   ├── csv/validator.py              ← pure-Python CSV validator
│   ├── deploy_all.sh                 ← multi-environment deployment router
│   └── environments/                 ← per-environment SQL config files
│
├── evals/                            ← data-driven black-box eval suite
│   ├── runner.py                     ← scenario runner + JSON reports
│   └── datasets/tier_p/             ← 23 CSV validator scenarios
│
├── infra/                            ← Azure Container Apps + Terraform
│
├── scripts/
│   ├── start-api.ps1                 ← Terminal 1: FastAPI on :8000
│   ├── start-frontend.ps1            ← Terminal 2: Vite on :8080
│   └── provision_full_test_env.sh    ← one-command DB setup
│
├── tests/
│   ├── test_api_unit.py              ← 12 unit tests (no DB required)
│   ├── test_api_integration.py       ← 19 integration tests
│   ├── test_te_loader_integration.py ← 11 T&E mode integration tests
│   ├── environments/                 ← 4 per-environment contract tests
│   └── snapshots/                    ← committed CSV test fixtures
│
├── env.dev.example                   ← dev environment template
├── docs/ENV_VARIABLES.md                  ← all environment variables documented
├── docs/API_INTEGRATION.md                ← frontend ↔ API endpoint mapping
├── docs/QUICKSTART.md                     ← 10-minute setup guide
└── docs/VCRM.md                           ← business requirement traceability
```

---

## Quick Start

See **`docs/QUICKSTART.md`** for the full 10-minute walkthrough. Summary:

```powershell
# 1. Clone
git clone https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader.git
cd PostgreDataMigrationAppWithCSVLoader

# 2. Install Python deps
pip install -r api\requirements.txt

# 3. Load dev env vars
Get-Content env.dev.example | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}

# 4. Provision dev database. Needs bash on PATH; on Windows make sure it is
#    Git Bash, not the WSL bash.exe in System32.
#    Replace REPLACE_ME with your local postgres password. If 5432 is taken
#    by another PostgreSQL instance, use the port your target instance uses.
#    See env.dev.example for the configuration template.
bash -c "PGUSER=postgres PGHOST=localhost PGPORT=5432 PGPASSWORD=REPLACE_ME bash scripts/provision_full_test_env.sh"

# 5. Terminal 1 — start the API
.\scripts\start-api.ps1

# 6. Terminal 2 — start the frontend
.\scripts\start-frontend.ps1

# 7. Open the UI
Start-Process "http://localhost:8080"
```

---

## API Surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | DB reachability + PostgreSQL version |
| `POST` | `/api/csv/preview` | Parse CSV, infer types, suggest T&E table match |
| `POST` | `/api/csv/upload` | Load CSV — `mode: "dynamic"` or `mode: "te"` |
| `GET` | `/api/csv/files` | List all uploaded CSVs |
| `GET` | `/api/csv/tables/{name}/rows` | Preview rows of a dynamic table |
| `DELETE` | `/api/csv/files/{id}` | Drop a dynamic table (requires `API_ALLOW_DESTRUCTIVE=true`) |
| `GET` | `/api/audit/log` | Paginated audit trail of uploads and deletions (action, file, table, mode, time) — not currently called by the shipped frontend, see note below |
| `GET` | `/api/te/tables` | Existence + row counts for the 12 fixed T&E tables |

Interactive docs: `http://localhost:8000/docs`

---

## Frontend Features (13)

> **Naming note:** the "audit log" features below (`/audit` route, `audit.tsx`)
> operate on **this browser's local import history** (`localStorage`, populated
> as you run imports in this session) — not the backend's `GET /api/audit/log`
> endpoint (server-side upload and deletion history), which the shipped frontend never
> calls. `audit.tsx` also renders a small, separate, hardcoded developer
> changelog widget (`src/lib/audit-log.ts`) alongside the import-history view;
> that's app release notes, unrelated to either audit trail above. Three
> different things share the word "audit" here — worth knowing before you go
> looking for server-side audit data in the UI.

| Feature | Description |
|---|---|
| Audit log filters | Filter by date, status, file name |
| Invalid row export | Download rejected rows as CSV / XLSX / PDF |
| Header rename / mapping confirmation | Review column mappings before import |
| Retry from audit log | Re-run a previous import with one click |
| Mapping templates | Save and reuse column mapping configurations |
| Per-file error modal | See row errors inline without leaving the page |
| Bulk selection | Select and action multiple files at once |
| Cancel / stop active imports | Interrupt a running import |
| Duplicate diff preview | See what changed between duplicate file uploads |
| Audit report download | Export the full audit log as a file |
| Browser notifications | Get notified when a long import completes |
| XLSX export | Download table data as Excel |
| CSV preview | See data before committing to import |

---

## Test Suite

### Python tests

```powershell
# Unit tests — no database needed (~5 seconds)
python -m pytest tests\ -m "unit or regression or security or snapshot" -q

# Integration tests — requires running API + provisioned database
python -m pytest tests\test_api_integration.py -v
python -m pytest tests\test_te_loader_integration.py -v

# Per-environment contract tests
python -m pytest tests\environments\ -v
```

### Frontend tests (139 vitest)

```powershell
cd csv-table-hub-main
npm test
```

### SQL assertion suite (142 assertions)

```powershell
bash tests/run_tests.sh dev
```

### Eval suite

```powershell
python evals\runner.py --tiers p,i,s,e   # 26 scenarios: Tier P 23, I 1, S 1, E 1
```

### CI

| Workflow | Runner | Scope |
|---|---|---|
| `quality-gate.yml` — `free-tier` | ubuntu | unit, regression, security, snapshot |
| `quality-gate.yml` — `integration-postgres` | ubuntu + PG | full suite, all 4 environments |
| `python-validator-tests.yml` | windows | database-free markers |

---

## Environment Variables

See **`docs/ENV_VARIABLES.md`** for the full reference. Key variables:

| Variable | Default | Description |
|---|---|---|
| `PGHOST` | `localhost` | PostgreSQL host |
| `PGPORT` | `5432` | PostgreSQL port. Set it to your instance's port if 5432 is taken |
| `PGPASSWORD` | _(empty)_ | PostgreSQL password |
| `PGDATABASE` | `te_mgmt_dev` | Target database |
| `API_KEY` | _(empty)_ | Shared secret for `X-API-Key` header (empty = unauthenticated) |
| `CORS_ORIGINS` | `http://localhost:8080,...` | Allowed frontend origins |
| `TE_SCHEMA` | `te_dev` | Schema for the 12 T&E tables |
| `API_ALLOW_DESTRUCTIVE` | `false` | Enable `DELETE /api/csv/files/{id}` |

---

## T&E Schema — 12 Tables

```text
organisations ──< personnel
      │
      └──< test_programs ──< temp_documents
                  │
                  └──< test_phases ──< test_cases ──< vcrm_entries >── requirements
                              │
                              └──< test_events ──< test_results ──< evidence_artifacts
                                                         │
                                                         └──< defect_reports
```

| Table | Purpose |
|---|---|
| `organisations` | Agencies, prime contractors, test units |
| `personnel` | T&E workforce with clearance levels and roles |
| `test_programs` | Top-level programmes (e.g. CYB9131, LAND 400 Ph3) |
| `temp_documents` | Versioned TEMP documents |
| `test_phases` | DT&E, AT&E, OT&E phases within a programme |
| `requirements` | System requirements subject to T&E verification |
| `test_cases` | Individual test cases with steps and expected results |
| `vcrm_entries` | VCRM — maps requirements ↔ test cases |
| `test_events` | Scheduled/completed test events |
| `test_results` | Execution outcomes per test case per event |
| `defect_reports` | Deficiency Reports linked to failed results |
| `evidence_artifacts` | Logs and reports attached to test results |

---

## Multi-Environment Setup

| Setting | Dev | Test | Staging | Prod |
|---|---|---|---|---|
| Database | `te_mgmt_dev` | `te_mgmt_test` | `te_mgmt_staging` | `te_mgmt_prod` |
| Schema | `te_dev` | `te_test` | `te_staging` | `te_prod` |
| App User | `te_dev_user` | `te_test_user` | `te_stg_user` | `te_prod_user` |
| Connection Limit | 10 | 15 | 25 | 50 |
| Seed Data | ✅ | ✅ | ❌ | ❌ |

Staging and Prod are **never seeded**. The `tests/environments/` contract tests
verify this automatically.

---

## Azure Deployment

See `docs/AZURE_DEPLOY.md` and `infra/` for full deployment instructions. The API
and frontend run as separate Azure Container Apps in the same environment.
Dev (`infra/terraform`) runs PostgreSQL as a Container App with
`external_enabled = false`, so the database is not publicly reachable. Test,
staging and prod (`infra/terraform-test`, `-staging`, `-prod`) use Azure
Database for PostgreSQL Flexible Server.

---

## License

MIT — see [LICENSE](LICENSE) for full text.

---

## Acknowledgements

Built with [PostgreSQL](https://www.postgresql.org/) 17+, [FastAPI](https://fastapi.tiangolo.com/), [React 19](https://react.dev/), and [Lovable](https://lovable.dev/).
