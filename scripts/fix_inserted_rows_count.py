#!/usr/bin/env python3
"""Fix the `insertedRows` under-count in api/services/dynamic_loader.py.

The defect
----------
``psycopg2.extras.execute_values`` defaults to ``page_size=100`` and issues one
INSERT per page. ``cursor.rowcount`` reflects only the **last** statement, so a
250-row upload reports 50. Files of 100 rows or fewer are correct, which is why
this survived manual testing.

See DEFECT_INSERTED_ROWS.md for the full analysis and reproduction.

The fix
-------
Add ``RETURNING 1`` and use ``fetch=True``, then count the rows the database
actually returned. This is independent of page size, so it cannot silently
regress if paging is tuned later. It also stays correct when
``ON CONFLICT DO NOTHING`` legitimately skips rows.

Run from the repository root::

    python scripts/fix_inserted_rows_count.py --dry-run   # preview
    python scripts/fix_inserted_rows_count.py             # apply

Then verify::

    python -m pytest tests/test_issue_04_multi_file_upload.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "api" / "services" / "dynamic_loader.py"

OLD_STMT = '''                stmt = sql.SQL(
                    "INSERT INTO {}.{} ({}) VALUES %s ON CONFLICT (_row_hash) DO NOTHING"
                ).format(sql.Identifier(schema), sql.Identifier(table_name), insert_cols)'''

NEW_STMT = '''                # RETURNING + fetch=True is deliberate: execute_values pages at 100
                # by default and cur.rowcount reflects only the last page, which
                # under-counted every file over 100 rows. Counting returned rows is
                # page-size independent. See DEFECT_INSERTED_ROWS.md.
                stmt = sql.SQL(
                    "INSERT INTO {}.{} ({}) VALUES %s "
                    "ON CONFLICT (_row_hash) DO NOTHING RETURNING 1"
                ).format(sql.Identifier(schema), sql.Identifier(table_name), insert_cols)'''

OLD_LOOP = '''                for i in range(0, len(to_insert), 500):
                    chunk = to_insert[i : i + 500]
                    execute_values(cur, stmt.as_string(cur), chunk)
                    inserted += cur.rowcount if cur.rowcount >= 0 else len(chunk)'''

NEW_LOOP = '''                for i in range(0, len(to_insert), 500):
                    chunk = to_insert[i : i + 500]
                    returned = execute_values(
                        cur, stmt.as_string(cur), chunk, fetch=True)
                    inserted += len(returned)'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change without writing")
    args = ap.parse_args()

    if not TARGET.exists():
        print(f"error: {TARGET} not found — run this from the repository root")
        return 2

    text = TARGET.read_text(encoding="utf-8")

    if "RETURNING 1" in text and "fetch=True" in text:
        print("  already fixed — nothing to do")
        return 0

    missing = [name for name, snippet in
               (("INSERT statement", OLD_STMT), ("insert loop", OLD_LOOP))
               if snippet not in text]
    if missing:
        print("error: could not locate the expected code:")
        for name in missing:
            print(f"  - {name}")
        print("\nThe file may have been edited since this script was written.")
        print("Apply the change by hand using DEFECT_INSERTED_ROWS.md.")
        return 1

    updated = text.replace(OLD_STMT, NEW_STMT, 1).replace(OLD_LOOP, NEW_LOOP, 1)

    if args.dry_run:
        print("  would rewrite api/services/dynamic_loader.py:\n")
        print("  --- INSERT statement: add RETURNING 1")
        print("  --- insert loop:      fetch=True, count returned rows")
        print("\n  Re-run without --dry-run to apply.")
        return 0

    TARGET.write_text(updated, encoding="utf-8")
    print("  rewrote api/services/dynamic_loader.py")
    print("\nNow verify:")
    print("  python -m pytest tests/test_issue_04_multi_file_upload.py")
    print("  python -m pytest tests/test_issue_05_import_summary.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
