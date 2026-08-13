# SETUP RUNBOOK — PostgreDataMigrationApp

Every command block below is labelled with **where to run it**. On Windows there are
two different terminals, and the repo's `.sh` scripts only work in one of them:

| Label | Prompt looks like | Use for |
|---|---|---|
| **Git Bash** | `user@machine MINGW64 ~` | all `.sh` scripts, `make`, day-to-day operations |
| **PowerShell** | `PS C:\Users\...>` | `preflight.ps1`, `scripts\test.ps1`, git on Windows |

On Linux / macOS / WSL2 every block runs in your normal shell.
Azure Cloud Shell is **not** used by this runbook — it cannot reach a database on your machine.

---

## Phase 0 — Prerequisites (one-time per machine)

Install:

- **Git** (on Windows: [Git for Windows](https://gitforwindows.org/), which includes Git Bash)
- **Python 3.10+**
- **PostgreSQL 13+** — server running, `psql` client on PATH

**▶ RUN IN: Git Bash** — verify:

```bash
git --version && python3 --version && psql --version && bash --version | head -1
```

## Phase 1 — Get the code and Python dependencies

**▶ RUN IN: Git Bash**

```bash
git clone https://github.com/amar-python/PostgreDataMigrationApp.git
cd PostgreDataMigrationApp
pip install -r requirements-dev.txt
```

## Phase 2 — Preflight check

Catches missing tools and configuration before anything half-deploys.

**▶ RUN IN: Git Bash** (repo root):

```bash
bash preflight.sh
```

Windows-native alternative — **▶ RUN IN: PowerShell**: `.\preflight.ps1`

## Phase 3 — Configure the database connection

**▶ RUN IN: Git Bash** (repo root):

```bash
cd build
cp config.env.example config.env
./setup.sh          # interactive wizard: engine, host, port, credentials per environment
cd ..
```

This writes `build/config.local.env` — the file every loader and test script reads.
It is gitignored; never commit it.

## Phase 4 — Deploy the schema

PostgreSQL must be running and reachable with the credentials from Phase 3.

**▶ RUN IN: Git Bash** (repo root):

```bash
export PGPASSWORD='<your postgres superuser password>'

# Single environment (dev) — idempotent, safe to re-run:
psql -U postgres -f build/environments/env_dev.sql

# Or all four environments (dev / test / staging / prod):
bash build/deploy_all.sh
```

## Phase 5 — Verify the deployment

**▶ RUN IN: Git Bash** (repo root):

```bash
make test-free                          # offline unit / regression / security tests
make lint                               # flake8 + bandit
make health                             # structural check — every expected file present
bash tests/run_tests.sh dev             # SQL assertion suite against the dev DB
python3 evals/runner.py --tiers p,i,s   # evals: offline + idempotency + SQL tiers
```

All green means the environment is correctly stood up.

## Phase 6 — Load and use CSV data (day-to-day)

**▶ RUN IN: Git Bash** (repo root):

```bash
make csv-demo                                             # one-shot proof with bundled samples
bash build/csv_loader.sh path/to/anything.csv --env dev   # load any CSV
bash build/csv_utilise.sh list --env dev                  # list CSV-loaded tables
bash build/csv_utilise.sh peek <table> --limit 5          # inspect rows
bash build/csv_utilise.sh export <table> out.csv          # round-trip back to CSV
bash build/csv_utilise.sh drop <table> --yes              # remove a CSV-loaded table
```

---

## Troubleshooting order

When a DB-dependent step fails, check in this order — it resolves most setup issues:

1. Is PostgreSQL running? (`pg_isready` or `psql -c "SELECT 1"`)
2. Is `PGPASSWORD` set **in this terminal**? (environment variables do not survive new windows)
3. Does `build/config.local.env` exist? (Phase 3 creates it; a fresh clone does not have it)
4. Are you in the right terminal? `.sh` scripts require Git Bash / WSL2 — they fail in
   PowerShell and cmd with syntax errors.
