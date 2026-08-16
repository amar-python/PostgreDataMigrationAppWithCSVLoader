# Quick Start — PostgreDataMigrationAppWithCSVLoader

A 10-minute walkthrough to get the full stack running locally: PostgreSQL
database, FastAPI backend, and React frontend.

For architecture and rationale see `docs/ARCHITECTURE.md`, `docs/VCRM.md`, and
`docs/API_INTEGRATION.md`.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| PostgreSQL | 17 or 18 | PG 18 recommended — installs on port 5433 by default |
| Python | 3.10+ | Must be on PATH |
| Node.js | 20+ | Required for the React frontend |
| Git Bash | Any | Required for bash scripts on Windows |
| psql client | Matching server | Windows: `C:\Program Files\PostgreSQL\<ver>\bin` |

---

## 1. Clone the repository

```powershell
git clone https://github.com/amar-python/PostgreDataMigrationAppWithCSVLoader.git
cd PostgreDataMigrationAppWithCSVLoader
```

---

## 2. Install Python dependencies

```powershell
pip install -r api\requirements.txt
pip install -r requirements-dev.txt   # only needed for running tests
```

---

## 3. Configure the dev environment

Copy the example env file and load it into your shell:

```powershell
# Load all dev env vars into the current session
Get-Content env.dev.example | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable(
            $matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}
```

> **Key values in `env.dev.example`:**
> - `PGPORT=5433` — PG 18 default (change to `5432` if using PG 17)
> - `PGPASSWORD=changeme_local_only` — update to match your local install
> - `API_KEY=` — empty is fine for local dev (unauthenticated)

To make `PGPORT=5433` permanent across all PowerShell sessions:

```powershell
Add-Content $PROFILE "`n`$env:PGPORT = `"5433`""
```

---

## 4. Provision the dev database

Requires Git Bash. Pass PG credentials explicitly:

```powershell
& "C:\Program Files\Git\bin\bash.exe" -c "
  cd '/c/Users/User/OneDrive/Desktop/Migration using ai/PostgreDataMigrationAppWithCSVLoader' &&
  PGUSER=postgres PGHOST=localhost PGPORT=5433 PGPASSWORD=changeme_local_only
  bash scripts/provision_full_test_env.sh
"
```

Expected output: `[✓] PostgreSQL reachable` followed by `[✓] Succeeded: dev`.

> **Note:** If you see `[✗] Deployment failed for dev` but the previous run
> already succeeded, this is a false positive — the database already exists.
> Run `bash build/deploy_all.sh dev` to confirm the real status.

---

## 5. Start the API (Terminal 1)

```powershell
# From the repo root
.\scripts\start-api.ps1
```

Or manually:

```powershell
$env:CORS_ORIGINS = "http://localhost:8080,http://localhost:5173,http://localhost:3000"
uvicorn api.main:app --reload --port 8000
```

Verify it's running: open `http://localhost:8000/api/health` — should return
`{"status": "ok"}`. Interactive docs at `http://localhost:8000/docs`.

> **Expected startup warnings (safe to ignore):**
> - `API_KEY is not set` — fine for local dev
> - `alembic.ini not found — skipping migration` — schema managed by
>   `provision_full_test_env.sh`, not Alembic

---

## 6. Start the frontend (Terminal 2)

```powershell
cd csv-table-hub-main

# First run only — create the env file
@"
VITE_API_BASE=http://localhost:8000
VITE_API_KEY=
"@ | Set-Content .env.local

# Install dependencies (first run only)
npm install

# Start the dev server
npm run dev
```

The frontend starts on **`http://localhost:8080`**. Open that URL in your
browser — you should see the CSV Table Hub upload interface.

Or use the convenience script from the repo root:

```powershell
.\scripts\start-frontend.ps1
```

---

## 7. Verify end to end

1. Open `http://localhost:8080`
2. Drop a CSV file onto the upload area
3. Preview the data and click Import
4. Check the Migrated Files table — your file should appear with row counts

---

## Run the Python test suite

```powershell
# Unit tests — no database needed
python -m pytest tests\ -m "unit or regression or security or snapshot" -q

# Integration tests — requires running API + provisioned database
python -m pytest tests\test_api_integration.py -v

# T&E mode integration tests
python -m pytest tests\test_te_loader_integration.py -v

# Per-environment contract tests
python -m pytest tests\environments\ -v

# Frontend tests
cd csv-table-hub-main
npm test
```

