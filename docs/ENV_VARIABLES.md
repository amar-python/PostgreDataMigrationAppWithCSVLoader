# Environment Variables Reference

**PostgreDataMigrationAppWithCSVLoader**
Last updated: August 2026

This document consolidates every environment variable used across the backend
API, build scripts, CI workflows, and frontend. Values marked **required in
production** must be set explicitly before deployment — they are never safe to
leave at their defaults outside a local developer machine.

---

## 1. PostgreSQL connection

These follow the standard libpq naming convention and are read by the API,
build scripts, and provisioning scripts.

| Variable | Default | Required in prod | Description |
|---|---|---|---|
| `PGHOST` | `localhost` | Yes | PostgreSQL host |
| `PGPORT` | `5433` (API) / `5432` (build scripts) | Yes | PostgreSQL port — note the all components default to **5432** |
| `PGUSER` | `postgres` | Yes | PostgreSQL superuser for provisioning; app user for normal operation |
| `PGPASSWORD` | _(empty)_ | Yes | PostgreSQL password — never commit a real value |
| `PGDATABASE` | `te_mgmt_dev` | Yes | Target database — switch per environment (see section 3) |

---

## 2. API settings

Read by `api/config.py`. Set these in the shell before running
`scripts/start-api.ps1` or in the Azure Container App environment.

| Variable | Default | Required in prod | Description |
|---|---|---|---|
| `API_KEY` | _(empty)_ | **Yes** | Shared secret sent in `X-API-Key` header. Empty = unauthenticated (local dev only). Set a strong random value for any non-localhost deployment. |
| `API_ALLOW_DESTRUCTIVE` | `false` | No | Set to `true` to enable `DELETE /api/csv/files/{id}`. Deliberately opt-in — never leave enabled in shared or prod environments. |
| `API_MAX_ROWS` | `100000` | No | Maximum data rows accepted per upload. Files over this limit are rejected before any per-row work. |
| `API_MAX_ROW_ERRORS` | `200` | No | Maximum row errors included in the JSON response body. Summary counts still reflect the true total. |
| `API_POOL_GETCONN_TIMEOUT` | `5.0` | No | Seconds a request waits to borrow a database connection from the pool. Exceeded = 503 response. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Yes | Comma-separated list of allowed CORS origins. Set to your frontend URL in production. |
| `CSV_UPLOADS_SCHEMA` | `csv_uploads` | No | Schema where per-CSV tables and the file registry live. |
| `TE_SCHEMA` | `te_dev` | No | Schema holding the 12 fixed T&E tables. Switch to `te_test`, `te_staging`, or `te_prod` per environment. |
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | No | Maximum file size accepted by the upload endpoint. |

---

## 3. Per-environment database config

Used by `build/config.env.example`, `scripts/provision_full_test_env.sh`, and
the environment SQL templates. Copy `build/config.env.example` to
`build/config.local.env` and fill in passwords before running setup.

| Variable | Dev | Test | Staging | Prod |
|---|---|---|---|---|
| `PG_DB_*` | `te_mgmt_dev` | `te_mgmt_test` | `te_mgmt_staging` | `te_mgmt_prod` |
| `PG_SCHEMA_*` | `te_dev` | `te_test` | `te_staging` | `te_prod` |
| `PG_APP_USER_*` | `te_dev_user` | `te_test_user` | `te_stg_user` | `te_prod_user` |
| `PG_APP_PASSWORD_*` | _(empty)_ | _(empty)_ | _(empty)_ | _(empty)_ |
| `PG_CONN_LIMIT_*` | `10` | `15` | `20` | `50` |
| `SEED_*` | `true` | `true` | `false` | `false` |

> **Staging and prod must never be seeded.** The `SEED_STAGING` and `SEED_PROD`
> variables default to `false`. Changing them to `true` will insert test data
> into production. The `tests/test_parity.py` contract tests verify this.

### Additional build-script variables

| Variable | Default | Description |
|---|---|---|
| `PG_SUPERUSER` | `postgres` | Superuser used by provisioning scripts |
| `PG_SUPERUSER_PASSWORD` | _(empty)_ | Superuser password — prompt by setup.sh if not set |
| `DB_ENGINE` | `postgresql` | Engine selector: `postgresql`, `mariadb`, `sqlite`, `influxdb`, `redis`, `teradata` |
| `TARGET_ENV` | `dev` | Active environment for build scripts |

