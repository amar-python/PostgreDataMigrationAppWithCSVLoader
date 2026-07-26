# Hand-off summary — evals/ package

**Date:** 2026-05-26
**Scope this round:** PostgreSQL only (Tiers P + I + S). MariaDB / SQLite / etc. deferred.

## What was delivered

| File / folder | What it is |
|--------------|-----------|
| `evals/PLAN.md` | Scope, folder layout, tiering, phases |
| `evals/FAILURE_MODES.md` | 29 catalogued failure modes; all 22 Tier P modes now covered |
| root `README.md` + `evals/USAGE.md` | How to run; CLI flags; exit codes |
| `evals/runner.py` | Single-file scenario discovery + diff engine + JSON report writer (606 lines) |
| `evals/datasets/tier_p/01-23/` | 23 CSV scenarios (happy + empty + malformed + unicode + generated edge cases) |
| `evals/datasets/tier_i/01_deploy_dev_twice/` | Idempotency scenario (NOTES only; runner drives the work) |
| `evals/datasets/tier_s/01_fresh_deploy_then_all_tests_pass/` | SQL-suite integration scenario |
| `evals/expected/tier_p/*.json` | 23 expected-outcome files |
| `evals/expected/tier_i/01_deploy_dev_twice.json` | Expected outcome (exit codes + row-count parity) |
| `evals/expected/tier_s/01_fresh_deploy_then_all_tests_pass.json` | Expected outcome (142/142 + ALL TESTS PASSED) |
| `evals/reports/` | Auto-created at runtime; one folder per run with `summary.json` |

## What was executed

| Tier | Result | Notes |
|------|--------|-------|
| **P** (23 scenarios) | **23 PASS / 0 FAIL** | Executed locally against the real `build/csv/validator.py` |
| **I** (1 scenario)   | **SKIP** | No PostgreSQL in the sandbox — clean skip with diagnostic |
| **S** (1 scenario)   | **SKIP** | Same |

Latest local run report: `evals/reports/20260531T094230Z-223fa5/summary.json`

## What you should do next (in order)

### 1. Verify Tier P on your machine

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp"
python evals\runner.py
```

Expect: `total: 23, passed: 23, failed: 0, skipped: 0` and exit code 0.

### 2. Run Tier I + S against your local PostgreSQL

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp"
# Make sure libpq vars are set or peer auth works:
#   $env:PGHOST = 'localhost'
#   $env:PGUSER = 'postgres'
#   $env:PGPASSWORD = '...'
python evals\runner.py --tiers p,i,s
```

Expect with PostgreSQL available: 23 P pass, 1 I pass, 1 S pass = **25 / 25**.

If Tier I fails on the row-count parity, check the `actual.row_counts_first` vs
`actual.row_counts_second` in `summary.json` — that pinpoints the table whose seed
inserts aren't using `ON CONFLICT DO NOTHING`.

If Tier S fails, the runner captures the last 2 KB of the suite's stdout in
`actual.stdout_tail` — that almost always pinpoints which assertion failed.

### 3. Archive the workspace cruft

The parent folder `Migration using ai\` still contains my earlier Python demo
(`src/`, `tests/`, `evals/` at root, `config.yaml`, etc.) that has nothing to do
with `PostgreDataMigrationApp`. A cleanup script is ready:

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai"
.\cleanup_workspace.ps1            # preview (dry run)
.\cleanup_workspace.ps1 -Apply     # commit the moves
```

Everything is **moved** to `_archive_demo\` (not deleted). Reversible by drag-back.
`PostgreDataMigrationApp\` is on the never-touch list.

### 4. (Optional) Wire evals into CI

Your existing GitHub Actions workflow `python-validator-tests.yml` only runs
the Python unit tests in `tests/`. To add the 23 Tier P evals:

Add to the workflow:

```yaml
    - name: Run Tier P evals
      run: python evals/runner.py --tiers p
      working-directory: PostgreDataMigrationApp
```

Tier I and S can be added when you have PostgreSQL in your CI runner.

## What's deferred to a later round

| Item | Why deferred |
|------|--------------|
| Tier X — cross-DB schema equivalence (MariaDB / SQLite / Teradata) | You explicitly said "ignore them for now" |
| Tier E — cross-environment (Dev/Test/Staging/Prod) structural parity | Not needed until you ship beyond Dev |
| Tier D — extended domain-rule evals beyond suite 05 | Existing 142 assertions already cover the high-value rules |
| Performance / scale (1M+ rows) | Would need a fixture generator — separate round |
| AI-assisted anomaly detection | Out of scope for deterministic evals |
| Single-field >128 KB | Current eval covers 50KB; larger-than-default `csv` field-size behavior remains future scope |

Catalogued in `FAILURE_MODES.md` so they're not lost.

## File counts

| Category | Count |
|----------|-------|
| Markdown docs (root README, PLAN, FAILURE_MODES, USAGE, HANDOFF) | 5 |
| Python (`runner.py`) | 1 |
| CSV input fixtures | 20 (scenarios 19, 20, 22, and 23 are generated/no-input scenarios) |
| Expected JSON files | 25 |
| Scenario note/TXT files | 4 |
| **Total files created** | **55** |

## Open items

Nothing blocking. If you want me to take the next step, ask for:

- "extend Tier P to N more scenarios" (e.g. RTL, very-long-row, latin-1)
- "add Tier X — cross-DB equivalence" once you have other DB engines installed
- "wire the evals into the GitHub Actions workflow"
- "build a sample-data generator that produces 100 K / 1 M row CSVs for perf"
