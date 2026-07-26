# Frontend Integration — CSV Table Hub

Notes on the FastAPI backend in `api/`, which connects the **CSV Table Hub**
frontend to PostgreSQL.

---

## Architecture

```text
CSV Table Hub (React)  →  api/ (FastAPI)  →  PostgreSQL
                                          ├── uploads schema   (dynamic mode)
                                          └── te_<env> schema  (te mode)
```

Two upload modes:

| Mode | Destination | Behaviour |
|---|---|---|
| `dynamic` | `uploads.csv_<sha256[:16]>` | A typed table per CSV, columns derived from the header |
| `te` | Fixed T&E schema | Loads into one of the 12 core tables when the columns match |

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

## What it does well

* **Deduplication at three levels** — filename, whole-file content hash, and
  per-row `_row_hash` with `ON CONFLICT DO NOTHING`. This is what the
  frontend's "no duplicates" promise needs.
* **Upload registry** — `uploads.csv_files` records filename, hash, table, row
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

### 1. Package imports — blocks testing (fix required)

`api/` uses bare imports (`from config import settings`, `from routers import
csv_routes`). These resolve only when the process's working directory is
`api/`, which is what `scripts/start-api.ps1` arranges with `Set-Location`.

The API runs correctly. But pytest collects from the repository root, so:

```text
$ python -c "import api.main"
ModuleNotFoundError: No module named 'config'
```

`tests/test_api.py` therefore cannot be collected, and the API is an **untested
surface** — invisible even to `scripts/test_report.py`, which can only account
for tests it can collect.

The fix is mechanical:

1. Add an empty `api/__init__.py`.
2. Make imports package-relative in every module under `api/`:

   ```python
   from api.config import settings
   from api.db import Conn
   from api.services.dynamic_loader import upload_dynamic
   from api.routers import csv_routes, te_routes
   ```

3. Update `scripts/start-api.ps1` to launch from the repository root:

   ```powershell
   Set-Location $PSScriptRoot\..
   python -m uvicorn api.main:app --reload --port 8000
   ```

Verified: with package-relative imports, `from api.main import app` succeeds
from the root and every endpoint responds.

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

## Tests

`tests/test_api.py` provides 17 tests:

| Group | Count | Needs a database |
|---|---|---|
| `unit` — health contract, request validation | 9 | No |
| `unit` + `security` — table-name guards, AST identifier check | 3 | No |
| `integration` — upload → list → rows → dedup round trip | 5 | Yes |

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
