# Standards Audit

A targeted compliance scan against two yardsticks: this repo's own CLAUDE.md
rules, and a stack-relevant industry-practice checklist (SQL injection,
secrets, input validation, authN, CORS, error handling, frontend XSS, infra
secrets). Report only — no fixes applied as part of this pass.

**Assessed at:** `main` @ `58e91e4`
**Method:** static read-through and grep across `api/`, `build/`,
`csv-table-hub-main/`, `infra/`, `docs/` (excluding the nested
`.claude/worktrees/` copy). Evidence is file:line references, not inferred.
**Scope decisions:** see the design-tree discussion this audit was grilled
out of — full repo, targeted scan (not exhaustive manual review), CLAUDE.md's
4 generic behavioral principles checked with best-effort proxies where one
exists.

---

## Summary

| # | Item | Verdict |
|---|------|---------|
| 1 | SQL identifiers via `psycopg2.sql.Identifier()` | PASS |
| 2 | Test markers (`unit` vs `integration`) correctly applied | PASS |
| 3 | SQL injection via values (parameter binding) | PASS |
| 4 | Secrets hygiene | PARTIAL — RESOLVED 2026-08-13 |
| 5 | Input validation (Pydantic models) | PASS |
| 6 | AuthN consistency (`X-API-Key`) | PASS |
| 7 | CORS config | PASS |
| 8 | Error handling (no leakage) | RESOLVED 2026-08-13 (2 fixed, 1 by-design) |
| 9 | Frontend XSS | PASS |
| 10 | Infra secrets (Terraform) | PASS |
| 11 | Think Before Coding (CLAUDE.md) | N/A |
| 12 | Surgical Changes (CLAUDE.md) | N/A (informational) |
| 13 | Simplicity First (CLAUDE.md) | PASS |
| 14 | Goal-Driven Execution (CLAUDE.md) | PASS |

**12 PASS, 2 N/A, 0 FAIL.** Both original PARTIALs (secrets hygiene, error
handling) have since been resolved — see items 4 and 8 below for what
changed and when.

---

## Project-specific rules (CLAUDE.md)

### 1. SQL identifiers via `psycopg2.sql.Identifier()` — PASS

Every `CREATE TABLE` / `DROP TABLE` / `INSERT` / `SELECT` / `DELETE` that
builds identifiers uses `sql.SQL(...).format(sql.Identifier(...), ...)`:

- `api/services/dynamic_loader.py` — lines 136-138, 155-158, 228-239,
  301-304, 320-324
- `api/services/te_loader.py` — lines 85-108, 171-181, 293-298
- `api/db.py` — `_bootstrap_fallback_schema()`, lines 195-226
- `api/routers/csv_routes.py`, `te_routes.py`, `audit_routes.py`,
  `api/main.py` (health check, lines 93-97)
- `build/csv/loader_postgresql.sh` — regex-validates `TABLE_NAME`/`SCHEMA`/
  `DB_NAME` (line 42) and quotes via `pg_quote_ident` before use (lines
  124-135)

Self-enforced by an AST-based test: `tests/test_api_unit.py:134-153`
(`test_identifiers_are_never_string_formatted`) fails the build if any
`.execute()` call's first argument is an f-string.

The only f-string near SQL-sounding code is a **log message**, not executed
SQL: `api/services/dynamic_loader.py:232` — the real `CREATE TABLE` at lines
233-239 still uses `sql.Identifier`.

### 2. Test markers correctly applied — PASS

- `pytest.ini` registers `unit`, `integration`, `e2e`, `regression`,
  `security`, `snapshot`, `parity` (lines 2-9).
- `tests/test_api_unit.py` — all classes marked `@pytest.mark.unit`; every
  test hits validation/guard code paths that return before `Conn()` is ever
  opened (e.g. `test_upload_rejects_unknown_mode`, line 91-94).
- `tests/test_api_integration.py` and `tests/test_te_loader_integration.py` —
  all classes marked `@pytest.mark.integration`.
- `tests/conftest.py` has no global DB bootstrap that could leak into unit
  tests.

---

## Industry-standard checklist

### 3. SQL injection via value binding — PASS

