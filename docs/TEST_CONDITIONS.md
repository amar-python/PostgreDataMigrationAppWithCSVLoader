# TEST_CONDITIONS — comprehensive catalog

Every test condition that runs against the codebase, in one place. Five categories: Python unit tests, SQL test-suite assertions, and Tier P / I / S evals.

## At a glance

| Category | Count | Where it lives | Driver |
|----------|-------|---------------|--------|
| Python unit tests | 54 | `tests/test_*.py` (9 files) | `unittest discover` |
| SQL test-suite assertions | 142 | `tests/suites/test_0[1-5]_*.sql` | `tests/run_all_tests.sql` |
| Tier P eval scenarios | 23 | `evals/datasets/tier_p/` | `evals/runner.py` |
| Tier I eval scenarios | 1 | `evals/datasets/tier_i/` | `evals/runner.py` |
| Tier S eval scenarios | 1 | `evals/datasets/tier_s/` | `evals/runner.py` |

---

## 1. Python unit tests (54)

Located in `tests/`, run as `python -m unittest discover -s tests -p "test*.py"`. All currently green.

### `tests/test_csv_validator.py` — 4 tests against `build/csv/validator.py`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_fails_when_required_env_vars_missing` | Exit 1; stderr contains `Missing required environment variables` |
| 2 | `test_fails_when_csv_file_missing` | Exit 1; stderr contains `CSV file not found` |
| 3 | `test_splits_valid_and_skipped_rows` | Exit 0; valid+skip rows split correctly; reasons captured |
| 4 | `test_returns_error_when_no_valid_rows` | Exit 1; stderr contains `No valid rows found` |

### `tests/test_evals_runner.py` — 7 tests against `evals/runner.py`

| # | Test | Asserts |
|---|------|---------|
| 5 | `test_load_expected_returns_none_for_missing_scenario` | Returns `None` when no expected JSON exists |
| 6 | `test_discover_scenarios_filters_only_requested_name` | `--only <name>` filter returns just the named scenario |
| 7 | `test_tier_p_reports_unknown_runner_action_as_failure` | Unknown `runner_action` value produces a failed scenario, not a crash |
| 8 | `test_tier_p_generated_invalid_utf8_fails_cleanly` | Invalid-UTF8 generated scenario exits 1 with no traceback |
| 9 | `test_tier_i_skips_when_postgresql_is_unavailable` | Tier I returns `skipped=True` when psql/PG isn't reachable |
| 10 | `test_count_dev_rows_records_none_for_failed_count_query` | `_count_dev_rows` records `None` per table on query failure |
| 11 | `test_have_psql_uses_path_lookup` | `_have_psql()` uses `shutil.which("psql")` |

---

## 2. SQL test-suite assertions (142)

Located in `tests/suites/`. Each suite is a standalone `.sql` file that uses the assertion library defined in `tests/framework/test_framework.sql`. Invoked via `tests/run_all_tests.sql` (orchestrator) or `tests/run_tests.sh` (Bash wrapper).

### Assertion functions available

| Function | Purpose |
|----------|---------|
| `assert_equals(suite, name, expected, actual)` | Exact value match |
| `assert_not_equals(suite, name, expected, actual)` | Values must differ |
| `assert_row_count(suite, name, query, n)` | `COUNT(*)` of query equals `n` |
| `assert_true(suite, name, sql_expr)` | Expression evaluates true |
| `assert_false(suite, name, sql_expr)` | Expression evaluates false |
| `assert_not_null(suite, name, query)` | Query returns a value |
| `assert_null(suite, name, query)` | Query returns NULL |
| `assert_raises(suite, name, query)` | Query must throw an exception (constraint violation, etc.) |

### Suite-by-suite breakdown

