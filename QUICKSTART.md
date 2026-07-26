# Quick Start — PostgreDataMigrationApp

A 10-minute walkthrough to deploy the Dev environment, run the eval suite, and
view the auto-generated VCRM gap report.

For the full architecture and rationale see `ARCHITECTURE.md`, `VCRM.md`, and
`evals/PLAN.md`.

## Prerequisites

- PostgreSQL 14 or later running locally (default port 5432)
- Python 3.10 or later on PATH
- `psql` client on PATH (Windows: under `C:\Program Files\PostgreSQL\<ver>\bin`)
- Git Bash, WSL, or PowerShell (examples below use PowerShell)

## Install

- Clone or extract the project to a working folder
- Open PowerShell and `cd` into the `PostgreDataMigrationApp` folder
- Confirm `psql --version` returns a 14+ build
- Confirm `python --version` returns 3.10+

## Configure connection

- Set the standard libpq environment variables once per session
- Use a role that can create databases, schemas, and roles
- For first-time setup, the superuser `postgres` works fine

```powershell
$env:PGHOST     = 'localhost'
$env:PGPORT     = '5432'
$env:PGUSER     = 'postgres'
$env:PGPASSWORD = '<your password>'
```
>
> **Security note:** Never commit credentials. `PGPASSWORD` lives only in the
> current session — close the terminal to clear it. If you instead keep settings
> in a `config.local.env` file, ensure it is gitignored and, on Mac/Linux,
>
> restrict its permissions so only you can read it:
>
> ```bash
> chmod 600 config.local.env
> ```
>
> For unattended use, a [`~/.pgpass`](https://www.postgresql.org/docs/current/libpq-pgpass.html)
> file (chmod `600`) avoids putting the password in environment variables at all.

## Deploy the Dev environment

From the project root:

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp"
bash build\deploy_all.sh dev
```

On success you should see `ALL ENVIRONMENTS DEPLOYED` and the new database
`te_mgmt_dev` with schema `te_dev` containing the 12 core tables. (Running the
SQL suite later adds a 13th, `test_run_results`, used to record assertions.)

## Run the eval suite

The single entry point is `evals\runner.py`. Three tiers run by default:

- **Tier P** — 23 Python validator scenarios (no DB required, ~5 seconds)
- **Tier I** — 1 idempotency scenario (PG required)
- **Tier S** — 1 SQL suite integration scenario (PG required, ~30 seconds)

```powershell
python evals\runner.py --tiers p,i,s
```

Expected outcome with PG available: `total: 25, passed: 25, failed: 0`.
Without PG, Tier P passes and Tiers I + S skip cleanly with a diagnostic.

## CSV pitfalls — what the framework handles and what to watch for

The framework's Tier P eval suite covers 22 documented CSV failure modes.
Here are the ones most likely to bite you when loading real data, with
how the framework responds and what to fix at the source.

### Encoding and byte-level issues

| Issue | What happens | Eval | Fix at source |
|---|---|---|---|
| UTF-8 BOM at start of file (`﻿`) | Stripped automatically — file opened with `utf-8-sig` | scenario 09 | Nothing — handled |
| CRLF line endings (Windows) | Native — Python's `csv` module handles it | scenario 11 | Nothing — handled |
| Latin-1 bytes (`\xe9` etc.) inside a UTF-8 file | Clean exit 1, stderr reports decode error, no traceback | scenario 23 | Re-export the source as UTF-8 |
| Emoji / RTL / CJK in values (Alice 👋, محمد, 田中花子) | Preserved end-to-end through ingest + PG | scenarios 10, 18, 21 | Nothing — handled |

### Header issues

| Issue | What happens | Eval | Fix at source |
|---|---|---|---|
| Leading/trailing spaces in headers (` id , name `) | Normalised by `cell.strip()` to `id`, `name` | scenario 17 | Nothing — handled |
| Duplicate column names (`id,id,name`) | Exit 0 but stdout shows `Duplicate column names` warning | scenario 06 | Rename the duplicate column in source |
| Header-only file (no data rows) | Exit 1, stderr `No valid rows found` | scenario 04 | Add data rows or remove the empty file |

### Row-shape issues

| Issue | What happens | Eval | Fix at source |
|---|---|---|---|
| Fewer fields than header | Row skipped with `_skip_reason: column mismatch` | scenario 07 | Quote fields that may contain commas |
| More fields than header | Same — skipped as column mismatch | scenario 07b | Same fix |
| Completely empty row (`,,`) | Skipped as `empty row` | scenario 08 | Trim source file or accept silently |
| Whitespace-only row (spaces around a comma) | Skipped as `empty row` (cells stripped first) | scenario 16 | Same |

### Embedded special characters

| Issue | What happens | Eval | Notes |
|---|---|---|---|
| Comma inside a quoted field: `1,"Smith, John"` | Parsed as one field `Smith, John` | scenario 13 | Just quote the field |
| Newline inside a quoted field: `1,"line1\nline2"` | Parsed as one row, note has embedded newline | scenario 14 | Quote it |
| Escaped quote: `1,"she said ""hi"""` | Parsed as `she said "hi"` | scenario 15 | Double the inner quotes |
| Very long single field (≥ 50 KB) | Accepted as one row | scenario 22 | Beyond ~128 KB, raise Python's `csv.field_size_limit` |

### Duplicate primary keys (the one that bit us)

This is **not** caught by Tier P — it surfaces at load time. If `input.csv`
contains rows with byte-identical primary keys, the staging table accepts
them, then the swap to the target table fails because the PK constraint
trips.

**Symptom:**

```text
ERROR: duplicate key value violates unique constraint "<table>_pkey"
DETAIL:  Key (col_1)=(...) already exists.
```

**Fix:** the `load_input_data.sql` script wraps the inserts with
`SELECT DISTINCT ON (col_1) ... ORDER BY col_1` to deduplicate within
the load. If you're loading via a different path, mirror that pattern or
clean the CSV first:

```powershell
# Quick dedup in PowerShell (keeps first occurrence of each col_1)
Import-Csv input.csv | Group-Object col_1 | ForEach-Object { $_.Group[0] } | Export-Csv input_dedup.csv -NoTypeInformation
```

### Missing inputs and env vars

| Issue | What happens | Eval |
|---|---|---|
| `CSV_FILE` env var not set | Exit 1, stderr `Missing required environment variables` | scenario 19 |
| `CSV_FILE` points at a non-existent path | Exit 1, stderr `CSV file not found` | scenario 20 |
| Zero-byte file | Exit 1, stderr `CSV file is empty` | scenario 02 |

### When in doubt — run Tier P on your own CSV

The validator runs standalone, no DB needed:

```powershell
$env:CSV_FILE   = "path\to\your.csv"
$env:VALID_CSV  = "out\valid.csv"
$env:SKIP_FILE  = "out\skipped.csv"
$env:TABLE_NAME = "your_table"
python build\csv\validator.py
```

It produces `out\valid.csv` (rows that passed) and `out\skipped.csv`
(rows that didn't, with a `_skip_reason` column explaining why).

## View the auto-generated gap report

Every run writes two files under `evals\reports\<run_id>\`:

- `summary.json` — machine-readable scenario outcomes
- `VCRM_GAPS_<run_id>.md` — per-run mapping of the 22 business requirements
  to this run's evidence, with REGRESSION / VERIFIED / PARTIAL / SKIPPED /
  UNVERIFIED / DEFERRED status per BR

Open the latest report in your editor:

```powershell
$latest = Get-ChildItem evals\reports -Directory |
          Sort-Object LastWriteTime -Descending |
          Select-Object -First 1
code "evals\reports\$($latest.Name)\VCRM_GAPS_$($latest.Name).md"
```

## Regenerate a gap report after the fact

If you want to rebuild the gap report for an earlier run without rerunning
the suite:

```powershell
python evals\gap_report.py evals\reports\20260605T102805Z-a83461\
```

Replace the timestamp with any folder name under `evals\reports\`.

## Expected results by tier

| Tier | Scenarios | Pass criteria | Typical wall-clock |
| --- | --- | --- | --- |
| P | 23 | All exit-code + stderr diffs match expected | ~5 s |
| I | 1 | Two deploys back-to-back, identical row counts | ~10 s |
| S | 1 | 142/142 assertions, "ALL TESTS PASSED" in stdout | ~30 s |
| X | deferred | Cross-engine schema equivalence | n/a |
| E | deferred | Cross-environment structural parity | n/a |

## Run ID format

Each run gets a timestamped folder under `evals\reports\`. The pattern is
`<UTC-timestamp>-<6-char-hash>`, for example `20260605T102805Z-a83461`.

| Segment | Meaning | Example |
| --- | --- | --- |
| `20260605` | UTC date `YYYYMMDD` | June 5, 2026 |
| `T102805Z` | UTC time `HHMMSS` + `Z` | 10:28:05 UTC |
| `-a83461` | 6-char random suffix | disambiguates concurrent runs |

## Troubleshooting

- **`psql: command not found`** — add the PG `bin` folder to PATH or use the
  full path `C:\Program Files\PostgreSQL\17\bin\psql.exe`
- **`FATAL: password authentication failed`** — recheck `$env:PGPASSWORD`
  matches the role you set during PG install
- **Tier I + S show SKIP** — PG is not reachable; verify `psql -c '\l'` works
  before rerunning
- **Tier S row-count drift** — check `actual.row_counts_first` vs
  `actual.row_counts_second` in `summary.json` to pinpoint the table whose
  
### Checking PostgreSQL is running and reachable

If connections fail, confirm the service is up and listening on port 5432:

```powershell
# Windows
Get-Service postgresql*
Test-NetConnection -ComputerName localhost -Port 5432
```

```bash
# Linux (systemd)
sudo systemctl status postgresql
ss -ltnp | grep 5432

# macOS
brew services list
lsof -iTCP:5432 -sTCP:LISTEN
```

## Next steps

- Read `evals\USAGE.md` for runner flags and CI integration
- Read `VCRM_GAPS.md` for the four open gaps and remediation effort
- Read `TEST_CONDITIONS.md` for the full catalogue of test conditions
- Read `evals\HANDOFF.md` for what is def
