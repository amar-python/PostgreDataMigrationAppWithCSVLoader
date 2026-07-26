# Failure-mode catalogue — PostgreDataMigrationApp

Each row is a real-world data or operational scenario that *could* break the framework. For each: a concrete example, the **expected** behaviour, and the eval scenario number that proves it.

Legend:

- ✅ **handles correctly** — framework already produces the right outcome
- ⚠️ **partial** — works but not asserted by an eval today
- ❌ **gap** — silently accepts, crashes, or fails noisily without a clean signal

---

## Tier P — Python CSV validator (`build/csv/validator.py`)

These run without any database. Driven by `evals/runner.py` against the actual `build/csv/validator.py` script as a subprocess.

| # | Failure mode | Example input | Expected behaviour | Current | Eval ID |
|---|--------------|--------------|--------------------|---------|---------|
| P1 | Missing required env vars | (no CSV_FILE) | exit 1; stderr contains "Missing required environment variables" | ✅ | 19 |
| P2 | CSV file path doesn't exist | `CSV_FILE=/tmp/nope.csv` | exit 1; stderr contains "CSV file not found" | ✅ | 20 |
| P3 | Empty file (0 bytes) | `` | exit 1; stderr contains "CSV file is empty" | ✅ | 02 |
| P4 | Header-only file (no data rows) | `id,name\n` | exit 1; stderr contains "No valid rows found" | ✅ | 04 |
| P5 | All valid rows | `id,name\n1,Alice\n2,Bob\n3,Carol\n` | exit 0; valid count 3, skip count 0 | ✅ | 01 |
| P6 | Mixed valid + skipped | header + 2 valid + empty row + col-mismatch row | exit 0; valid 2, skip 2, reasons "empty row" and "column mismatch" | ✅ | 05 |
| P7 | Completely empty row | `id,name\n1,Alice\n,\n2,Bob\n` | row 3 skipped as "empty row" | ✅ | 08 |
| P8 | Whitespace-only row | `id,name\n1,Alice\n  ,  \n` | row 3 skipped as "empty row" (cell.strip() returns empty) | ✅ | 16 |
| P9 | Row with fewer fields than header | header has 3, row has 2 | row skipped as "column mismatch" | ✅ | 07 |
| P10 | Row with more fields than header | header has 2, row has 3 | row skipped as "column mismatch" | ✅ | 07b |
| P11 | Duplicate column names | `id,id,name\n…` | exit 0 but stdout contains "Duplicate column names" warning | ✅ | 06 |
| P12 | Leading/trailing whitespace in headers | header `id,name` with surrounding spaces | headers normalised to `id`, `name` (stripped) | ✅ | 17 |
| P13 | UTF-8 BOM at start of file | U+FEFF byte then `id,name\n…` | BOM stripped (file opened with `utf-8-sig`); behaves as if no BOM | ✅ | 09 |
| P14 | UTF-8 emoji in value | `1,Alice 👋` | preserved through; row valid | ✅ | 10 |
| P15 | UTF-8 CJK characters | `1,田中花子` | preserved through; row valid | ✅ | 18 |
| P16 | CRLF line endings | `id,name\r\n1,Alice\r\n` | csv module handles natively; row valid | ✅ | 11 |
| P17 | Quoted field containing comma | `id,note\n1,"Smith, John"\n` | parsed as single field `Smith, John` | ✅ | 13 |
| P18 | Quoted field containing newline | `id,note\n1,"line1\nline2"\n` | parsed as single row, note has embedded newline | ✅ | 14 |
| P19 | Quoted field containing escaped quote | `id,note\n1,"she said ""hi"""\n` | parsed as `she said "hi"` | ✅ | 15 |
| P20 | Unicode RTL (Arabic) | `1,محمد` | preserved through; row valid | ✅ | 21 |
| P21 | Very long row (50KB single field) | massive single value | accepted as one row | ✅ | 22 |
| P22 | Mixed encoding (Latin-1 bytes inside UTF-8) | `\xe9` bytes in middle of file | clean exit 1; stderr reports unexpected decode error; no traceback | ✅ | 23 |

**Of 22 modes:** all 22 are now covered by Tier P evals. Scenario numbering is 01–23 because the short and long column-mismatch cases are separate eval fixtures.

---

## Tier I — Idempotency

| # | Failure mode | Example scenario | Expected behaviour | Current | Eval ID |
|---|--------------|------------------|--------------------|---------|---------|
| I1 | Re-run `deploy_all.sh dev` on a deployed DB | run twice in a row | exit 0 both times; no new rows inserted on 2nd run (`ON CONFLICT DO NOTHING` seed pattern); no `CREATE TABLE` errors | ✅ | 01 |
| I2 | Re-run after `\set` changes to identifiers (table renamed) | edit env_dev.sql to rename a table, re-run | should fail safely (rename isn't auto-detected) — manual migration needed | ⚠️ | not in initial set |
| I3 | Schema deployed; user manually drops a table; re-run | DROP TABLE te_dev.organisations; re-run env_dev.sql | table re-created; FK-dependent seed inserts pass | ✅ | not in initial set |
| I4 | Re-run with PG service offline | stop PG, run deploy_all.sh | exit non-zero; stderr contains connection-refused | ✅ | not in initial set |

Tier I initial scope: only I1 (the core re-runnability claim from the README).

---

## Tier S — SQL suite integration

| # | Failure mode | Example scenario | Expected behaviour | Current | Eval ID |
|---|--------------|------------------|--------------------|---------|---------|
| S1 | Fresh deploy + all 5 suites must pass | `deploy_all.sh dev` then `run_tests.sh dev` | exit 0; "ALL TESTS PASSED" appears in stdout; overall pass_rate 100.0% | ✅ | 01 |
| S2 | Deploy without seed data; suites should fail predictably | `\set include_seed_data false`; run suites | some suites expecting non-zero row counts fail; runner reports the count drift | ⚠️ | not in initial set |
| S3 | Deploy with corrupted seed (intentionally invalid FK) | manually edit seed insert to break an FK | deploy_all fails at seed step; no schema corruption | ⚠️ | not in initial set |

Tier S initial scope: only S1.

---

## What this catalogue does NOT yet cover

- **Multi-DB equivalence** (cross-engine schema parity) — deferred until PG is locked in.
- **Performance / scale** (1M-row load timing) — separate suite if needed later.
- **Cross-environment structural equivalence** (Dev vs Test vs Staging vs Prod) — Tier E, future.
- **Domain-rule deep dives beyond suite 05** — Tier D, future.
- **Validator behaviour on >128KB single field** — beyond the current 50KB eval and Python `csv` default field-size assumptions.

---

## Summary

| Tier | Modes catalogued | Modes in initial eval set | Deferred |
|------|------------------|---------------------------|----------|
| P | 22 | 22 | 0 |
| I | 4 | 1 | 3 |
| S | 3 | 1 | 2 |
| **Total** | **29** | **21** | **7** |

The current eval set covers every catalogued Tier P mode plus the initial Tier I and Tier S operational scenarios. The remaining deferred items are PostgreSQL oper