| File | `assert_*` invocations | What it covers |
|------|-----------------------|----------------|
| `test_01_organisations_personnel.sql` | 23 | Row counts in `organisations` & `personnel`; FK from personnel → organisations; CHECK constraints on `clearance` and `te_role` enums; UNIQUE on email; NOT NULL on key columns; raises on bad inserts |
| `test_02_programs_phases.sql` | 25 | `test_programs` and `test_phases` seed rows; classification marking values (`UNCLASSIFIED`/`PROTECTED`/`SECRET`/`TOP SECRET`); `phase_type` enum (`DT&E`/`AT&E`/`OT&E`/etc.); date-range rules (start before end); TEMP document version sequencing |
| `test_03_requirements_vcrm.sql` | 23 | `requirements` and `vcrm_entries` seed rows; **100% VCRM coverage check for CYB9131** (every requirement has at least one mapped test case); intentional gap detection for LAND400 (verifies the gap is reported, not hidden); per-program coverage percentages |
| `test_04_execution_defects.sql` | 38 | `test_events`, `test_results`, `defect_reports` seed rows; verdict mix (pass/fail/blocked/inconclusive); DR → fail result linkage; `severity` enum (`critical`/`major`/`minor`/`observation`); `resolved_at` lifecycle (NULL while open, populated when closed) |
| `test_05_schema_and_business_rules.sql` | 31 | Table existence; index existence; trigger firing; updated_at timestamp auto-update; cross-table business rules (e.g. `test_results.event_id` must reference an event in the same phase as the test case) |

The suite reports **142 assertions** at runtime (`142 | 142 | 0 | 0 | 100.0%`). A raw grep of `assert_*` call sites returns fewer, because some assertions run inside loops.

**Pass criteria for Tier S:** suite output contains `ALL TESTS PASSED` and the total/pass-rate line shows 100%.

---

## 3. Tier P eval scenarios — 23

Located in `evals/datasets/tier_p/`. Each scenario folder has an `input.csv` (or generated bytes for special cases) and a matching `expected/tier_p/<name>.json`. Runs offline against `build/csv/validator.py` as a subprocess.

| # | Scenario | What it tests | Expected outcome |
|---|----------|--------------|------------------|
| 01 | `01_happy_path` | 3 valid rows, no header issues | Exit 0; valid=3; skip=0 |
| 02 | `02_empty_file` | 0-byte file | Exit 1; stderr `CSV file is empty` |
| 03 | `03_empty_header_only_newline` | Single newline (empty header row) | Exit 1; stderr `Header row is empty` |
| 04 | `04_no_valid_rows` | Header present but every data row blank | Exit 1; stderr `No valid rows found`; 2 skipped (`empty row`) |
| 05 | `05_mixed_valid_skipped` | 2 valid + 1 empty + 1 column-mismatch | Exit 0; valid=2; skip=2; reasons `empty row` + `column mismatch` |
| 06 | `06_duplicate_headers` | `id,id,name` header | Exit 0; stdout warns `Duplicate column names`; row still processed |
| 07 | `07_column_mismatch_short` | Header has 3 cols; one row has 2 | Exit 0; 2 valid, 1 skipped with `column mismatch — expected 3, got 2` |
| 08 | `08_column_mismatch_long` | Header has 2 cols; one row has 5 | Exit 0; 2 valid, 1 skipped with `column mismatch — expected 2, got 5` |
| 09 | `09_empty_row` | Row with only commas | Exit 0; row skipped as `empty row` |
| 10 | `10_utf8_bom` | UTF-8 BOM at file start | Exit 0; BOM stripped by `utf-8-sig`; headers parse cleanly |
| 11 | `11_utf8_emoji` | Emoji in values | Exit 0; emoji preserved end-to-end |
| 12 | `12_crlf_line_endings` | `\r\n` line endings | Exit 0; csv module handles natively |
| 13 | `13_quoted_comma` | `"Smith, John"` quoted field | Exit 0; field preserved as single value |
| 14 | `14_quoted_newline` | Embedded `\n` inside quoted field | Exit 0; row parsed correctly with embedded newline |
| 15 | `15_quoted_quote` | `"she said ""hi"""` escaped quote | Exit 0; value becomes `she said "hi"` |
| 16 | `16_whitespace_only_row` | Row with only spaces | Exit 0; skipped as `empty row` (cell.strip() returns empty) |
| 17 | `17_header_whitespace` | ` id , name ` leading/trailing whitespace in headers | Exit 0; headers normalised to `id`, `name` |
| 18 | `18_utf8_cjk` | Japanese CJK characters | Exit 0; round-trip preserved |
| 19 | `19_missing_env_vars` | Runner deliberately omits env vars | Exit 1; stderr `Missing required environment variables` |
| 20 | `20_missing_csv_file` | `CSV_FILE` points at a path that doesn't exist | Exit 1; stderr `CSV file not found` |
| 21 | `21_utf8_arabic` | Right-to-left Arabic text | Exit 0; preserved end-to-end |
| 22 | `22_very_long_field` | Generated ~50KB single field | Exit 0; accepted as one row |
| 23 | `23_invalid_utf8_bytes` | Generated `0xE9` Latin-1 byte inside UTF-8 file | Exit 1; clean exit with decode-error message; no Python traceback |

