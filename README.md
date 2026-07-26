# T&E Database Framework

> A fully parameterised, idempotent **PostgreSQL database framework** for **Test & Evaluation (T&E)** programme management — covering TEMP documents, VCRM traceability, test execution, defect reporting, and multi-environment deployment, with a built-in SQL test suite.

[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13%2B-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Environments](https://img.shields.io/badge/Environments-Dev%20%7C%20Test%20%7C%20Staging%20%7C%20Prod-blue)](#environment-comparison)
[![Test Suites](https://img.shields.io/badge/Tests-5%20suites%20%7C%20142%20assertions-brightgreen)](#test-suite)
[![Evals](https://img.shields.io/badge/Evals-23%20CSV%20scenarios-brightgreen)](evals/)
[![Terraform](https://img.shields.io/badge/Terraform-1.5%2B-7B42BC?logo=terraform&logoColor=white)](https://developer.hashicorp.com/terraform)

---

## What This Is

This project provides a **production-grade SQL framework** to stand up a T&E management database from scratch — on a single PostgreSQL server or across multiple environments. It is designed to support the full T&E lifecycle as practised in Australian acquisition:

- **Program management** — test programs, TEMP versioning, DT&E / AT&E / OT&E phases
- **Requirement traceability** — system requirements linked to test cases via a VCRM (Verification Cross Reference Matrix)
- **Test execution** — events, results, verdicts, and evidence artefacts
- **Defect reporting** — deficiency reports (DRs) linked directly to failed results
- **Multi-environment isolation** — separate databases, schemas, and users for Dev, Test, Staging, and Prod
- **Automated data testing** — 142 assertions across 5 SQL test suites, all written in pure PostgreSQL
- **Data-driven evals** — 23 offline CSV validator scenarios plus PostgreSQL-backed idempotency and full-suite checks

All names (database, schema, users, every table) are controlled by a single `\set` configuration block at the top of each environment file. Rename anything in one place and the entire script updates automatically.

---

## Who Is This For?

| Role | How you use this |
|---|---|
| **T&E Engineers / Analysts** | Understand the data model — VCRM, TEMP versioning, DR lifecycle |
| **Database Administrators** | Deploy and maintain the schema across isolated environments |
| **DevOps / Platform Engineers** | Plug `deploy_all.sh` and `run_tests.sh` into CI/CD pipelines; manage repos with Terraform |
| **Students / Learners** | Study parameterised SQL, idempotent DDL patterns, SQL-native testing, and Terraform IaC |

---

## Repository Structure

The project is organised into three categories: `build/` (everything that ships), `tests/` (correctness coverage), `evals/` (data-driven black-box scenarios). See **`ARCHITECTURE.md`** for the rationale.

```text
PostgreDataMigrationApp/
│
├── build/                             ← everything that ships
│   ├── te_core_schema.sql             ← PostgreSQL master schema (legacy entry point)
│   ├── te_seed_data.sql               ← Seed data
│   │
│   ├── adapters/                      ← Engine-specific deployment adapters
│   │   ├── adapter_postgresql.sh
│   │   ├── adapter_mariadb.sh
│   │   ├── adapter_sqlite.sh
│   │   ├── adapter_influxdb.sh
│   │   ├── adapter_redis.sh
│   │   └── adapter_teradata.sh
│   │
│   ├── csv/                           ← Python validator + per-engine loaders
│   │   ├── validator.py
│   │   ├── validator.sh
│   │   └── loader_<engine>.sh
│   │
│   ├── schema/                        ← Engine-specific DDL and seed data
│   │   ├── postgresql/
│   │   │   └── te_core_schema.sql
│   │   ├── mariadb/
│   │   │   └── te_core_schema.sql
│   │   ├── sqlite/
│   │   │   └── te_core_schema.sql
│   │   ├── influxdb/
│   │   │   └── te_seed_data.lp
│   │   ├── redis/
│   │   │   └── te_seed_data.sh
│   │   └── teradata/
│   │       ├── te_core_schema.sql
│   │       └── te_seed_data.sql
│   │
│   ├── environments/                  ← PostgreSQL per-environment launchers
│   │   ├── env_dev.sql
│   │   ├── env_test.sql
│   │   ├── env_staging.sql
│   │   └── env_prod.sql
│   │
│   ├── terraform-github-repos/        ← GitHub repos as Infrastructure as Code
│   │
│   ├── setup.sh                       ← Interactive multi-database configuration wizard
│   └── deploy_all.sh                  ← Multi-engine deployment router
│
├── tests/                             ← correctness coverage for build/
│   ├── framework/
│   │   └── test_framework.sql         ← Assertion library + results table
│   ├── suites/
│   │   ├── test_01_organisations_personnel.sql
│   │   ├── test_02_programs_phases.sql
│   │   ├── test_03_requirements_vcrm.sql
│   │   ├── test_04_execution_defects.sql
│   │   └── test_05_schema_and_business_rules.sql
│   ├── run_all_tests.sql              ← Master SQL test orchestrator
│   ├── run_tests.sh                   ← Bash wrapper (reads config.local.env)
│   ├── run_python_tests.ps1           ← Windows test runner (CI)
│   ├── test_csv_validator.py          ← unittest for build/csv/validator.py
│   └── test_evals_runner.py           ← unittest for evals/runner.py
│
├── evals/                             ← data-driven black-box scenarios
│   ├── PLAN.md  USAGE.md  FAILURE_MODES.md  README.md  HANDOFF.md
│   ├── runner.py                      ← Scenario discovery, diff engine, JSON reports
│   ├── datasets/tier_p/               ← 23 offline CSV validator scenarios
│   ├── datasets/tier_i/               ← Idempotency scenarios (needs PG)
│   ├── datasets/tier_s/               ← SQL suite integration scenarios
│   ├── expected/tier_*/               ← Expected outcomes
│   └── reports/                       ← Runtime output (gitignored)
│
├── ARCHITECTURE.md                    ← The three-layer model
├── README.md  LICENSE  .gitignore
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| PostgreSQL | 13+ | Extensions used: `uuid-ossp`, `pg_trgm`, `dblink` |
| psql client | Matching server | Must support `\set`, `\if`, `\i` metacommands |
| bash | 4.0+ | For `deploy_all.sh`, `setup.sh`, and `run_tests.sh` |
| Superuser access | — | Required to create databases and roles |
| Terraform | 1.5+ | For GitHub repo management (`terraform-github-repos/`) |
| GitHub PAT | — | Required by Terraform — scope: `repo` |
| MariaDB / MySQL | 10.6+ / 8.0+ | For `DB_ENGINE=mariadb` — requires `mysql` CLI on PATH |
| SQLite | 3.35+ | For `DB_ENGINE=sqlite` — requires `sqlite3` CLI on PATH |
| InfluxDB | 2.x | For `DB_ENGINE=influxdb` — requires `influx` CLI v2 on PATH |
| Redis | 7.x | For `DB_ENGINE=redis` — requires `redis-cli` on PATH |
| Teradata | Vantage 17+ | For `DB_ENGINE=teradata` — requires `bteq` (TTU) on PATH |

> **Windows users:** Use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/) or [Git Bash](https://gitforwindows.org/) to run the shell scripts. The `.sql` files work natively on any platform via `psql`.

---

## Verify Before You Deploy

Before running any deployment — local or Azure — confirm your environment is
ready. This repository has evolved over time, so always verify which files and
tools are actually present rather than assuming.

### 1. Confirm the required tools are installed

```powershell
az version          # Azure CLI (only needed for Azure deployment)
terraform version   # Terraform 1.5+
psql --version      # PostgreSQL client
python --version    # Python 3.10+
```

If any command is not recognised, install that tool before continuing. On
Windows, add `psql` to PATH permanently:

```powershell
setx PATH "$($env:PATH);C:\Program Files\PostgreSQL\17\bin"
```

### 2. Locate the deployment scripts actually present in your copy

```powershell
Get-ChildItem -Recurse -Filter "deploy-all.ps1" | Select-Object FullName
Get-ChildItem -Recurse -Filter "main.tf"        | Select-Object FullName
Get-ChildItem -Recurse -Filter "deploy_all.sh"  | Select-Object FullName
```

Use the paths these return — do not assume a folder name. Azure automation may
live under `azure-automation/` or `infra/` depending on your version.

### 3. Confirm PostgreSQL is reachable (before DB-backed steps)

```powershell
psql -c '\l'
```

If this fails, local deploys and Tiers I + S of the eval suite will skip — the
database must be installed and running first.

### 4. Confirm no secrets are tracked

```powershell
git ls-files | Select-String -Pattern "config.local.env$|\.tfvars$|\.pgpass"
```

This should return nothing. If it lists a file, remove it from tracking before
pushing.

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/amar-python/PostgreDataMigrationApp.git
cd PostgreDataMigrationApp
```

### 2. Run the interactive setup wizard

```bash
cd build
chmod +x setup.sh
./setup.sh
```

The wizard prompts you to select a database engine and configure all settings, then writes `config.local.env`:

```text
  ╔══════════════════════════════════════════════════════════════╗
  ║       PostgreDataMigrationApp — Database Setup Wizard        ║
  ║   Supports: PostgreSQL · MariaDB · SQLite · InfluxDB         ║
  ║             Redis · Teradata                                  ║
  ╚══════════════════════════════════════════════════════════════╝

  1)  postgresql  — PostgreSQL 15  (relational, ACID, recommended)
  2)  mariadb     — MariaDB 10.x   (relational, MySQL-compatible)
  3)  mysql       — MySQL 8.x      (relational, MySQL protocol)
  4)  sqlite      — SQLite 3       (embedded, file-based, no server)
  5)  influxdb    — InfluxDB 2.x   (time-series, metrics & events)
  6)  redis       — Redis 7.x      (in-memory key-value / cache)
  7)  teradata    — Teradata Vantage (enterprise data warehouse)
```

Or skip the wizard and accept all defaults:

```bash
./setup.sh --defaults                 # use all defaults
./setup.sh --engine teradata          # pre-select engine
./setup.sh --engine sqlite --env dev  # pre-select engine + environment
```

### 3. Deploy an environment

```bash
# Dev only (includes realistic seed data)
psql -U postgres -f build/environments/env_dev.sql

# Or deploy all 4 environments at once
chmod +x build/deploy_all.sh
./build/deploy_all.sh
```

### 3. Run the test suite

```bash
chmod +x tests/run_tests.sh
./tests/run_tests.sh dev        # test Dev
./tests/run_tests.sh            # test all 4 environments
```

### 4. Connect and explore

```bash
psql -U te_dev_user -d te_mgmt_dev

-- VCRM coverage for CYB9131
SELECT r.req_identifier, r.title, COUNT(v.tc_id) AS tc_mapped
FROM   te_dev.requirements   r
LEFT   JOIN te_dev.vcrm_entries v ON v.req_id = r.req_id
GROUP  BY r.req_identifier, r.title
ORDER  BY r.req_identifier;
```

---

## CSV Loader

`csv_loader.sh` validates CSV files, derives the target table name from the filename unless `--table` is supplied, writes accepted/skipped row outputs under `csv/logs/`, and routes valid rows to the selected engine-specific loader.

```bash
# Load into the engine from config.local.env
./csv_loader.sh data/customers.csv

# Specify engine/environment
./csv_loader.sh data/orders.csv --engine postgresql --env dev

# Validate only
./csv_loader.sh data/products.csv --engine sqlite --dry-run

# Override the target table name
./csv_loader.sh data/export_2025.csv --engine mariadb --table invoices
```

CSV inputs must have a header row, use comma delimiters, and be UTF-8 encoded with or without a BOM. The shared Python validator skips empty rows and row/header column-count mismatches, warns on duplicate headers, preserves quoted commas/newlines, and writes rejected rows with an `_skip_reason` column.

Supported loader backends are PostgreSQL, MariaDB/MySQL, SQLite, InfluxDB, Redis, and Teradata. PostgreSQL uses `COPY`, MariaDB/MySQL uses `LOAD DATA LOCAL INFILE`, SQLite uses Python `csv` + `sqlite3`, InfluxDB writes line protocol via the `influx` CLI, Redis writes hashes through `redis-cli`, and Teradata uses BTEQ/FastLoad tooling.

### Load any CSV

The loader is schema-agnostic — drop any CSV file in front of it and a matching table is auto-created in the target environment's database. Every CSV-loaded table is tagged with two marker columns: `_csv_row_id BIGSERIAL PRIMARY KEY` and `_loaded_at TIMESTAMPTZ`. All other columns start as `TEXT`; `ALTER TABLE` afterwards if you need stricter types.

Three sample CSVs ship under `build/csv/samples/` (`customers.csv`, `orders.csv`, `inventory.csv`) — deliberately off-domain from the T&E schema to demonstrate that any shape is accepted.

```bash
# Single-command happy-path proof (loads all three samples into dev, lists them)
make csv-demo

# Load any CSV
make csv-load FILE=path/to/anything.csv          # ENV defaults to dev
make csv-load FILE=path/to/anything.csv ENV=test ENGINE=postgresql

# Use loaded data — companion script: build/csv_utilise.sh (PostgreSQL only)
./build/csv_utilise.sh list                       # all CSV-loaded tables in the env
./build/csv_utilise.sh describe customers         # columns + row count
./build/csv_utilise.sh peek orders --limit 5      # first N rows
./build/csv_utilise.sh export inventory dump.csv  # round-trip back to CSV
./build/csv_utilise.sh drop customers --yes       # remove a CSV-loaded table
```

`csv_utilise.sh` only sees tables that carry the marker columns, so it cannot accidentally touch the rigid te_core_schema tables.

---

## How Parameterisation Works

Every environment file contains **only a `\set` configuration block** followed by `\i te_core_schema.sql`. All logic lives in the core schema — the environment file is pure configuration.

```sql
-- environments/env_dev.sql — the ONLY file you edit for Dev
\set env_label          DEV
\set db_name            te_mgmt_dev       ← rename the database here
\set schema_name        te_dev            ← rename the schema here
\set app_user           te_dev_user
\set app_password       Dev@Local#2025!
\set tbl_test_cases     test_cases        ← rename any table here
\set include_seed_data  true              ← toggle seed data on/off

\i te_core_schema.sql                     ← unchanged core logic
```

**psql variable syntax used throughout the core schema:**

| Syntax | Expands to | Used for |
|---|---|---|
| `:'varname'` | `'quoted string'` | String literals, WHERE clauses, DO blocks |
| `:"varname"` | `"quoted identifier"` | Table and schema names in DDL/DML |

---

## Environment Comparison

| Setting | Dev | Test | Staging | Prod |
|---|---|---|---|---|
| Database | `te_mgmt_dev` | `te_mgmt_test` | `te_mgmt_staging` | `te_mgmt_prod` |
| Schema | `te_dev` | `te_test` | `te_staging` | `te_prod` |
| App User | `te_dev_user` | `te_test_user` | `te_stg_user` | `te_prod_user` |
| Connection Limit | 10 | 15 | 20 | 50 |
| Seed Data | ✅ Full | ✅ Full | ❌ Empty | ❌ Empty |

Each environment is fully isolated. All four can run on the same PostgreSQL instance.

To deploy to a remote host:

```bash
PGHOST=my-db-server PGPORT=5432 PGUSER=postgres ./build/deploy_all.sh staging
```

---

## Schema Reference — 12 Tables

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
| `organisations` | agencies, prime contractors, test units |
| `personnel` | T&E workforce with clearance levels and roles |
| `test_programs` | Top-level programmes (e.g. CYB9131, LAND 400 Ph3) |
| `temp_documents` | Versioned TEMP documents (draft → approved → superseded) |
| `test_phases` | DT&E, AT&E, OT&E and other phase types within a program |
| `requirements` | System requirements subject to T&E verification |
| `test_cases` | Individual test cases with steps and expected results |
| `vcrm_entries` | VCRM — maps requirements ↔ test cases (many-to-many) |
| `test_events` | Scheduled/completed test events (lab, field trial, TTX) |
| `test_results` | Execution outcomes — one row per test case run per event |
| `defect_reports` | Deficiency Reports (DRs) raised against failed results |
| `evidence_artifacts` | Logs, screenshots, reports attached to test results |

### Key enumerated values

```sql
-- personnel.te_role
'test_director' | 'test_manager' | 'test_engineer' |
'te_analyst' | 'safety_engineer' | 'config_manager' | 'observer'

-- personnel.clearance  (Australian security clearance levels)
'baseline' | 'NV1' | 'NV2' | 'PV'

-- test_programs.classification  (ISM-aligned)
'UNCLASSIFIED' | 'PROTECTED' | 'SECRET' | 'TOP SECRET'

-- test_phases.phase_type
'DT&E' | 'AT&E' | 'OT&E' | 'IOT&E' | 'LFT&E' | 'FOLLOW_ON'

-- test_results.verdict
'pass' | 'fail' | 'blocked' | 'not_run' | 'inconclusive'

-- defect_reports.severity
'critical' | 'major' | 'minor' | 'observation'
```

---

## Seed Data (Dev & Test Only)

Realistic Australian T&E data is loaded automatically when `include_seed_data` is `true`.

| Table | Records | Highlights |
|---|---|---|
| `organisations` | 5 | CASG, DST Group, Leidos, BAE Systems, JSTF |
| `personnel` | 6 | Roles from test_director to safety_engineer; NV1–PV clearances |
| `test_programs` | 2 | CYB9131 (PROTECTED), LAND 400 Ph3 (SECRET) |
| `temp_documents` | 3 | Approved v1.0 + draft amendment for CYB9131; draft for LAND 400 |
| `test_phases` | 3 | CYB9131 DT&E (completed), OT&E (active), LAND400 AT&E (planned) |
| `requirements` | 8 | 6 × CYB9131 (security, performance, functional, compliance), 2 × LAND400 |
| `test_cases` | 8 | Security, performance, acceptance TCs against CYB9131 OT&E |
| `vcrm_entries` | 8 | 100% VCRM coverage for CYB9131; LAND400 intentionally uncovered |
| `test_events` | 3 | EV01 completed, EV02 in-progress, EV03 planned |
| `test_results` | 7 | 4 pass, 2 fail, 1 inconclusive — realistic mix |
| `defect_reports` | 3 | DR-CYB-0001 (audit gap), 0002 (TLS 1.2), 0003 (session timeout) |

---

## Test Suite

### Run it

```bash
# Against a single environment
./tests/run_tests.sh dev

# Against all environments
./tests/run_tests.sh

# Run Python tests
python -m unittest discover -s tests -p "test*.py" -v

# Run data-driven CSV validator evals
python evals/runner.py --tiers p

# Run all eval tiers; PostgreSQL-backed tiers skip cleanly if PG is unavailable
python evals/runner.py --tiers p,i,s

# Manually via psql
psql -U postgres -d te_mgmt_dev \
  --set schema_name=te_dev \
  --set tbl_organisations=organisations \
  --set tbl_personnel=personnel \
  --set tbl_test_programs=test_programs \
  --set tbl_temp_documents=temp_documents \
  --set tbl_test_phases=test_phases \
  --set tbl_requirements=requirements \
  --set tbl_test_cases=test_cases \
  --set tbl_vcrm_entries=vcrm_entries \
  --set tbl_test_events=test_events \
  --set tbl_test_results=test_results \
  --set tbl_defect_reports=defect_reports \
  --set tbl_evidence_artifacts=evidence_artifacts \
  -f tests/run_all_tests.sql
```

```powershell
# Windows/PowerShell runner for Python tests
powershell -NoProfile -ExecutionPolicy Bypass -File "tests/run_python_tests.ps1"
# Optional: run a custom test path
powershell -NoProfile -ExecutionPolicy Bypass -File "tests/run_python_tests.ps1" -TestPath "tests/test_csv_validator.py"
```

### Windows / Cursor AI notes

- `setup.sh`, `deploy_all.sh`, and `tests/run_tests.sh` are bash scripts.
- On Windows, run shell scripts via WSL2 or Git Bash.
- The Python unit tests and Tier P evals are Windows-native and do not require WSL.
- Tier I and Tier S evals require a reachable PostgreSQL instance and `psql` on PATH; if unavailable, they skip cleanly.
- Required for Python tests and offline evals:
  - Python on PATH (`python --version`)
  - PowerShell available (`pwsh` or `powershell`)
- Recommended Windows command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "tests/run_python_tests.ps1"
python evals\runner.py --tiers p
```

### CI validation (Windows)

A GitHub Actions workflow is included for Windows validation of the Python tests:

- Workflow file: `.github/workflows/python-validator-tests.yml`
- Runner: `windows-latest`
- Python version: `3.11`
- Command executed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "tests/run_python_tests.ps1"
```

### Data-driven evals

The `evals/` package complements the SQL and unit tests with scenario fixtures and expected JSON outputs.

| Tier | What it validates | Database required? |
|---|---|---|
| P | `csv/validator.py` across 23 CSV edge cases, including malformed rows, BOM, CRLF, Unicode, quoted newlines, long fields, missing env vars, and invalid UTF-8 bytes | No |
| I | Dev deployment idempotency by deploying twice and comparing seed row counts | Yes |
| S | Fresh Dev deploy followed by the full SQL suite, expecting all 142 assertions to pass | Yes |

Run examples:

```powershell
python evals\runner.py                  # Tier P only
python evals\runner.py --tiers p,i,s    # all tiers; I/S skip if PostgreSQL is unavailable
python evals\runner.py --only 14_quoted_newline --tiers p
```

Each eval run writes a JSON report under `evals/reports/<run_id>/summary.json`; that folder is intentionally gitignored.

### Coverage — 142 assertions across 5 suites

| Suite | Assertions | What is tested |
|---|---|---|
| 01 — Organisations & Personnel | 17 | Row counts, FK integrity, CHECK/UNIQUE/NOT NULL constraints |
| 02 — Programs, TEMP & Phases | 19 | Date rules, classification markings, status enums |
| 03 — Requirements & VCRM | 21 | 100% VCRM coverage check, per-program gap detection |
| 04 — Execution & Defects | 28 | Verdict counts, DR linkage to fail results, resolved_at logic |
| 05 — Schema & Business Rules | 20 | Table/index existence, trigger firing, cross-table rules |

### Assertion functions

| Function | Purpose |
|---|---|
| `assert_equals(suite, name, expected, actual)` | Exact value match |
| `assert_not_equals(suite, name, expected, actual)` | Values must differ |
| `assert_row_count(suite, name, query, n)` | COUNT of query = N |
| `assert_true(suite, name, sql_expr)` | Expression is TRUE |
| `assert_false(suite, name, sql_expr)` | Expression is FALSE |
| `assert_not_null(suite, name, query)` | Query returns a value |
| `assert_null(suite, name, query)` | Query returns NULL |
| `assert_raises(suite, name, query)` | Query must throw an exception |

### Sample output

```text
============================================================
 T&E TEST SUITE   Schema: te_dev
============================================================

REPORT 1: Suite Summary
─────────────────────────────────────────────────────────────
 suite             total  passed  failed  pass_rate  status
 ──────────────── ──────  ──────  ──────  ─────────  ──────────────
 business_rules       8       8       0   100.0%     ✓ ALL PASS
 defect_reports      12      12       0   100.0%     ✓ ALL PASS
 organisations        8       8       0   100.0%     ✓ ALL PASS
 personnel            9       9       0   100.0%     ✓ ALL PASS
 programs            13      13       0   100.0%     ✓ ALL PASS
 requirements        11      11       0   100.0%     ✓ ALL PASS
 schema              20      20       0   100.0%     ✓ ALL PASS
 temp_documents       6       6       0   100.0%     ✓ ALL PASS
 test_cases           9       9       0   100.0%     ✓ ALL PASS
 test_events          8       8       0   100.0%     ✓ ALL PASS
 test_phases          6       6       0   100.0%     ✓ ALL PASS
 test_results         9       9       0   100.0%     ✓ ALL PASS
 vcrm                10      10       0   100.0%     ✓ ALL PASS

REPORT 4: Overall Result
─────────────────────────────────────────────────────────────
 total  passed  failed  pass_rate  overall
 ─────  ──────  ──────  ─────────  ───────────────────────
    85      85       0   100.0%    ✓ ALL TESTS PASSED
```

---

## Running the Full Test Suite

Every test reports **pass** or **fail**. Nothing is skipped: an unavailable
prerequisite (no PostgreSQL, no `env_<env>.sql`, no `config.local.env`, no
deployed database, no bash) is a **failure**, not a silent skip.

### One-time provisioning

Concrete environment launchers and `config.local.env` are gitignored, so a
fresh clone has none of them. Create them all in one step:

```bash
bash scripts/provision_full_test_env.sh
```

This copies `env_<env>.sql` from the committed `*.example.sql` templates, writes
a local `config.local.env`, and deploys all four environments. It needs a
reachable PostgreSQL and `PGUSER` / `PGHOST` / `PGPORT` set.

### Run with full accounting

```bash
python3 scripts/test_report.py --strict
```

Every run ends with a block accounting for all collected tests:

```text
==================================================================
  FINAL RESULT — every test accounted for
==================================================================
  collected     : 54
  executed      : 54
  PASSED        : 54
  FAILED        : 0
  ERROR         : 0
  SKIPPED       : 0
  NOT RUN       : 0  (deselected by the marker filter)

  SKIPPED (0)
    none — no test was skipped
==================================================================
  RESULT: PASS
==================================================================
```

The **SKIPPED** section prints even when empty, so its absence is never
ambiguous. **NOT RUN** names each test deselected by a marker filter — those are
out of that invocation's scope, not skipped, and must run in another job.
`--strict` exits non-zero if anything was skipped.

```bash
python3 scripts/test_report.py                                  # whole suite
python3 scripts/test_report.py --markers "unit or security"     # scoped
```

### Expected results

| Layer | Command | Expected |
|---|---|---|
| Python tests | `python3 scripts/test_report.py --strict` | 54 / 54, 0 skipped |
| SQL assertions | `bash tests/run_tests.sh dev` | 142 / 142, 100% |
| Evals P, I, S | `python3 evals/runner.py --tiers p,i,s` | 25 / 25, 0 skipped |
| Lint | `bash scripts/lint.sh` | flake8 + bandit clean |
| Health | `python3 scripts/health_check.py` | all checks pass |

Captured output for each of these is in `test-artifacts/` — including a
deliberate negative-control run proving that missing prerequisites fail rather
than skip. See `test-artifacts/00_SUMMARY.md`.

### CI

| Workflow | Runner | Scope |
|---|---|---|
| `quality-gate.yml` — `free-tier` | ubuntu | `unit`, `regression`, `security`, `snapshot` |
| `quality-gate.yml` — `integration-postgres` | ubuntu + PG service | full suite, all four environments |
| `python-validator-tests.yml` | windows | database-free markers |

Both workflows end with `scripts/test_report.py --strict`, so a skipped test
fails the build. GitHub Actions service containers are Linux-only, so the
Windows job cannot host PostgreSQL; it runs the database-free markers and prints
the tests it does not run by name. The database-backed markers run in
`integration-postgres`.

### Related documents

| Document | Contents |
|---|---|
| `FIXES_APPLIED.md` | Every fix made during the audit, with evidence |
| `GAP_ANALYSIS.md` | Open gaps and the decisions they need |
| `VCRM_GAPS.md` | Business-requirement traceability, regenerated per run |
| `TEST_CONDITIONS.md` | Full catalogue of test conditions |
| `test-artifacts/00_SUMMARY.md` | Captured output from the verification run |

---

## Idempotency

The entire framework is safe to re-run against an existing database:

- `CREATE DATABASE` / `CREATE ROLE` — wrapped in `DO $$ IF NOT EXISTS $$` guards
- `CREATE TABLE` — uses `IF NOT EXISTS`
- `CREATE INDEX` — uses `IF NOT EXISTS`
- `CREATE EXTENSION` — uses `IF NOT EXISTS`
- Seed data — uses `ON CONFLICT DO NOTHING`
- Triggers — `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`

---

## Production Guidance

- **Never commit real passwords** — use a secrets manager (Azure Key Vault, HashiCorp Vault, AWS Secrets Manager) and inject `app_password` at deploy time.
- **Staging and Prod have seed data disabled** — load your own anonymised snapshot after deployment.
- **Connection limits** per user are set conservatively by default — tune `conn_limit` to your workload.
- The `evidence_artifacts` table is schema-only — wire it to your document store (SharePoint, S3, Azure Blob) via the `file_path` column.

---

## Terraform — GitHub Repository Management

The `terraform-github-repos/` folder manages this repository (and any future ones) as **Infrastructure as Code**. Instead of manually configuring repositories on GitHub, you define them in code and apply changes with a single command.

### Prerequisites

- [Terraform 1.5+](https://developer.hashicorp.com/terraform/install)
- A GitHub Personal Access Token (PAT) with `repo` scope — [generate one here](https://github.com/settings/tokens)

### Setup

```bash
cd terraform-github-repos
```

Set your token as an environment variable (never hard-code it):

```powershell
# PowerShell (Windows)
$env:TF_VAR_github_token="ghp_yourtoken"
```

```bash
# Mac / Linux / Git Bash
export TF_VAR_github_token="ghp_yourtoken"
```

### Run

```bash
terraform init     # download the GitHub provider (run once)
terraform plan     # preview what will change
terraform apply    # apply changes to GitHub
```

### Add a new repository

**Step 1** — Add an entry to `variables.tf`:

```hcl
"MyNewProject" = {
  description = "Description of my new project"
  visibility  = "public"
  topics      = ["python", "automation", "devops"]
}
```

**Step 2** — Add a resource block in `main.tf`:

```hcl
resource "github_repository" "my_new_project" {
  name        = "MyNewProject"
  description = var.repos["MyNewProject"].description
  visibility  = var.repos["MyNewProject"].visibility
  has_issues  = true
  auto_init   = false
  lifecycle { prevent_destroy = true }
}

resource "github_repository_topics" "my_new_project" {
  repository = github_repository.my_new_project.name
  topics     = var.repos["MyNewProject"].topics
}
```

**Step 3** — Apply:

```bash
terraform plan    # confirm what will be created
terraform apply   # create the repo on GitHub
```

### Key features

- `prevent_destroy = true` — protects repos from accidental `terraform destroy`
- `sensitive = true` on the token — prevents it appearing in plan output or logs
- `terraform.tfvars` is in `.gitignore` — credentials are never committed
- All repo config lives in one place: `variables.tf`

### Useful commands

```bash
terraform output          # print all repository URLs
terraform show            # show current managed state
terraform fmt             # auto-format .tf files
terraform validate        # check configuration for errors
```

---

Contributions are welcome. Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes and add or update tests in `tests/suites/`
4. Verify all 142 assertions still pass: `./tests/run_tests.sh dev`
5. Open a Pull Request with a clear description of what changed and why

**Guidelines:**

- Keep the framework idempotent — every change must be safe to re-run
- Add at least one test assertion for any new table column or constraint
- Follow the existing naming convention for tables (`tbl_*`), indexes (`idx_*`), and triggers (`trg_*`)
- Do not commit passwords, real classified data, or environment-specific connection strings

---

## License

MIT — see [LICENSE](LICENSE) for full text.

---

## Acknowledgements

Here are the prompts, distilled from every action I actually performed today. Each one is self-contained and would run end-to-end without follow-up questions.

---

### Prompt 1 — Audit & Fix Stale Documentation

```text
Audit all markdown docs and requirements.txt against the current codebase.
For each file, check that referenced functions, imports, file paths, test
counts, and CLI commands still match the code. Fix anything stale in-place.
Push to GitHub with a summary of what changed and why.

Files to check: README.md, FIXES_APPLIED.md, VALIDATION_REPORT.md,
NEW_USER_NAVIGATION_GUIDE.md, requirements.txt
```

---

### Prompt 2 — Generate Edge Case Datasets + Stress Tests

```text
Generate synthetic edge case CSV datasets in sample_data/edge_cases/ and
write matching pytest tests in tests/test_edge_cases.py. Cover these cases:

- UTF-8 BOM in headers
- Tab-delimited (.tsv)
- Duplicate primary keys
- Header-only (empty) CSV
- Unicode (CJK, accented, Polish characters)
- Nulls in required columns (empty string, "NULL", "N/A")
- Special characters (embedded commas, quotes, apostrophes)
- Ragged rows (inconsistent column count)
- Wrong/missing column headers
- Over-length string values exceeding max_length
- Large file (10,000 rows) with a performance assertion under 5 seconds
- Missing/nonexistent file path

Each test should use the project's existing JobConfig and pre_import stage.
Run the full test suite to confirm everything passes, then push to GitHub.
```

---

### Prompt 3 — Run Tests + Generate Detailed Report for Lead

```text
Run the full pytest suite and create TEST_REPORT.md at the project root.
The report must include:

- Summary line: total / passed / failed / skipped
- A table per test file with columns: #, Test name, Marker (unit/integration),
  Status, What it verifies
- A "Note for Lead" section explaining that integration tests need a live
  PostgreSQL database configured via .env, and that running `pytest -m unit`
  deselects them by marker filter (not skipped due to failure)
- A test data table listing every dataset file and its purpose

Push TEST_REPORT.md to GitHub.
```

---

### Prompt 4 — Repo Hygiene (one-shot cleanup)

```text
Clean up the GitHub repo (amar-python/TestUploadtoGIT) in one pass:

1. If files exist at both root and a nested path (e.g. OneDrive/Desktop/...),
   keep the latest version at root and git rm the nested duplicate entirely.
2. Add .abacusai/, .claude/, and any other tool/session folders to .gitignore
   and untrack them with git rm --cached.
3. Prune the reports/ folder to keep only the 5 most recent timestamped run
   directories and their matching logs. Delete the rest.
4. Add an auto-pruning rule to src/reporting.py that deletes old runs
   beyond MAX_REPORT_RUNS (default 5) after each write_summary() call.
   Make the limit configurable via env var.

Commit each logical change separately and push to master.
```

---

### Prompt 5 — Full Session (combines all of the above)

```text
I have a CSV-to-PostgreSQL migration framework at:
C:\Users\User\OneDrive\Desktop\Migration using ai
GitHub repo: amar-python/TestUploadtoGIT

Do the following in order:

1. AUDIT DOCS — Check all .md files and requirements.txt against the code.
   Fix anything stale.

2. EDGE CASE TESTS — Generate 11+ synthetic CSV datasets covering:
   - BOM (Byte Order Mark — the hidden \xEF\xBB\xBF prefix Excel adds to
     UTF-8 files that corrupts the first column header)
   - Tab-delimited (.tsv)
   - Unicode (CJK, accented, Polish characters)
   - Nulls in required columns (empty string, "NULL", "N/A")
   - Special characters (embedded commas, quotes, apostrophes)
   - Ragged rows (inconsistent column count)
   - Wrong/missing column headers
   - Over-length string values exceeding max_length
   - Large file (10,000 rows) with a performance assertion under 5 seconds
   - Duplicate primary keys
   - Empty file (header only)
   Write matching pytest tests. Run the suite to confirm all pass.

3. TEST REPORT — Create TEST_REPORT.md listing every test with status,
   marker, and description. Include a note for the lead about integration
   tests requiring PostgreSQL.

4. REPO HYGIENE — Flatten any nested paths to root level. Add tool folders
   to .gitignore and untrack them. Prune reports/ to 5 most recent runs
   and add auto-pruning logic to src/reporting.py (MAX_REPORT_RUNS=5).

5. PUSH — Commit each logical change separately and push to master.
   Confirm the final repo structure.
```

---

The full session prompt (#5) would reproduce today's entire day of work in a single request. The individual prompts (#1-4)