Every value passed to `cur.execute(...)` across `api/services/*.py`,
`api/routers/*.py`, `api/db.py` uses `%s` placeholders with a params
tuple/list (or `sql.Placeholder()`). No string-interpolated values found in
any `.execute()` call.

### 4. Secrets hygiene — PARTIAL — RESOLVED 2026-08-13

- `.gitignore` correctly excludes `.env`, `.env.*` (except `.env.example`),
  `*.tfvars` (except `.tfvars.example`), `*.local.env`, `*.pgpass`, and
  Terraform state. Confirmed via `git check-ignore -v`: `.env`,
  `csv-table-hub-main/.env.local`, `build/config.local.env` are all ignored
  and none is tracked.
- **Finding:** the literal `devpassword123` is committed in tracked files —
  `env.dev.example:10`, `docs/ENV_VARIABLES.md:153`,
  `docs/QUICKSTART.md:57,75,195`. It reads as a real (if low-value) password
  rather than an obviously-fake placeholder like `CHANGEME`. The consuming
  code paths are all local-dev-only, so exploitability is low, but it's
  still a real credential string living in source control.
- `api/config.py:10` defaults `PG_PASSWORD` and `API_KEY` to `""` (safe).
- No hardcoded credentials found in `csv-table-hub-main/src` (`.ts`/`.tsx`).

**Fix applied:** `devpassword123` replaced with `changeme_local_only` across
`env.dev.example:13`, `docs/ENV_VARIABLES.md:153`,
`docs/QUICKSTART.md:57,75,195`, and `README.md:122` — same value everywhere
so the local-dev flow (set your Postgres password → export it →
run tests) stays self-consistent, but the string now reads unambiguously as
a placeholder rather than a plausible real password. `build/config.local.env`
(gitignored, not committed) was left untouched.

### 5. Input validation (Pydantic models) — PASS

`api/routers/csv_routes.py:25-36` — `PreviewRequest` and `UploadRequest`
(both `BaseModel`, with `Field` length constraints) are the typed parameters
for the only two POST routes. No raw `dict`/`Request.json()` parsing found.

### 6. AuthN consistency (`X-API-Key`) — PASS

- `api/auth.py:10-15` — `require_api_key`, constant-time comparison via
  `secrets.compare_digest`.
- Applied at router level in `csv_routes.py:18-22`, `te_routes.py:10-14`,
  `audit_routes.py:14-18` — every route in each router inherits the guard.
- `/api/health` (`main.py:82-83`) is the sole deliberate exception, with an
  explanatory comment (line 59-61) and a dedicated test asserting it's
  intentional: `tests/test_api_integration.py:46-59`.

### 7. CORS config — PASS

`api/main.py:64-69` configures `CORSMiddleware` with
`allow_origins=settings.CORS_ORIGINS`; `api/config.py:20-22` defaults to
`http://localhost:5173,http://localhost:3000`. No wildcard `allow_origins`
found anywhere in `api/`, `infra/`, `docs/`, or `build/`.

### 8. Error handling (no leakage) — PARTIAL

Good pattern in `api/services/dynamic_loader.py:108-118` — `psycopg2.Error`
is caught and mapped to a fixed generic message, not the raw exception.

**Findings** — three spots returned truncated raw exception text to the client:

- `api/main.py:105-107` — **RESOLVED 2026-08-13.** `/api/health`
  (unauthenticated) used to return `str(exc).split("\n")[0][:200]` on DB
  connection failure, which could include host/port/user details from
  psycopg2's `OperationalError` message. Now returns a fixed message
  (`"Database is unreachable or not fully bootstrapped."`); the real
  exception is still logged server-side via `logger.warning`. Verified with
  `pytest tests/test_api_unit.py -m unit` (12 passed) — no test asserts on
  the `error` field's content, only `status`.
- `api/routers/csv_routes.py:46-53` — **RESOLVED 2026-08-13.** CSV parse
  failures used to return `f"The CSV couldn't be parsed: {str(exc)[:200]}"`
  (raw Python exception text). Now returns a fixed message
  (`"The CSV couldn't be parsed. Check the file's structure and try
  again."`); the real exception is logged server-side via
  `logger.warning`. Verified with `pytest tests/test_api_unit.py -m unit`
  (12 passed).