---

## 4. Tier I eval scenarios — 1

Located in `evals/datasets/tier_i/`. Requires reachable PostgreSQL; skips cleanly otherwise.

| # | Scenario | What it tests | Expected outcome |
|---|----------|--------------|------------------|
| 01 | `01_deploy_dev_twice` | Runs `psql -f build/environments/env_dev.sql` twice in a row; counts rows in every seeded `te_dev.*` table between runs | `first_run_exit_code: 0`, `second_run_exit_code: 0`, `row_counts_unchanged: true`, `min_seeded_tables_present: 11`. Proves `ON CONFLICT DO NOTHING` seed pattern + idempotent DDL. |

---

## 5. Tier S eval scenarios — 1

Located in `evals/datasets/tier_s/`. Requires reachable PostgreSQL; skips cleanly otherwise.

| # | Scenario | What it tests | Expected outcome |
|---|----------|--------------|------------------|
| 01 | `01_fresh_deploy_then_all_tests_pass` | Deploys Dev fresh; runs `tests/run_all_tests.sql` with all `--set` table-name overrides; parses the suite output | `deploy_exit_code: 0`, `tests_exit_code: 0`, stdout contains `ALL TESTS PASSED`, `min_total_assertions: 85`, `min_pass_rate_percent: 100.0`. Proves the deployed system is correct end-to-end. |

---

## 6. Load-time verification queries — REMOVED

The `input_data/` directory (`load_input_data.sql`, `load_input_data.ps1`) is
**not present in this repository**. CSV ingestion is now handled by
`build/csv/validator.py` plus the per-engine loaders in `build/csv/`, driven by
`build/csv_loader.sh`. Those paths are covered by the Tier P evals (category 3)
and the Python unit tests (category 1).

---

## Test-condition coverage matrix

A single view of which layer covers which kind of failure mode.

