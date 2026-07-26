# USAGE — evals package

End-to-end instructions for running, interpreting, and extending the
`PostgreDataMigrationApp/evals/` suite. If you only need the 30-second
quick start, see the root `../README.md`. For the architectural rationale, see
`PLAN.md`. For the catalogue of what's covered, see `FAILURE_MODES.md`.

---

## 1. One-time setup

### Prerequisites

| Tool | Required for | How to check |
|------|--------------|--------------|
| Python 3.10+ | All tiers | `python --version` (or `python3 --version`) |
| psql client | Tiers I + S only | `psql --version` |
| PostgreSQL server | Tiers I + S only | `psql -c "SELECT 1"` returns `1` |

There is nothing to `pip install`. The runner uses only the Python standard library.

### One-time PG environment (only if you want Tiers I + S)

The runner reads standard libpq env vars. Set them once in PowerShell:

```powershell
$env:PGHOST     = 'localhost'
$env:PGPORT     = '5432'
$env:PGUSER     = 'postgres'
$env:PGPASSWORD = '<your password>'
```

To make these persistent, add them to your PowerShell profile (`notepad $PROFILE`).
For Mac/Linux, equivalent `export PGHOST=...` lines in `~/.bashrc` or `~/.zshrc`.

---

## 2. Running the suite

### Offline tier only (Tier P — no PG)

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp"
python evals\runner.py
```

Expected: 23 PASS lines + summary `total: 23, passed: 23, failed: 0, skipped: 0`. Takes ~5 seconds.

### All tiers (Tier P + I + S — needs PG)

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp"
python evals\runner.py --tiers p,i,s
```

Expected with PostgreSQL available: 25 scenarios total, with 23 Tier P passes plus Tier I and Tier S passes. Takes ~2–3 minutes the first time (the SQL deploy is the slow step). Without PostgreSQL, Tier I and Tier S skip cleanly.

### Targeted runs

```powershell
# Just one scenario
python evals\runner.py --only 05_mixed_valid_skipped

# Verbose — show actual vs expected on failures
python evals\runner.py --verbose

# Combine
python evals\runner.py --tiers p,i --only 01_happy_path --verbose
```

---

## 3. Reading the results

### Terminal

Each scenario prints one line:

```text
PASS tier_p/01_happy_path
FAIL tier_p/05_mixed_valid_skipped
     exit_code: expected 0, got 1
     stderr missing substring: 'Valid rows'
SKIP tier_i/01_deploy_dev_twice  PostgreSQL not reachable via psql...
```

Then a final summary block with totals.

### JSON report

Every run writes:

```text
evals\reports\<run_id>\summary.json
```

Where `<run_id>` is a UTC timestamp + short uuid. The JSON contains:

```json
{
  "run_id":   "20260526T220950Z-48edd7",
  "started_at": "2026-05-26T22:09:50.123456+00:00",
  "tiers":    ["p", "i", "s"],
  "totals":   { "total": 25, "passed": 25, "failed": 0, "skipped": 0 },
  "scenarios": [
    {
      "tier": "p",
      "name": "01_happy_path",
      "passed": true,
      "skipped": false,
      "errors": [],
      "actual":   { "exit_code": 0, "stdout": "...", "valid_csv_rows": [...] },
      "expected": { ... }
    },
    ...
  ]
}
```

