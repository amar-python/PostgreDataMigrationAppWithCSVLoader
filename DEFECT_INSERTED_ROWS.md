# Defect — `insertedRows` under-reports for files over 100 rows

**Found by:** `tests/test_issue_04_multi_file_upload.py::test_a_larger_file_loads_completely`
**Affects:** `api/services/dynamic_loader.py`, insert loop
**Severity:** Medium — data is correct; the reported count is not
**Directly breaks:** Issue #5 ("created" count), and the row count shown in
"Migrated files"

---

## Symptom

Uploading a 250-row CSV reports 50 rows created. All 250 rows are present in
the table.

```text
AssertionError: 50 != 250 : all distinct rows should load
```

## Cause

`psycopg2.extras.execute_values` takes `page_size=100` by default. It splits
the argument list into pages and issues **one INSERT statement per page**.
`cursor.rowcount` reflects only the **last** statement executed.

For 250 rows that is three statements — 100, 100, 50 — so `rowcount` is 50.

```python
# api/services/dynamic_loader.py
for i in range(0, len(to_insert), 500):
    chunk = to_insert[i : i + 500]
    execute_values(cur, stmt.as_string(cur), chunk)      # page_size defaults to 100
    inserted += cur.rowcount if cur.rowcount >= 0 else len(chunk)
```

The outer chunking at 500 has no effect on this: even a single 500-row chunk is
paged internally into 100s.

## Reproduction

Independent of the API, with psycopg2 directly:

```text
rows supplied          : 250
cur.rowcount reported  : 50
actually in the table  : 250
execute_values defaults: (template=None, page_size=100, fetch=False)
```

### Predicted values

| Rows in file | Reported | Correct |
|---|---|---|
| 99 | 99 | 99 ✓ |
| 100 | 100 | 100 ✓ |
| 117 | 17 | 117 ✗ |
| 250 | 50 | 250 ✗ |
| 500 | 100 | 500 ✗ |

Files of 100 rows or fewer are correct, which is why this survived manual
testing with small samples.

## Blast radius

`inserted` is written to `uploads.csv_files.row_count`:

```python
"INSERT INTO {}.csv_files (..., row_count, ...) VALUES (%s, %s, %s, 'dynamic', %s, %s)",
(file_name, file_hash, table_name, inserted, columns),
```

So the wrong figure is persisted and also appears in `GET /api/csv/files` —
the "Migrated files" list in the UI.

It also breaks the arithmetic the summary implies:
`totalRows == insertedRows + duplicateRowsSkipped + failedRows` fails for any
file over 100 rows.

---

## Fix

Two options, both verified against PostgreSQL 16 including the case where
`ON CONFLICT` legitimately skips rows (250 supplied, 120 already present →
both correctly report 130).

### Option A — one line

```python
execute_values(cur, stmt.as_string(cur), chunk, page_size=len(chunk))
inserted += cur.rowcount if cur.rowcount >= 0 else len(chunk)
```

Forces a single statement per chunk, so `rowcount` covers all of it. Minimal
change, but it depends on `rowcount`'s relationship to paging — the same
subtlety that caused the defect.

### Option B — count what the database returns (recommended)

```python
stmt = sql.SQL(
    "INSERT INTO {}.{} ({}) VALUES %s "
    "ON CONFLICT (_row_hash) DO NOTHING RETURNING 1"
).format(sql.Identifier(schema), sql.Identifier(table_name), insert_cols)

for i in range(0, len(to_insert), 500):
    chunk = to_insert[i : i + 500]
    returned = execute_values(cur, stmt.as_string(cur), chunk, fetch=True)
    inserted += len(returned)
```

Counts rows the database actually inserted, independent of page size. Costs
one integer per inserted row over the wire — negligible at these volumes, and
it cannot silently regress if `page_size` is tuned later.

---

## Regression coverage

The failing test stays as the guard:

```python
def test_a_larger_file_loads_completely(self):
    rows = "\n".join(f"{self.tag},{i}" for i in range(250))
    body = self._upload(f"{self.tag}_bulk.csv", f"col_a,col_b\n{rows}\n")
    self.assertEqual(body["totalRows"], 250)
    self.assertEqual(body["insertedRows"], 250, "all distinct rows should load")
```

250 is deliberately above the 100-row page boundary. A test using fewer than
100 rows would pass against the defect.

Worth adding after the fix: assert the reconciliation invariant on a large
file, since that is what the UI summary depends on.