| Failure mode | Python unit | SQL suite | Tier P | Tier I | Tier S | Load verify |
|--------------|------------:|----------:|-------:|-------:|-------:|------------:|
| Validator: missing env vars | ✅ (1) | — | ✅ (19) | — | — | — |
| Validator: missing file | ✅ (2) | — | ✅ (20) | — | — | — |
| Validator: split valid/skip | ✅ (3) | — | ✅ (05) | — | — | — |
| Validator: no valid rows | ✅ (4) | — | ✅ (04) | — | — | — |
| Validator: empty file | — | — | ✅ (02) | — | — | — |
| Validator: BOM handling | — | — | ✅ (10) | — | — | — |
| Validator: unicode (emoji, CJK, RTL) | — | — | ✅ (11/18/21) | — | — | — |
| Validator: CRLF | — | — | ✅ (12) | — | — | — |
| Validator: quoted fields (3 variants) | — | — | ✅ (13/14/15) | — | — | — |
| Validator: header whitespace | — | — | ✅ (17) | — | — | — |
| Validator: empty/whitespace rows | — | — | ✅ (09/16) | — | — | — |
| Validator: column count mismatch | — | — | ✅ (07/08) | — | — | — |
| Validator: duplicate column names | — | — | ✅ (06) | — | — | — |
| Validator: very long row | — | — | ✅ (22) | — | — | — |
| Validator: invalid UTF-8 bytes | ✅ (8) | — | ✅ (23) | — | — | — |
| Runner: unknown runner_action | ✅ (7) | — | — | — | — | — |
| Runner: scenario discovery | ✅ (5/6) | — | — | — | — | — |
| Runner: psql probe | ✅ (11) | — | — | — | — | — |
| Runner: handle psql unavailable | ✅ (9) | — | — | ✅ implicit | ✅ implicit | — |
| Runner: count_dev_rows resilience | ✅ (10) | — | — | — | — | — |
| Schema: tables exist | — | ✅ (05) | — | — | ✅ | — |
| Schema: indexes exist | — | ✅ (05) | — | — | ✅ | — |
| Schema: triggers fire | — | ✅ (05) | — | — | ✅ | — |
| Schema: FK integrity | — | ✅ (01) | — | — | ✅ | — |
| Schema: CHECK / UNIQUE / NOT NULL constraints | — | ✅ (01/02/04) | — | — | ✅ | — |
| Domain: VCRM coverage 100% for CYB9131 | — | ✅ (03) | — | — | ✅ | — |
| Domain: classification markings | — | ✅ (02) | — | — | ✅ | — |
| Domain: verdict + DR linkage | — | ✅ (04) | — | — | ✅ | — |
| Domain: TEMP version sequencing | — | ✅ (02) | — | — | ✅ | — |
| Operational: deploy is idempotent | — | — | — | ✅ (01) | — | — |
| Operational: full suite green after deploy | — | — | — | — | ✅ (01) | — |
| Data load: row counts match CSV | — | — | — | — | — | ✅ (S1) |
| Data load: staging vs target reconciliation | — | — | — | — | — | ✅ (S3) |
| Data load: duplicate PKs flagged | — | — | — | — | — | ✅ (S4) |
| Data load: NOT NULL columns satisfied | — | — | — | — | — | ✅ (S5) |
| Data load: aggregates plausible | — | — | — | — | — | ✅ (S2) |

Numbers in parentheses reference the test numbers in the per-layer tables above.

---

## How to run each category

```powershell
# Python unit tests (11)
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp"
python -m unittest discover -s tests -p "test*.py"

# Tier P evals (23) — offline
python evals\runner.py

# Tier P + I + S evals (25 total) — needs PG
$env:PGPASSWORD = 'postgres'; $env:PGDATABASE = 'migration_test'
python evals\runner.py --tiers p,i,s

# SQL test suite directly (alternative to Tier S)
psql -d migration_test --set schema_name=te_dev -f tests\run_all_tests.sql

```

---

## Where to add a new test condition

| Kind of thing you want to assert | Add it here |
|---------------------------------|------------|
| Single Python function behaves correctly | `tests/test_csv_validator.py` or `tests/test_evals_runner.py` |
| A SQL business rule holds across seed data | `tests/suites/test_0X_<topic>.sql` using `assert_*` |
| End-to-end behaviour against the validator binary | `evals/datasets/tier_p/<NN_name>/` + `evals/expected/tier_p/<NN_name>.json` |
| End-to-end PostgreSQL operational scenario | `evals/datasets/tier_i/<NN_name>/` + runner branch in `evals/runner.py` |
| End-to-end SQL-suite-passes scenario | `evals/datasets/tier_s/<NN_name>/` + runner branch |
| Visual / runtime sanity check on the loaded data | New `\echo` + `SELECT` block in `input_data/load_input_data.sql` |

When a single failure case naturally fits two layers (e.g. the validator's missing-env-var guard appears as Python unit test #1 AND Tier P scenario 19), keep both — the unit test runs in 0.2s during dev, and the Tier P scenario asserts the same property end-to-end through the subprocess interface.
