# CSV Migrator — end-to-end checks

## Fixture CSVs (`scripts/fixtures/`)

| File | What it exercises |
| --- | --- |
| `basic.csv` | Typed inference — int8, numeric, boolean, date |
| `ambiguous-headers.csv` | Column names that used to collide with PL/pgSQL loop vars (`i`, `t`, `s`, `idx`) |
| `quoted.csv` | Quoted fields, embedded newlines, escaped `""` |
| `bad-types.csv` | Rows that should land in the row-error report, not the table |
| `dup-rows.csv` | In-file duplicate row de-duplication via `_row_hash` |
| `empty.csv` | Header-only — should surface the "must have a header row and at least one data row" error |

Drop them onto the UI in one batch to exercise the preview + import + diagnostics + error export end to end.

## DB-level regression suite (`scripts/e2e-csv.sh`)

Runs `create_csv_table` directly against Postgres with the column names that used to break things. Requires `PG*` env (already set in this sandbox):

```bash
bash scripts/e2e-csv.sh
```

Exits non-zero if any case regresses, so it can be wired into CI later.
