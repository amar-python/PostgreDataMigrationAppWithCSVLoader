# Frontend Integration — CSV Table Hub

Notes on the FastAPI backend in `api/`, which connects the React frontend in
`frontend/` (originally the standalone **csv-table-hub-main** project, now
merged into this monorepo) to PostgreSQL.

> **See also** the **Web UI + REST API** section of `README.md` for the
> user-facing quickstart (two-terminal launch, endpoint table, env vars). This
> file is the deeper design/integration doc — for how the backend is put
> together and what's still open.

---

## Architecture

```text
frontend/ (React 19 + TanStack Start)  →  api/ (FastAPI)  →  PostgreSQL
                                                          ├── csv_uploads schema  (dynamic mode)
                                                          └── te_<env>    schema  (te mode)
```

Schema names are configurable via `CSV_UPLOADS_SCHEMA` (default `csv_uploads`)
and `TE_SCHEMA` (default `te_dev`) — see `api/config.py`.

Two upload modes:

| Mode | Destination | Behaviour |
|---|---|---|
| `dynamic` | `csv_uploads.csv_<sha256[:16]>` | A typed table per CSV, columns derived from the header |
| `te` | Fixed T&E schema (`te_dev.*`) | Loads into one of the 12 core tables when the columns match |

`services/te_loader.match_te_table()` inspects the parsed columns and suggests a
T&E table, which drives the mode picker in the UI.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness; reports `ok` or `degraded`, never errors |
| POST | `/api/csv/preview` | Parse and type-detect without writing |
| POST | `/api/csv/upload` | Load (`mode: dynamic \| te`) |
| GET | `/api/csv/files` | Registered uploads — drives "Migrated files" |
| GET | `/api/csv/tables/{table}/rows` | Row preview, `limit` 1–200 |
| DELETE | `/api/csv/files/{id}` | Remove registration; drops the table in dynamic mode |

CSV content is sent as a JSON string, not multipart.

## Authentication

Every endpoint (including `/api/health`) requires an `X-API-Key` header
matching the `API_KEY` environment variable. If `API_KEY` is unset the check
is skipped — that's the local-dev default, and `api/main.py` logs a warning
at startup when it's unset so this isn't silently forgotten in a real
deployment. Set `API_KEY` (backend) and `VITE_API_KEY` (frontend, same value)
before deploying anywhere reachable beyond localhost. See `frontend/.env`.

> **Known DX gap** — if `API_KEY` and `VITE_API_KEY` don't match, every request
> returns 401 with no hint from either process. Tracked as BUG-006 in
> `BUG_REPORT.md`.

## What it does well

* **Deduplication at three levels** — filename, whole-file content hash, and
  per-row `_row_hash` with `ON CONFLICT DO NOTHING`. This is what the
  frontend's "no duplicates" promise needs.
* **Upload registry** — `csv_uploads.csv_files` records filename, hash, table, row
  count and columns, which is what "Migrated files" renders.
* **Structured logs** — every upload returns a timestamped `logs[]`, a ready
  foundation for the audit log.
* **Typed columns** via an allow-list, with per-row cast errors reported by row
  number and column.
* **Identifier safety** — `psycopg2.sql.Identifier` throughout; no string
  interpolation of identifiers. A test asserts this from the AST.
* **Connection pooling** and lifespan management rather than per-request
  connections.

---

## Findings

### 1. Package imports — RESOLVED

**Previous state:** `api/` used bare imports (`from config import settings`,
`from routers import csv_routes`). These resolved only when the process's
working directory was `api/`. `tests/test_api.py` therefore could not be
collected from the repository root, leaving the API as an untested surface.

**Resolution:** applied all three steps of the fix.

1. `api/__init__.py`, `api/routers/__init__.py`, and `api/services/__init__.py`
   now exist as empty package markers.
2. Every module under `api/` uses package-relative imports
   (`from api.config import settings`, `from api.db import Conn`, etc.).
3. `scripts/start-api.ps1` does `Set-Location (Join-Path $PSScriptRoot "..")`
   before invoking `python -m uvicorn api.main:app --reload --port 8000`.

Verified: `python -c "from api.main import app"` succeeds from the repo root.
`pytest tests/test_api.py` collects and runs the full suite.

### 2. No environment selector

The API is hardwired to a single database via `settings.PG_DATABASE`. The
framework's dev/test/staging/prod isolation — the point of the parameterised
schema — is not exposed, so the frontend can only ever reach one environment.

Adding an `env` query parameter constrained to an enum would surface it. Worth
doing before this is deployed anywhere with more than one environment.

### 3. `DELETE /api/csv/files/{id}` drops tables unguarded

The endpoint issues `DROP TABLE` for dynamic uploads with no confirmation, no
audit entry, and no environment guard. That is defensible for a local
uploads schema; it is not if the API is ever pointed at a shared or production
database. Consider an allow-list of droppable schemas, or an
`API_ALLOW_DESTRUCTIVE=1` gate.

