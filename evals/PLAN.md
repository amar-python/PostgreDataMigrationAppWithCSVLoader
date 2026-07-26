# Evals package — PostgreDataMigrationApp

This folder holds **data-driven evals** for the T&E Database Framework. Evals complement (but don't replace) the existing SQL test suites under `tests/suites/` and the Python unit tests under `tests/test_csv_validator.py`.

## Why a separate `evals/` folder

| Aspect | `tests/` (existing) | `evals/` (this folder) |
|--------|--------------------|--------------------|
| Driver | Code (SQL assertions + Python unittest) | Data (CSV fixtures + expected JSON) |
| Adding a new scenario | Edit Python or SQL | Drop a new `datasets/<NN>/input.csv` and `expected/<NN>.json` |
| What gets reviewed | Code diffs | Data fixtures (much easier to eyeball) |
| Failure granularity | One Python assert, one SQL assert | exit_code + stderr + stdout + output-file contents — all in one report |
| Scope | Schema correctness, business rules, validator unit behaviour | End-to-end behaviour: validator interface, idempotency, full SQL-suite-passes-after-load |

In short: `tests/` proves the **code is correct**; `evals/` proves the **framework behaves correctly on real-world data and operational scenarios**.

## Scope (this round)

- **Database engine:** PostgreSQL only.
  - MariaDB / SQLite / InfluxDB / Redis / Teradata adapters are deliberately out of scope until Postgres evals are stable. The eval structure is engine-agnostic so they can be added later.
- **Tiers in scope:**
  - **Tier P** — Python CSV validator (`build/csv/validator.py`). Pure data-in / files-out. No DB.
  - **Tier I** — Idempotency of `deploy_all.sh` against a clean Dev PostgreSQL.
  - **Tier S** — SQL test suite integration: deploy fresh + run all 5 suites and assert 142/142.
- **Tiers deferred:**
  - **Tier X** — Cross-DB schema equivalence (MariaDB/SQLite). Out until Postgres is locked in.
  - **Tier E** — Cross-environment (Dev/Test/Staging/Prod) structural equivalence.
  - **Tier D** — Extended domain-rule evals beyond what suite 05 already covers.

## Folder layout

```text
PostgreDataMigrationApp/
└── evals/
    ├── PLAN.md                          ← this file
    ├── FAILURE_MODES.md                 ← failure-mode catalogue
    ├── runner.py                        ← scenario discovery + diff engine + report
    │
    ├── datasets/
    │   ├── tier_p/                      ← Python CSV validator scenarios
    │   │   ├── 01_happy_path/
    │   │   │   └── input.csv
    │   │   ├── 02_empty_file/
    │   │   └── … (23 scenarios)
    │   │
    │   ├── tier_i/                      ← idempotency scenarios
    │   │   └── 01_deploy_dev_twice/
    │   │       └── NOTES.txt            ← what the runner does (no CSV needed)
    │   │
    │   └── tier_s/                      ← SQL suite integration
    │       └── 01_fresh_deploy_then_all_tests_pass/
    │           └── NOTES.txt
    │
    ├── expected/
    │   ├── tier_p/
    │   │   ├── 01_happy_path.json
    │   │   ├── 02_empty_file.json
    │   │   └── …
    │   ├── tier_i/
    │   │   └── 01_deploy_dev_twice.json
    │   └── tier_s/
    │       └── 01_fresh_deploy_then_all_tests_pass.json
    │
    └── reports/                         ← runtime output (gitignored)
        └── <run_id>/
            ├── tier_p_summary.json
            ├── tier_i_summary.json
            ├── tier_s_summary.json
            └── overall.json
```

Each scenario is self-contained. To add a new one: create a new folder under `datasets/<tier>/` and a matching `expected/<tier>/<scenario>.json`. No code edits.

## Expected JSON contract

Each `expected/<tier>/<scenario>.json` declares what the runner should see. Only the fields populated are diffed — everything else is ignored. Example:

```json
{
  "scenario": "05_mixed_valid_skipped",
  "expected": {
    "exit_code": 0,
    "stdout_contains": ["Valid rows   : 2", "Skipped rows : 2"],
    "stderr_contains": [],
    "valid_csv_rows": [["id", "name"], ["1", "Alice"], ["3", "Bob"]],
    "skip_csv_rows_count": 2,
    "skip_reasons_contain": ["empty row", "column mismatch"]
  },
  "notes": "Two valid rows, two skipped — one empty, one with too few fields."
}
```

## Runner behaviour

`runner.py`:

1. Discovers every folder under `datasets/<tier>/`.
2. For Tier P: copies the scenario's `input.csv` to a temp file, sets env vars, runs `python3 build/csv/validator.py`, captures exit + stdout + stderr + output files, diffs against `expected/<tier>/<scenario>.json`.
3. For Tier I and Tier S: runs the orchestration script (`deploy_all.sh dev`, `tests/run_tests.sh dev`) and asserts the documented outcomes.
4. Prints one line per scenario: `PASS / FAIL / SKIPPED`.
5. Writes per-tier and overall JSON summaries under `reports/<run_id>/`.

Exit code: 0 if all scenarios in selected tiers pass, 1 otherwise. CI-friendly.

## Tiering

- **Tier P** runs anywhere — only needs Python + the validator script. **Fully offline.**
- **Tier I** and **Tier S** need a live PostgreSQL instance + `psql` on PATH + the values in `config.local.env`. They skip cleanly if no DB is reachable.

## Phasing

| Phase | What | Status |
|-------|------|--------|
| 0 | PLAN + FAILURE_MODES + root README coverage | **DONE** |
| 1 | Tier P dataset folders (23 scenarios) + expected JSONs | DONE |
| 2 | Tier P runner.py | DONE |
| 3 | Execute Tier P locally; show results | DONE / awaiting your review |
| 4 | Tier I scaffolding + runner extension | next |
| 5 | Tier S scaffolding + runner extension | next |
| 6 | (Future) Tier X across MariaDB/SQLite once Postgres is locked in | deferred |

## What this DOES NOT do

- Doesn't replace the existing 85-assertion SQL suite under `tests/suites/` — Tier S runs those after a fresh deploy and counts the pass total.
- Doesn't replace the Python unit tests in `tests/` — Tier P is broader (23 scenarios), while unit tests keep fast in-Python coverage for the validator and eval runner.
- Doesn't include performance/load testing yet (scope creep — separate suite if needed later).

## Open questions

None blocking — proceeding with the plan above. If you want to change scope or add scenarios after seeing the Tier P results, edit `FAILURE_MODES.md` and let me
