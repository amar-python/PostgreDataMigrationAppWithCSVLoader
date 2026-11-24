# Quick Start — PostgreDataMigrationAppWithCSVLoader

A 10-minute walkthrough to get the full stack running locally: PostgreSQL
database, FastAPI backend, and React frontend.

For architecture and rationale see `docs/ARCHITECTURE.md`, `docs/VCRM.md`, and
`docs/API_INTEGRATION.md`.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| PostgreSQL | 16 or later | CI tests PostgreSQL 16. The walkthrough below uses PostgreSQL 18 on port 5433 |
| Python | 3.10+ | Must be on PATH |
| Node.js | 22.12+ | Required for the React frontend (TanStack Start needs >=22.12) |
| Git Bash | Any | Required for bash scripts on Windows |
| psql client | Matching server | Must be on PATH; the Windows installer does not add it. Add `C:\Program Files\PostgreSQL\<ver>\bin`. `build/deploy_all.sh` checks and says what to do |

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
> - `API_ALLOW_ANONYMOUS=` — leave empty: sign in through the frontend (below). Setting it to `1` lets the API
>   answer without sign-in, for local experiments only; it works only with `API_ENV=dev` (#298)

To make `PGPORT=5433` permanent across all PowerShell sessions:

```powershell
Add-Content $PROFILE "`n`$env:PGPORT = `"5433`""
```

### Save the PostgreSQL login once, so nothing asks for it every time

`$env:PGPASSWORD` lives only in the window where you set it, so every new window starts
without it (and without `PGPORT`). Save the login once instead:

```powershell
python scripts\pg_login.py save
```

It first checks that PostgreSQL is accepting connections (if it is not, it says so and
asks for no password), then asks for the owner's password with the input hidden,
**tests it against PostgreSQL**, and writes it only if PostgreSQL accepts it, so a typo
is never saved. The
login (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`) goes to
`%USERPROFILE%\.te-migration\pg-dev.env`, next to the runtime role's `app-db-dev.env`.
Windows' default permissions on your profile folder keep other ordinary accounts out of
it (the owner-only `0600` mode is applied on Linux and macOS; Windows does not use it).
It is plain text, like that file: fine for a development database that only this
computer can reach, not for anything else. It never prints the password. Use `--env test` for another environment, and `--host`,
`--port` and `--user` if yours differ from `localhost`, `5433` and `postgres`.

After that:

- **`.\scripts\start-api.ps1`** uses the saved login. It takes each value from, in this
  order: the window's own `PG*` variables, the saved file, the defaults, then a prompt.
  It checks that PostgreSQL is reachable **before** it asks for a password, so with the
  server stopped or on another port it says so at once and asks for nothing. Then it tests
  the login before it starts, so a wrong password costs one clear message and a chance to
  type it again (three tries), not a failed start. If you typed a password, it offers to
  save it.
- **The other scripts** (`create_app_role.py`, `reset_password.py`,
  `create_tenant_admin.py`, ...) read the `PG*` variables, so load the saved login into
  the window first. Note the dot and the space; without them the values vanish when the
  script ends:

  ```powershell
  . .\scripts\dev-env.ps1          # dev
  . .\scripts\dev-env.ps1 test     # another environment
  ```

- **Check or find it:** `python scripts\pg_login.py check` tests whatever login the
  window has (server first, then the login; exit 0 works, 2 refused, 3 not reachable),
  `check --server-only` asks only whether PostgreSQL is accepting connections and needs no
  password, and `python scripts\pg_login.py where` shows the file and what it holds (the
  password is not shown). To forget the login, delete that file.

If the password changes later (a reset, a reinstall), `start-api.ps1` says the saved one
was refused and asks again; save the new one with `python scripts\pg_login.py save`.

**"... is not digitally signed" when running a `.ps1`.** Windows blocks unsigned scripts
in a file downloaded or synced from elsewhere. For this window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

or unblock the files once: `Unblock-File .\scripts\*.ps1`.

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

> **Note:** If `[✗] Deployment FAILED` appears with `syntax error at or near "ï»¿"`,
> your `build/environments/env_<env>.sql` was copied from an older template that
> started with a UTF-8 byte-order mark. Recreate it from the template
> (`cp build/environments/env_dev.example.sql build/environments/env_dev.sql`),
> or set `PGCLIENTENCODING=UTF8` (PowerShell: `$env:PGCLIENTENCODING="UTF8"`).

---

## 5. Start the API (Terminal 1)

```powershell
# From the repo root
.\scripts\start-api.ps1
```

Or manually:

