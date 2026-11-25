"""Pieces both CSV loaders share (#330): logging, capped row errors, the row-cap and rows-failed responses,
batch insert with a per-row fallback, and the "ok" result.

dynamic_loader.py and te_loader.py used to carry their own copy of each. Nothing here opens a connection or reads a
table name from the request, so each piece is unit-tested without a database (tests/unit/test_load_common.py).
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from psycopg2 import sql
from psycopg2.extras import execute_values

from api.config import settings
from api.services.csv_parse import extra_cells, ragged_row_reason


def log(logs: list, step: str, message: str, level: str = "info", count: int | None = None) -> None:
    """Append one entry to an upload's log, the list the response carries as ``logs``."""
    entry: dict = {"ts": int(time.time() * 1000), "step": step, "level": level, "message": message}
    if count is not None:
        entry["count"] = count
    logs.append(entry)


class RowErrors:
    """The failing rows of one load: every failure is counted, the first ``MAX_ROW_ERRORS_REPORTED`` are kept.

    BUG-027 / BUG-039: the cap keeps a wholly broken file from producing a huge response, while ``failed`` stays the
    true count, which is what the response's ``failedRows`` reports.
    """

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.failed = 0

    def add(self, row_number: int, column: str, value: str, reason: str | None) -> None:
        self.failed += 1
        if len(self.items) < settings.MAX_ROW_ERRORS_REPORTED:
            self.items.append({"rowNumber": row_number, "column": column, "value": value, "reason": reason})

    def add_db_error(self, row_number: int, reason: str) -> None:
        """A row the database refused (constraint, cast): there is no single column to name."""
        self.failed += 1
        if len(self.items) < settings.MAX_ROW_ERRORS_REPORTED:
            self.items.append({"rowNumber": row_number, "reason": reason})

    def first(self) -> dict | None:
        return self.items[0] if self.items else None


def ragged(raw: list[str], width: int, row_number: int, errors: RowErrors) -> bool:
    """Record a row with cells beyond the header (#203). True if it was one, and so must be skipped."""
    extra = extra_cells(raw, width)
    if not extra:
        return False
    errors.add(row_number, "(beyond header)", extra[0], ragged_row_reason(raw, width))
    return True


def too_many_rows(data_row_count: int, logs: list) -> dict | None:
    """BUG-027: the error response for a file over ``API_MAX_ROWS`` data rows, or None if it is within the cap."""
    if data_row_count <= settings.MAX_ROWS:
        return None
    log(logs, "error", f"CSV has {data_row_count} data rows; max allowed is {settings.MAX_ROWS}.", "error")
    return {
        "status": "error",
        "message": (
            f"CSV has {data_row_count} data rows, but the API is configured to "
            f"accept at most {settings.MAX_ROWS}. Split the file or raise API_MAX_ROWS."
        ),
        "logs": logs,
    }


def rows_failed(message: str, errors: RowErrors, total_rows: int, logs: list, **fields: object) -> dict:
    """The response when rows failed and nothing was saved (#123, #170, #289). ``fields`` follow ``failedRows``."""
    log(logs, "error", message, "error")
    return {"status": "error", "message": message, "rowErrors": errors.items,
            "totalRows": total_rows, "failedRows": errors.failed, **fields, "logs": logs}


def insert_with_row_fallback(cur, batch_stmt: sql.Composable, row_stmt: sql.Composable,
                             rows: Sequence[tuple[int, list]], errors: RowErrors, chunk_size: int = 500) -> int:
    """Insert ``(row number, values)`` pairs in batches; when a batch fails, retry it a row at a time.

    A constraint (FK, UNIQUE, CHECK) or a cast the database makes itself fails the whole batch, so the batch is
    rolled back to its savepoint and each row is tried under a savepoint of its own: the rows that fail are
    recorded in ``errors`` and the rest go in. Returns how many rows were inserted.
    """
    inserted = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        cur.execute("SAVEPOINT chunk_sp")
        try:
            execute_values(cur, batch_stmt.as_string(cur), [v for _, v in chunk])
            cur.execute("RELEASE SAVEPOINT chunk_sp")
            inserted += len(chunk)
        except Exception:  # noqa: BLE001 — DB-level constraint: retry per-row
            cur.execute("ROLLBACK TO SAVEPOINT chunk_sp")
            cur.execute("RELEASE SAVEPOINT chunk_sp")
            inserted += _insert_one_by_one(cur, row_stmt, chunk, errors)
    return inserted


def _insert_one_by_one(cur, row_stmt: sql.Composable, chunk: Sequence[tuple[int, list]], errors: RowErrors) -> int:
    inserted = 0
    for row_number, values in chunk:
        cur.execute("SAVEPOINT row_sp")
        try:
            cur.execute(row_stmt, values)
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT row_sp")
            errors.add_db_error(row_number, str(exc).split("\n")[0])
        finally:
            cur.execute("RELEASE SAVEPOINT row_sp")
    return inserted


def ok_result(file_id: object, table_name: str, total_rows: int, inserted: int, duplicates: int, failed: int,
              columns: list[str], types: list[str], **fields: object) -> dict:
    """The "ok" response of a load. ``fields`` follow ``types``, in the order given."""
    return {"status": "ok", "fileId": str(file_id), "tableName": table_name, "totalRows": total_rows,
            "insertedRows": inserted, "duplicateRowsSkipped": duplicates, "failedRows": failed,
            "columns": columns, "types": types, **fields}