---

## 4. Frontend (csv-table-hub-main)

Set in a `.env.local` file inside `csv-table-hub-main/` (not committed).
Create it by copying the table below.

| Variable | Default | Required | Description |
|---|---|---|---|
| `VITE_API_BASE` | _(empty — same origin)_ | Yes in prod | Base URL of the FastAPI backend. Empty = calls relative to the page origin (works when frontend and API are served from the same host). Set to `https://your-api.example.com` when they are separate. |
| `VITE_API_KEY` | _(empty)_ | Yes if API_KEY is set | API key sent in `X-API-Key` header. Must match `API_KEY` on the backend. |

**Example `csv-table-hub-main/.env.local` for local development:**
```
VITE_API_BASE=http://localhost:8000
VITE_API_KEY=
```

**Example for production:**
```
VITE_API_BASE=https://your-api.azurecontainerapps.io
VITE_API_KEY=your-strong-api-key-here
```

---

## 5. CI (GitHub Actions)

Set automatically by the workflow files. Listed here for reference.

| Variable | Value in CI | Workflow |
|---|---|---|
| `PGHOST` | `localhost` | `quality-gate.yml` (integration-postgres job) |
| `PGPORT` | `5432` | `quality-gate.yml` |
| `PGUSER` | `postgres` | `quality-gate.yml` |
| `PGPASSWORD` | `postgres` | `quality-gate.yml` |
| `PGDATABASE` | `postgres` | `quality-gate.yml` |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL service container password |

> The Windows CI job (`python-validator-tests.yml`) runs only database-free
> tests (unit, regression, security, snapshot) and sets no PG variables.
> G2 in `docs/GAP_ANALYSIS.md` documents this as an accepted limitation.

---

## 6. Static values (hardcoded in source)

These are not environment-controlled but are collected here for visibility.
Change them by editing the source file directly.

| Value | Location | Description |
|---|---|---|
| `5433` | `api/config.py` | Default PGPORT for the API (local PG 18) |
| `5432` | `build/config.env.example`, `scripts/provision_full_test_env.sh` | Default PGPORT for build scripts (standard PG) |
| `te_mgmt_dev` | `api/config.py` | Default database name |
| `csv_uploads` | `api/config.py` | Default uploads schema |
| `te_dev` | `api/config.py` | Default T&E schema |
| `100000` | `api/config.py` | Default max rows per upload |
| `200` | `api/config.py` | Default max row errors in response |
| `5.0` | `api/config.py` | Default pool connection timeout (seconds) |
| `52428800` | `api/config.py` | Default max upload size (50 MB) |
| `8000` | `scripts/start-api.ps1` | API port |
| `5173` | `api/config.py` (CORS default) | Frontend dev server port |
| `organisations, personnel, …` | `api/config.py` (TE_TABLES) | The 12 fixed T&E table names |

---

## 7. Quick-reference — what to set before each scenario

### Local development
```powershell
$env:PGPASSWORD = "your-local-postgres-password"
# API_KEY left empty — unauthenticated is fine locally
.\scripts\start-api.ps1
```

### Running tests
```powershell
$env:PGPASSWORD = "devpassword123"
python -m pytest tests\ -m "unit or regression or security or snapshot"
```

### Deploying to Azure
Set these in the Container App environment (not in code):
```
PGHOST         = your-pg-host.postgres.database.azure.com
PGPORT         = 5432
PGUSER         = postgres
PGPASSWORD     = <from Key Vault>
PGDATABASE     = te_mgmt_prod
API_KEY        = <strong random value>
CORS_ORIGINS   = https://your-frontend.azurestaticapps.net
TE_SCHEMA      = te_prod
CSV_UPLOADS_SCHEMA = csv_uploads
API_ALLOW_DESTRUCTIVE = false
```

And in the frontend build / Static Web App settings:
```
VITE_API_BASE  = https://your-api.azurecontainerapps.io
VITE_API_KEY   = <same value as API_KEY above>
```