- `api/services/te_loader.py:274-281` — **assessed, left as-is by design.**
  Per-row DB errors return `str(exc).split("\n")[0]` in `rowErrors[]`. On
  review this isn't a leak in the same sense as the other two: it's the
  mechanism behind the project's advertised row-by-row error-isolation
  feature, the endpoint is authenticated (`X-API-Key`), it's already
  truncated to one line, and a typical constraint-violation message here
  (e.g. `duplicate key value violates unique constraint "te_missions_pkey"`)
  carries no host/port/credential detail — just the reason a specific row
  failed, which the user needs to fix their CSV. Curating it away would
  quietly remove real diagnostic value for a security benefit that doesn't
  apply in an authenticated context. Revisit if this endpoint is ever made
  unauthenticated.

No full stack traces or file paths leak — everything is truncated to a
single line ≤200 chars, and FastAPI's default (non-debug) 500 handler is
untouched.

Both genuine leaks (health check, CSV parse) are now fixed. The remaining
per-row `te_loader.py` case is a deliberate design choice, not an open
remediation item — see above.

### 9. Frontend XSS — PASS

No `dangerouslySetInnerHTML`, raw `innerHTML` assignment, or `eval(` found
anywhere in `csv-table-hub-main/src`.

### 10. Infra secrets (Terraform) — PASS

- `infra/terraform/main.tf:121,136-138` and
  `infra/terraform-prod/main.tf:213,223-224,242` generate the PG password via
  `random_password` and store it in Azure Key Vault; consumers reference
  `random_password.pg_password.result`, never a literal.
- No `.tfvars` committed, only non-secret `.tfvars.example` files.
- Noted for context, not a secret: `infra/terraform-prod/main.tf:183` —
  `public_network_access_enabled = true # temporarily enabled so Terraform
  can seed the secret; flip to false after bootstrap` — a documented,
  presumably-temporary public-access flag worth revisiting.

---

## CLAUDE.md generic principles (best-effort proxies)

These four are written as process guidance for how changes get made, not all
of them describe a property observable in a finished file — see verdicts
below for which ones have a real static proxy.

### 11. Think Before Coding — N/A

Describes deliberation before writing code; not observable in a static
snapshot of the repo.

### 12. Surgical Changes — N/A (informational only)

`git log --oneline -20` shows mostly single-concern commits (e.g.
`9c38830 fix: escape SCHEMA/DB_NAME/TABLE_NAME in COPY/LOAD/COUNT
statements`). One commit bundles three concerns in its message:
`102d613 fix: send X-API-Key from frontend, fix orphaned-table leak, resolve
G1/G5`. Presented as informational only, not a scored verdict — diff
discipline within a single commit isn't reconstructable from the log alone.

### 13. Simplicity First — PASS

No plugin systems, strategy/factory abstractions, or feature-flag
scaffolding found in `api/`. Every `Settings` field in `api/config.py`
(`PG_*`, `UPLOADS_SCHEMA`, `TE_SCHEMA`, `CORS_ORIGINS`, `MAX_UPLOAD_BYTES`,
`MAX_ROWS`, `MAX_ROW_ERRORS_REPORTED`, `POOL_GETCONN_TIMEOUT`,
`allow_destructive`, `API_KEY`) has a confirmed caller elsewhere in `api/`.

### 14. Goal-Driven Execution — PASS

Every feature the README claims (upload/dynamic-table creation, preview,
T&E mode, duplicate detection, audit log) has corresponding test coverage:

- Upload / dynamic-table: `test_api_unit.py`, `test_api_integration.py`,
  `test_csv_loader_arbitrary_shapes.py`, `test_issue_04_multi_file_upload.py`
- Preview: `test_api_unit.py:78-89`, `csv-preview.test.ts`
- T&E mode: `test_te_loader_integration.py` (dedicated 11-test suite)
- Duplicate detection: `test_api_integration.py`, `test_api_coverage.py`
- Audit log: `test_api_coverage.py`, `audit-filters.test.ts`

---

## Net assessment

No FAILs. Both PARTIALs are real but low-severity: a plausible-but-not-obviously-fake
dev password committed in example/docs files, and a few call sites that
return truncated raw exception text instead of curated messages (dev-error
visibility, not a stack-trace or credential leak). Neither blocks anything —
they're listed here as findings for you to decide on, per this audit's
report-only scope.