Open it in a JSON viewer (VS Code, browser via `start ./summary.json`) to drill into any failure.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | All scenarios in the selected tiers passed (skips don't count as failures) |
| 1 | At least one scenario failed |
| 2 | Configuration error (unknown tier, missing validator script, etc.) |

CI gating: assert exit `0`.

---

## 4. Adding a new scenario

### A new Tier P scenario (CSV validator)

No code edits needed — just data files.

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp\evals"

# 1. Create dataset folder
mkdir datasets\tier_p\24_rtl_arabic
notepad datasets\tier_p\24_rtl_arabic\input.csv
```

`input.csv`:

```csv
id,name
1,محمد علي
2,فاطمة
```

```powershell
# 2. Create expected outcome
notepad expected\tier_p\24_rtl_arabic.json
```

`expected/tier_p/24_rtl_arabic.json`:

```json
{
  "scenario": "24_rtl_arabic",
  "description": "Right-to-left Arabic text must survive the round-trip.",
  "runner_action": "default",
  "expected": {
    "exit_code": 0,
    "stdout_contains": ["Valid rows   : 2"],
    "stderr_contains": [],
    "valid_csv_rows": [["id", "name"], ["1", "محمد علي"], ["2", "فاطمة"]],
    "skip_csv_row_count": 0,
    "skip_reasons_contain": []
  }
}
```

```powershell
# 3. Run just that scenario
python ..\evals\runner.py --only 24_rtl_arabic
```

### Special runner_action values (Tier P)

| `runner_action` | Effect |
|-----------------|--------|
| `"default"` | Copy `input.csv` to a temp file, set `CSV_FILE`, `VALID_CSV`, `SKIP_FILE`, `TABLE_NAME` env vars, run validator |
| `"omit_env_vars"` | Don't set any env vars — tests the validator's missing-vars guard |
| `"point_at_missing_file"` | Set `CSV_FILE` to a path that doesn't exist — tests the file-not-found guard |
| `"write_long_field_file"` | Generate a CSV with one large payload field without checking in a huge fixture |
| `"write_invalid_utf8_file"` | Generate a CSV with invalid UTF-8 bytes and assert a clean failure |

### Field reference for `expected/tier_p/<name>.json`

| Field | Required | Description |
|-------|----------|-------------|
| `scenario` | yes | Must match the folder name |
| `description` | no | Free text |
| `runner_action` | no | Default `"default"` |
| `expected.exit_code` | yes | Integer exit code |
| `expected.stdout_contains` | no | List of substrings that must appear in stdout |
| `expected.stderr_contains` | no | List of substrings that must appear in stderr |
| `expected.valid_csv_rows` | no | Exact list-of-lists of expected valid output rows (`null` to skip the check) |
| `expected.skip_csv_row_count` | no | Exact count of skipped rows |
| `expected.skip_reasons_contain` | no | List of substrings each of which must appear in some skip-row's `_skip_reason` cell |

### A new Tier I or Tier S scenario

These need a runner branch because each scenario does different work (deploy, count rows, run suite, etc.).

1. Create `datasets/tier_i/<NN_name>/NOTES.txt` describing the action.
2. Create `expected/tier_i/<NN_name>.json` declaring the expected outcome.
3. Open `runner.py` → find `run_tier_i_scenario` (or `run_tier_s_scenario`).
4. Add an `if name == "<NN_name>": return _run_<name>(result, expected)` branch.
5. Implement the `_run_<name>` helper following the pattern of `_run_deploy_dev_twice` or `_run_fresh_deploy_then_tests`.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Exit code 2 + `build/csv/validator.py not found at ...` | Running from the wrong directory | `cd PostgreDataMigrationApp` first |
| Every Tier P scenario fails with `No expected file at expected/tier_p/...` | The `expected/tier_p/` folder structure doesn't match `datasets/tier_p/` | Filenames must match (folder name = expected JSON filename without extension) |
| Tier I + S always SKIP | `psql` not on PATH, or no PG instance reachable | Run `psql -c "SELECT 1"` standalone — if that doesn't return `1`, fix that first |
| Tier S fails with `total_assertions: expected >= 85, got None` | The suite output doesn't match the regex the runner uses to parse the totals line | Open `summary.json` → look at `actual.stdout_tail` to see what was actually printed; adjust either the suite's output format or the parser in `_run_fresh_deploy_then_tests` |
| Tier I fails with `row counts changed between runs: {table_name: (n1, n2)}` | A seed INSERT in `env_dev.sql` (or one of its includes) isn't using `ON CONFLICT DO NOTHING` — the eval just caught a real idempotency bug | Fix the seed script; re-run |
| Encoding garbled in terminal (mojibake on emoji / CJK) | Windows console using cp1252 | Set `$env:PYTHONIOENCODING = 'utf-8'`, or use Windows Terminal (which defaults to UTF-8) |
| Tier I times out after 120 s | Deploy script is hanging on a prompt (e.g. `\set` asking for a value) | Make sure `build/environments/env_dev.sql` has no interactive prompts; check `actual.stderr` in the report |
| `SyntaxError: unterminated string literal` when running runner.py | You're on Python <3.10 | Upgrade to Python 3.10+. The runner uses syntax that requires it. |

---

## 6. CI integration

### GitHub Actions — offline tier only

Add to your existing `.github/workflows/python-validator-tests.yml`:

```yaml
    - name: Run Tier P evals
      working-directory: PostgreDataMigrationApp
      run: python evals/runner.py --tiers p
```

This adds ~5 seconds to the run, costs nothing, catches every Tier P regression.

### GitHub Actions — full suite with PostgreSQL service

```yaml
jobs:
  evals-full:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports: ['5432:5432']

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }

      - name: Install psql client
        run: sudo apt-get update && sudo apt-get install -y postgresql-client

      - name: Run all evals
        working-directory: PostgreDataMigrationApp
        env:
          PGHOST:     localhost
          PGPORT:     '5432'
          PGUSER:     postgres
          PGPASSWORD: postgres
        run: python evals/runner.py --tiers p,i,s
```

---

## 7. Where everything lives

```text
PostgreDataMigrationApp/
└── evals/
    ├── PLAN.md              ← architecture and tiering
    ├── FAILURE_MODES.md     ← 29 catalogued failure modes
    ├── USAGE.md             ← this file
    ├── HANDOFF.md           ← what was delivered + next steps
    ├── runner.py            ← orchestrator (606 lines, stdlib only)
    │
    ├── datasets/
    │   ├── tier_p/<NN_name>/input.csv      (or README.txt for env-var-only scenarios)
    │   ├── tier_i/<NN_name>/NOTES.txt
    │   └── tier_s/<NN_name>/NOTES.txt
    │
    ├── expected/
    │   ├── tier_p/<NN_name>.json
    │   ├── tier_i/<NN_name>.json
    │   └── tier_s/<NN_name>.json
    │
    └── reports/<run_id>/summary.json       ← generated at