Update: the `API_ALLOW_DESTRUCTIVE` gate and an `audit_log` table now exist,
and every endpoint (including this one) requires the `X-API-Key` header — see
[Authentication](#authentication). Callers still get no per-request
confirmation prompt; that remains a UI-level gap if accidental deletes become
a problem in practice.

### 4. Two CSV parsers now exist

`api/services/csv_parse.py` parses CSVs in Python. `build/csv/validator.py`
does too, and is covered by 23 Tier P eval scenarios. They can drift — a fix in
one will not reach the other.

This is a reasonable trade rather than a defect: the typed columns and
row-level dedup the frontend needs genuinely do not exist in the bash loader.
But it should be a recorded decision, and the API parser needs its own
scenario coverage, since it inherits none of Tier P's.

### 5. Table-name guard is prefix-and-length only

`GET /api/csv/tables/{table}/rows` guards with:

```python
if not table_name.startswith("csv_") or len(table_name) > 64:
    raise HTTPException(422, "Invalid table name")
```

Names such as `csv_a'--` or `csv_a; DROP TABLE personnel` satisfy both
conditions and reach the database layer. **No injection is possible** — the
`csv_files` lookup is parameterised, an unregistered name returns 404, and
`psycopg2.sql.Identifier` quotes the identifier. The registry check is doing the
real work.

Still, a stricter guard would reject them at the door rather than relying on
the layer below, since dynamic tables are always `csv_<sha256[:16]>`:

```python
import re
if not re.fullmatch(r"csv_[0-9a-f]{16}", table_name):
    raise HTTPException(422, "Invalid table name")
```

### 6. `mode: "te"` writes to the schema the test suite validates

`upload_te()` writes into the fixed T&E tables — the same 12 tables the 142 SQL
assertions verify. A defect there could corrupt the schema the whole suite
depends on. Of everything here, this path most needs tests; the current file
covers `dynamic` only, because `te_loader.py` behaviour was not available when
these were written.

---

## Migrations

Schema changes to `csv_uploads.*` are managed by Alembic. Migrations run
automatically at API startup (see `bootstrap()` in `api/db.py`) via
`alembic upgrade head` against the same database the API pool connects to.

**Layout:**

    alembic.ini                                      — Alembic config
    alembic/env.py                                   — Runtime config (reads api.config.settings)
    alembic/script.py.mako                           — Template for new revisions
    alembic/versions/0001_initial_uploads_schema.py  — Baseline (csv_files + audit_log + indexes)

**Adding a new migration:**

```bash
# Same env vars scripts/start-api.ps1 uses (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE):
python -m alembic revision -m "add updated_at to csv_files"
# Edit the generated alembic/versions/000N_add_updated_at_to_csv_files.py
# — write raw SQL in upgrade() and downgrade() via op.execute("ALTER TABLE ...").
# Alembic does NOT autogenerate for this project; there are no SQLAlchemy models.
python -m alembic upgrade head    # apply locally
```

Restart the API and every environment gets the new migration on next boot.

**Preview SQL without applying** (useful for review/PR):

```bash
python -m alembic upgrade head --sql > pending.sql
```

**Rollback the most recent migration:**

```bash
python -m alembic downgrade -1
```

**Limitations:**

- Migration files hard-code the schema name `csv_uploads`. Changing the
  `CSV_UPLOADS_SCHEMA` env var at runtime affects `api/` code but NOT
  Alembic's target schema. If you need a different schema name, write a
  rename migration.
- Startup migration is not multi-instance-safe — two API instances booting
  simultaneously can race the `alembic upgrade head` call. Fine for a single
  container per environment; adopt `pg_advisory_lock` if you scale out.
- The baseline migration (`0001_initial_uploads_schema.py`) uses
  `IF NOT EXISTS` clauses so it applies cleanly to databases that were
  bootstrapped by the pre-Alembic code path. Future migrations should NOT
  rely on that pattern — Alembic tracks state via the `alembic_version`
  table it creates automatically.

---

## Tests

`tests/test_api.py` provides 19 tests:

| Group | Count | Needs a database |
|---|---|---|
| `unit` — health contract, request validation | 9 | No |
| `unit` + `security` — table-name guards, AST identifier check | 3 | No |
| `integration` — upload → list → rows → dedup round trip | 7 | Yes |

Per the repository's no-skip policy, the integration group **fails** with
remediation text when the database is unreachable rather than skipping.

```bash
python -m pytest tests/test_api.py -m unit          # no database
python -m pytest tests/test_api.py                  # full
python scripts/test_report.py --strict              # whole suite
```

**Verification status:** all 19 tests verified green against the real `api/`
package and a live PostgreSQL 18 instance on port 5433 — 12 `unit` and 7
`integration`, the latter exercising the upload → list → rows round trip, both
deduplication paths (content hash and in-file row hash), and 404 handling for
unregistered tables.

The integration group needs `PGPASSWORD` set in the shell; `start-api.ps1`
prompts for it interactively, but pytest does not. Without it the suite fails
with remediation text rather than skipping, per the no-skip policy.

## Also required

CI installs only `requirements-dev.txt`. Because `tests/test_api.py` imports
FastAPI at module level, both workflows need:

```yaml
run: pip install -r requirements-dev.txt -r api/requirements.txt
```

Without it, pytest collection fails and every job goes red.