```powershell
$env:CORS_ORIGINS = "http://localhost:8080,http://localhost:5173,http://localhost:3000"
uvicorn api.main:app --reload --reload-dir api --port 8000
```

Verify it's running: open `http://localhost:8000/api/health` — should return
`{"status": "ok"}`. Interactive docs at `http://localhost:8000/docs`.

> **Expected startup warnings (safe to ignore):**
> - `ANONYMOUS ACCESS IS ON` — only if you set `API_ALLOW_ANONYMOUS=1`; unset it to require sign-in

### Create your sign-in (first run only)

The frontend requires signing in (#96). Create a tenant and its admin once:

```powershell
cd "C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader"
python scripts\create_tenant_admin.py --tenant dev --name "Dev tenant" --username admin
```

It prompts for a password of at least 12 characters, or reads it from
`TE_ADMIN_PASSWORD`. Sign in with tenant `dev`, username `admin` and that
password.

**If the tenant already exists** (you, or an earlier setup, ran this before), it does
not fail. It says what exists and asks whether to use it:

- `admin` is already a member: `Use the existing tenant 'dev' as it is?` Answer `y`
  and nothing is created and the password is not changed. If you have forgotten that
  password, use `scripts\reset_password.py` (below).
- The tenant exists but `admin` does not: `Use the existing tenant 'dev' and add 'admin'
  as a tenant admin?` Answer `y` and it asks for the new account's password.

Anything other than `y` changes nothing. With no terminal, or to skip the question, add
`--use-existing`. A username that already belongs to an account outside that tenant is
never reused; choose another `--username`.

> **When you re-run the database deploy** (`build/deploy_all.sh`) against a database that
> already exists, it likewise asks `Use it and apply the T&E schema to it? [y/N]`.
> Add `--yes` to skip the question.

### Set up the runtime database role (once per environment, M3d)

The API answers requests as a separate database role, `te_app_<env>` — so
`te_app_dev` for your dev environment. It can only read and add to the audit log
and the stored uploads, never change or delete them (#107). The owner (`PGUSER`,
usually `postgres`) is used only at startup. Stop the API first, then run this
once from the same folder:

```powershell
cd "C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader"
python scripts\create_app_role.py --env dev
```

It connects as the owner with the `PG*` values from step 3, so run it in a
window where they're set (`PGPORT` 5433 and `PGPASSWORD` for PostgreSQL 18): once you
have saved the login, `. .\scripts\dev-env.ps1` sets them.
It creates the role with a random password and writes the role's settings to
`%USERPROFILE%\.te-migration\app-db-dev.env`. It never prints the password.
`start-api.ps1` loads that file, choosing it from `API_ENV` (default `dev`).
Until you run it, the API prints `APP_DB_USER not set` and runs as the owner.
Running it again sets a new password.

`--env` is required (#173). Both the role name and the credential file come from
it, so setting up a second environment on the same PostgreSQL server leaves the
first one working. Standing up Test here, for example, is
`--env test` with that environment's `PG*` values set, and it creates
`te_app_test` with its own `app-db-test.env`. Before #173 there was one shared
`te_app` role and one `app-db.env`: setting up Test rotated the password Dev was
using, and Dev's connections failed on their next reconnect with
`password authentication failed`. This is the normal shape for a dev PC — the
PostgreSQL 17 instance on 5432 and the PostgreSQL 18 one on 5433 each hold
several environments.

**Upgrading from before #173.** If you already have
`%USERPROFILE%\.te-migration\app-db.env`, run the command above once. It writes
the new per-environment file and renames the old one to
`app-db.env.superseded-dev`, so `start-api.ps1` stops reading it; nothing is
deleted, so `mv` puts it back. Once every environment has been re-run with
`--env`, the old cluster-wide `te_app` role is unused and the script prints the
`DROP ROLE` to remove it.

### Change or reset a password (#117)

- **Your own password:** sign in, then click the key icon in the header.
- **Someone else in your tenant:** a tenant admin calls
  `POST /api/auth/users/<username>/password` (see `docs/ROLES.md`).
- **No admin can sign in** (forgotten password or locked out):

```powershell
cd "C:\Users\User\OneDrive\Desktop\Migration using ai\PostgreDataMigrationAppWithCSVLoader"
python scripts\reset_password.py --username admin
```

It prompts for the new password (at least 12 characters), or reads it from
`TE_NEW_PASSWORD`. It also clears any lockout and signs the user out everywhere.

### Idle sign-out and purging old sessions (#296)

A session that has not been used for `SESSION_IDLE_MINUTES` (default 30) is refused, and its owner signs in again. Set it to `0` to turn that off. Rows of sessions that ended more than `SESSION_PURGE_GRACE_DAYS` (default 1) ago are deleted once each time the API starts. For a deployment that stays up for weeks, run this on a schedule (cron, or a Container Apps job) with the API's `PG*` environment set:

```powershell
python scripts\purge_sessions.py
```

It prints how many rows it removed. It never touches a live session, a user or a membership.

---

## 6. Start the frontend (Terminal 2)

```powershell
cd csv-table-hub-main

# First run only — create the env file
@"
VITE_API_BASE=http://localhost:8000
"@ | Set-Content .env.local

# Install dependencies (first run only)
npm install

# Start the dev server
npm run dev
```

The frontend starts on **`http://localhost:8080`**. Open that URL in your
browser. You should see the sign-in page; after signing in, the upload page.

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
python -m pytest tests\system\test_api_integration.py -v

# T&E mode integration tests
python -m pytest tests\system\test_te_loader_integration.py -v

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
| Frontend shows "This page didn't load" | API not running | Start the API first (Terminal 1) |
| `ERR_CONNECTION_REFUSED` in browser console | API stopped | Restart `uvicorn` |
| "Can't reach the API at http://localhost:8000. Is it running?" | API not running | Start it with `.\scripts\start-api.ps1` |
| `start-api.ps1` says "Port 8000 is already in use by PID …" | An older API is still running, maybe in a window you've forgotten (#118) | Close that window, or run the `taskkill` line it prints, then start again |
| `npm run dev` fails with "Missing script" | Wrong directory | Must run from `csv-table-hub-main\`, not repo root |
| Deployment shows `[✗] failed for dev` with `syntax error at or near "ï»¿"` | `env_dev.sql` has a UTF-8 BOM (old template) | Recreate it from `env_dev.example.sql`, or set `PGCLIENTENCODING=UTF8` |
| `psql was not found on PATH`, and the message says it is bash "inside WSL" (older versions hint at `apt install` even on Windows) | `bash` typed in PowerShell is the WSL launcher, which runs the script in Linux and cannot see the Windows `psql.exe` | Run it with Git's bash: `& "C:\Program Files\Git\bin\bash.exe" build/deploy_all.sh dev`, or from a Git Bash window |
| The API stops at startup with `Could not connect to PostgreSQL at … as postgres to run the database migrations` | The owner login (`PGUSER` / `PGPASSWORD`) was refused. The API's runtime role connected, but the migrations use the owner. A `PGPASSWORD` left in the window (or in your Windows user environment variables) wins over the saved login | `start-api.ps1` now tests the login first and asks again. To stop being asked, save a working one: `python scripts\pg_login.py save`. To see what a window holds without printing the password: `python scripts\pg_login.py check` |
| `start-api.ps1` says `PostgreSQL refused the login for postgres@localhost:5433` | The password it picked up (named in the next line: this window, the saved login, or what you typed) is wrong for that server | Type it again at the prompt; to replace the saved one, `python scripts\pg_login.py save` |
| `start-api.ps1` says `Could not reach PostgreSQL at localhost:5433` | The server is not running, or it is on another port (PostgreSQL 17 is 5432, 18 is 5433) | Start the service, or set `$env:PGPORT`. It checks this before asking for any password, because a different password cannot help |
| `... is not digitally signed`, or `running scripts is disabled on this system` | Windows blocks unsigned `.ps1` files | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window, or `Unblock-File .\scripts\*.ps1` |

---

## Directory structure

```text
PostgreDataMigrationAppWithCSVLoader/
├── api/                          ← FastAPI backend
│   ├── main.py                   ← app entrypoint, CORS, lifespan
│   ├── config.py                 ← env-var settings + TE_TABLES list
│   ├── db.py                     ← psycopg2 pool + Conn context manager
│   ├── auth.py                   ← sign-in sessions, tenant scope, role checks
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
│   ├── .env.local                ← VITE_API_BASE (not committed)
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
├── docs/API_INTEGRATION.md            ← API design notes: auth, known gaps, migrations
└── docs/VCRM.md                       ← business requirement traceability
```

---

## Next steps

- `docs/STARTER_GUIDE.md` — orientation, key concepts, and a guided first
  walkthrough (dynamic mode vs T&E mode, running the test suite end to end)
- `docs/ENV_VARIABLES.md` — full list of every environment variable
- `docs/API_INTEGRATION.md` — API design notes: auth model, known gaps, migrations
  (route list: `http://localhost:8000/docs` with the API running)
- `docs/VCRM.md` — business requirement traceability (142 SQL assertions)
- `docs/ARCHITECTURE.md` — three-layer architecture rationale
- `evals/USAGE.md` — eval runner flags and CI integration
