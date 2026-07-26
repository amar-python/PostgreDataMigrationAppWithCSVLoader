# ARCHITECTURE — PostgreDataMigrationApp

The project is organised into three categories. Every file in the repo belongs to exactly one of them.

```text
PostgreDataMigrationApp/
|
+-- build/             <-- production code that gets deployed
+-- tests/             <-- correctness coverage for the production code
+-- evals/             <-- data-driven black-box scenarios
|
+-- README.md  LICENSE  ARCHITECTURE.md  .gitignore
```

## Why the split

| Category | Question it answers | Failure means |
|----------|--------------------|---------------|
| **build** | "What do we ship?" | The deployed system is broken |
| **tests** | "Is the code correct?" | Some function has a bug |
| **evals** | "Does it handle real-world data correctly end-to-end?" | A whole-system behaviour regressed |

The three layers can break independently, so we keep them physically separate. Tests live close to the code they verify; evals stay in their own folder because they're driven by data, not code.

## What's in each folder

### `build/` — production code

| Path | What it is |
|------|-----------|
| `build/te_core_schema.sql` | PostgreSQL master schema (legacy entry point) |
| `build/te_seed_data.sql` | Seed data |
| `build/csv/` | Python CSV validator (`validator.py`), per-engine shell loaders (`loader_*.sh`), and `samples/` |
| `build/adapters/` | Per-engine deployment adapters (`adapter_postgresql.sh`, `adapter_mariadb.sh`, etc.) |
| `build/schema/` | Engine-specific DDL and seed data |
| `build/environments/` | PostgreSQL per-environment launchers. Only `env_dev.example.sql` is committed; concrete `env_<env>.sql` files are gitignored and created from it. |
| `build/terraform-github-repos/` | GitHub repository management as Infrastructure-as-Code |
| `build/setup.sh` | Interactive multi-database configuration wizard |
| `build/deploy_all.sh` | Multi-engine deployment router |
| `build/csv_loader.sh` | Schema-agnostic CSV ingestion: any CSV → auto-created table |
| `build/csv_utilise.sh` | Companion to the loader: list / describe / peek / export / drop CSV-loaded tables (PostgreSQL) |

### `tests/` — correctness coverage

| Path | What it is |
|------|-----------|
| `tests/framework/test_framework.sql` | Assertion library + results table |
| `tests/suites/test_01..05_*.sql` | 142 SQL assertions across 5 suites |
| `tests/run_all_tests.sql` | Master SQL test orchestrator |
| `tests/run_tests.sh` | Bash wrapper that sources `config.local.env` |
| `tests/run_python_tests.ps1` | Windows runner — invoked by the GitHub Actions workflow |
| `tests/conftest.py` | pytest env-var isolation between tests |
| `tests/test_csv_validator.py` | unittest for `build/csv/validator.py` |
| `tests/test_csv_utilise.py` | unit tests for `build/csv_utilise.sh` argument parsing |
| `tests/test_csv_loader_arbitrary_shapes.py` | integration: arbitrary CSV shapes through loader → PG (skips without PG) |
| `tests/test_e2e_pipeline.py` | e2e: CSV → validate → load → verify (DB half skips without PG) |
| `tests/test_parity.py` | cross-environment row-count / schema parity (skips without PG) |
| `tests/test_regression.py` | pinned tests for previously found bug classes |
| `tests/test_security.py` | static credential/SQL-pattern scans |
| `tests/test_snapshot.py` | golden-file output comparisons (`tests/snapshots/`) |
| `tests/test_evals_runner.py` | unittest for `evals/runner.py` itself |

### `evals/` — data-driven scenarios

| Path | What it is |
|------|-----------|
| `evals/PLAN.md` | Scope, layout, phases, tier rationale |
| `evals/USAGE.md` | End-to-end run instructions |
| `evals/FAILURE_MODES.md` | Catalogue of 29 failure modes |
| `evals/USAGE.md` | Quick-start |
| `evals/HANDOFF.md` | What was delivered + next steps |
| `evals/runner.py` | Scenario discovery + diff engine + JSON report writer |
| `evals/datasets/tier_p/*` | 23 CSV scenarios for `build/csv/validator.py` |
| `evals/datasets/tier_i/*` | Idempotency scenarios (run `build/environments/env_dev.sql` twice) |
| `evals/datasets/tier_s/*` | SQL suite integration scenarios |
| `evals/expected/tier_*/*.json` | Expected outcome per scenario |
| `evals/reports/` | Runtime output (gitignored) |

## Dependency direction

```text
evals/   --reads--->  build/csv/validator.py
                      build/environments/env_dev.sql
                      tests/run_all_tests.sql

tests/   --reads--->  build/csv/validator.py
                      evals/runner.py  (just to verify it imports cleanly)

build/   --reads--->  nothing in tests/ or evals/
```

`build/` has no dependency on the other two layers. That's the property to defend on every change.

## When you add a new file, ask yourself

1. Does this run in production? → `build/<engine-or-folder>/`
2. Does this assert that some function is correct? → `tests/`
3. Does this drive a scenario through the deployed system from outside? → `evals/`

If a file would fit two of those, split it — the test belongs in `tests/`, the production code in `build/`.

## What's not part of any layer

- `README.md`, `LICENSE`, `ARCHITECTURE.md`, `.gitignore` — repo metadata
- `_norton_/`, `extend to Oracle dbs/` — exploratory user folders, not currently wired up
- `scripts/insert_random_test_data.sql` — auxiliary helper not yet categorised

These are left at the repo root and excluded from the layer model. They can move into one of the three folders if their role becomes clear.

## Path conventions inside the layers

- Code inside `evals/runner.py` computes `PROJECT_ROOT = Path(__file__).resolve().parent.parent` and reaches into `build/csv/validator.py`, `build/environments/env_dev.sql`, `tests/run_all_tests.sql` from there.
- Code inside `tests/test_csv_validator.py` does `Path(__file__).resolve().parents[1] / "build" / "csv" / "validator.py"`.
- Shell scripts inside `build/` cd into their own directory and use relative paths (`./adapters/...`, `./schema/...`).
- Nothing in `build/` references `tests/` or `evals/`.

If a new file has to break these rules, document why in this