---

## Run the eval suite

```powershell
# Tier P — 23 CSV validator scenarios (no DB needed, ~5 seconds)
python evals\runner.py --tiers p

# All tiers — P + I (idempotency) + S (142 SQL assertions)
python evals\runner.py --tiers p,i,s
```

Expected: `total: 25, passed: 25, failed: 0`.

---

## PostgreSQL password reset (if forgotten)

Requires **admin PowerShell**:

```powershell
$hba = "C:\Program Files\PostgreSQL\18\data\pg_hba.conf"
(Get-Content $hba) -replace "scram-sha-256", "trust" | Set-Content $hba
Restart-Service postgresql-x64-18
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -p 5433 `
  -c "ALTER USER postgres WITH PASSWORD 'changeme_local_only';"
(Get-Content $hba) -replace "trust", "scram-sha-256" | Set-Content $hba
Restart-Service postgresql-x64-18
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `password authentication failed` | Wrong `PGPASSWORD` | Reset password using admin steps above |
| `Connection refused` on port 5433 | PG 18 not running | Open Services → start `postgresql-x64-18` |
| `alembic.ini not found` on API start | Expected — no Alembic in this repo | Safe to ignore |
| Frontend shows "This page didn't load" | API not running | Start the API first (Terminal 1) |
| `ERR_CONNECTION_REFUSED` in browser console | API stopped | Restart `uvicorn` |
| `npm run dev` fails with "Missing script" | Wrong directory | Must run from `csv-table-hub-main\`, not repo root |
| Deployment shows `[✗] failed for dev` | DB already exists | False positive — run `bash build/deploy_all.sh dev` to confirm |

---

## Directory structure

```text
PostgreDataMigrationAppWithCSVLoader/
├── api/                          ← FastAPI backend
│   ├── main.py                   ← app entrypoint, CORS, lifespan
│   ├── config.py                 ← env-var settings + TE_TABLES list
│   ├── db.py                     ← psycopg2 pool + Conn context manager
│   ├── auth.py                   ← optional X-API-Key guard
│   ├── routers/
│   │   ├── csv_routes.py         ← /api/csv/* endpoints
│   │   └── te_routes.py          ← /api/te/tables
│   ├── services/
│   │   ├── csv_parse.py          ← CSV parser + type inference
│   │   ├── dynamic_loader.py     ← creates csv_<hash> tables
│   │   └── te_loader.py          ← loads CSV into fixed T&E tables
│   └── requirements.txt
│
├── csv-table-hub-main/           ← React 19 + TanStack frontend (Lovable)
│   ├── src/routes/               ← file-based routes
│   ├── src/lib/                  ← export, mapping-templates, csv-preview
│   ├── src/__tests__/            ← 76 vitest tests
│   ├── .env.local                ← VITE_API_BASE, VITE_API_KEY (not committed)
│   └── package.json
│
├── build/                        ← SQL schema, loaders, deploy scripts
├── evals/                        ← 23 CSV scenarios + Tier I/S eval suite
├── infra/                        ← Azure / Terraform config
├── scripts/                      ← start-api.ps1, start-frontend.ps1, etc.
├── tests/                        ← Python test suite
│   ├── test_api_unit.py          ← 12 unit tests (no DB)
│   ├── test_api_integration.py   ← 19 integration tests
│   ├── test_te_loader_integration.py  ← 11 mode=te tests
│   ├── environments/             ← per-environment contract tests
│   └── snapshots/                ← committed CSV fixtures
│
├── env.dev.example               ← dev environment template
├── docs/ENV_VARIABLES.md              ← all env vars documented
├── docs/API_INTEGRATION.md            ← frontend ↔ API endpoint mapping
└── docs/VCRM.md                       ← business requirement traceability
```

---

## Next steps

- `docs/ENV_VARIABLES.md` — full list of every environment variable
- `docs/API_INTEGRATION.md` — frontend ↔ backend endpoint mapping and gaps
- `docs/VCRM.md` — business requirement traceability (142 SQL assertions)
- `docs/ARCHITECTURE.md` — three-layer architecture rationale
- `evals/USAGE.md` — eval runner flags and CI integration
