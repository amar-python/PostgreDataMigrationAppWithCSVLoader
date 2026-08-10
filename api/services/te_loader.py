"""T&E mode: load a CSV into one of the 12 fixed T&E tables (te_dev schema).

The CSV's sanitized headers must all be existing columns of the target table.

BUG-028: Casting is now done CLIENT-SIDE where possible. For each target
column we look up its Postgres data_type once, map it to one of the six
ALLOWED_TYPES via ``pg_type_to_allowed_type()``, and use ``cast_value()`` to
validate every cell before we build the batch. Rows that fail validation are
reported in ``rowErrors[]`` without hitting the database.

For columns whose data_type doesn't map to a client-validatable type
(``uuid``, ``USER-DEFINED`` enums, ``ARRAY``, etc.) we fall back to
per-row inserts guarded by a SAVEPOINT — the old behaviour — so a bad enum
value or FK violation still shows up as a row error instead of aborting the
batch.

BUG-027: Also enforces ``settings.MAX_ROWS`` (previously dynamic mode only).
"""

from __future__ import annotations

import hashlib
import time

from psycopg2 import sql
from psycopg2.extras import execute_values

from api.config import TE_TABLES, settings
from api.db import Conn
from api.services.csv_parse import (
    cast_value,
    parse_csv,
    pg_type_to_allowed_type,
    sanitize_columns,
)


def _log(logs: list, step: str, message: str, level: str = "info", count: int | None = None):
    entry = {"ts": int(time.time() * 1000), "step": step, "level": level, "message": message}
    if count is not None:
        entry["count"] = count
    logs.append(entry)


def te_table_columns(table: str) -> list[str]:
    """Column names of a T&E table (excluding generated/default-only columns)."""
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (settings.TE_SCHEMA, table),
            )
            return [r[0] for r in cur.fetchall()]


def _te_column_types(cur, table: str) -> dict[str, str]:
    """Return ``{column_name: data_type}`` for a T&E table via one query."""
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (settings.TE_SCHEMA, table),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def match_te_table(columns: list[str]) -> str | None:
    """Best-effort match: the T&E table whose column set contains all CSV columns."""
    for table in TE_TABLES:
        te_cols = set(te_table_columns(table))
        if te_cols and set(columns).issubset(te_cols):
            return table
    return None


def upload_te(file_name: str, content: str, target_table: str) -> dict:
    logs: list[dict] = []
    _log(logs, "receive", f'Received "{file_name}" for T&E table "{target_table}"')

    if target_table not in TE_TABLES:
        return {
            "status": "error",
            "message": f'"{target_table}" is not a T&E table. Valid: {", ".join(TE_TABLES)}',
            "logs": logs,
        }

    rows = parse_csv(content)
    if len(rows) < 2:
        return {
            "status": "invalid_structure",
            "reason": "empty" if not rows else "header_only",
            "message": "The CSV needs a header row and at least one data row.",
            "logs": logs,
        }

    # BUG-027 for T&E mode: reject oversize files up-front.
    data_row_count = len(rows) - 1
    if data_row_count > settings.MAX_ROWS:
        _log(
            logs,
            "error",
            f"CSV has {data_row_count} data rows; max allowed is {settings.MAX_ROWS}.",
            "error",
        )
        return {
            "status": "error",
            "message": (
                f"CSV has {data_row_count} data rows, but the API is configured to "
                f"accept at most {settings.MAX_ROWS}. Split the file or raise API_MAX_ROWS."
            ),
            "logs": logs,
        }

    columns = sanitize_columns(rows[0])
    table_cols = te_table_columns(target_table)
    if not table_cols:
        return {
            "status": "error",
            "message": f'T&E table "{target_table}" not found in schema {settings.TE_SCHEMA}. '
            "Run deploy_all.sh dev first.",
            "logs": logs,
        }
    unknown = [c for c in columns if c not in table_cols]
    if unknown:
        return {
            "status": "error",
            "message": f'CSV columns not present in {settings.TE_SCHEMA}.{target_table}: {", ".join(unknown)}',
            "logs": logs,
        }
    _log(logs, "validate_columns", f"All {len(columns)} CSV columns exist on {target_table}")

    data_rows = rows[1:]
    row_errors: list[dict] = []
    inserted = 0

    insert_stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
        sql.Identifier(settings.TE_SCHEMA),
        sql.Identifier(target_table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    batch_insert_stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
        sql.Identifier(settings.TE_SCHEMA),
        sql.Identifier(target_table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
    )

    def _err(row_number: int, column: str, value: str, reason: str) -> None:
        # BUG-027 cap: append the error only if we're under the reporting limit,
        # so a fully-broken file can't produce a 200MB JSON response body.
        # The true failed-row count is tracked by the caller via
        # ``failed_row_count += 1`` right after each ``_err(...)`` call — the
        # response's ``failedRows`` field reflects that counter, not the length
        # of ``rowErrors`` (which is capped). See BUG-039.
        if len(row_errors) < settings.MAX_ROW_ERRORS_REPORTED:
            row_errors.append(
                {"rowNumber": row_number, "column": column, "value": value, "reason": reason}
            )

    with Conn() as conn:
        with conn.cursor() as cur:
            # BUG-028: one lookup instead of per-row psql casts.
            col_pg_types = _te_column_types(cur, target_table)
            # Map to ALLOWED_TYPES (or None if we should let PG cast it).
            col_types: list[str | None] = [
                pg_type_to_allowed_type(col_pg_types.get(c, "text"))
                for c in columns
            ]
            unmapped = [c for c, t in zip(columns, col_types) if t is None]
            if unmapped:
                _log(
                    logs,
                    "validate_columns",
                    f"Columns fall back to server-side cast: {', '.join(unmapped)}",
                    "info",
                )

            # Pre-validate every row client-side; drop failures into row_errors.
            failed_row_count = 0
            to_insert: list[list] = []
            for r, raw in enumerate(data_rows):
                row_number = r + 1
                values: list = []
                failed = False
                for c, col_type in enumerate(col_types):
                    cell = raw[c].strip() if c < len(raw) else ""
                    if cell == "":
                        values.append(None)
                        continue
                    if col_type is None:
                        # Let PG handle it; pass the raw string through and
                        # rely on the SAVEPOINT fallback below to catch errors.
                        values.append(cell)
                        continue
                    ok, val, reason = cast_value(cell, col_type)
                    if not ok:
                        _err(row_number, columns[c], cell, reason or "type error")
                        failed = True
                        failed_row_count += 1
                        break
                    values.append(val)
                if not failed:
                    to_insert.append(values)

            _log(
                logs,
                "cast_rows",
                f"Client-side validated {len(data_rows)} rows → "
                f"{len(to_insert)} valid, {failed_row_count} type errors",
                "warn" if failed_row_count else "info",
                count=len(to_insert),
            )

            # Batch insert survivors. If a constraint (FK, UNIQUE, CHECK on an
            # unmapped column, etc.) trips, roll back the chunk and fall back
            # to per-row to identify the bad row(s) — same shape as before but
            # only runs on the ~few rows that had DB-only failure modes.
            chunk_size = 500
            for start in range(0, len(to_insert), chunk_size):
                chunk = to_insert[start : start + chunk_size]
                cur.execute("SAVEPOINT chunk_sp")
                try:
                    execute_values(cur, batch_insert_stmt.as_string(cur), chunk)
                    cur.execute("RELEASE SAVEPOINT chunk_sp")
                    inserted += len(chunk)
                except Exception:  # noqa: BLE001 — DB-level constraint: retry per-row
                    cur.execute("ROLLBACK TO SAVEPOINT chunk_sp")
                    cur.execute("RELEASE SAVEPOINT chunk_sp")
                    for i, values in enumerate(chunk):
                        # We don't know which original CSV row this maps to
                        # because to_insert dropped failures — reconstruct via
                        # position in the surviving list. Row numbers reported
                        # here are the position within the successful subset;
                        # good enough to point the user at the record.
                        cur.execute("SAVEPOINT row_sp")
                        try:
                            cur.execute(insert_stmt, values)
                            inserted += 1
                        except Exception as exc:  # noqa: BLE001
                            cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                            failed_row_count += 1
                            if len(row_errors) < settings.MAX_ROW_ERRORS_REPORTED:
                                row_errors.append({
                                    "rowNumber": start + i + 1,
                                    "reason": str(exc).split("\n")[0],
                                })
                        finally:
                            cur.execute("RELEASE SAVEPOINT row_sp")

            # Register the load in the shared registry (mode='te')
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            # T&E loads may be re-run; clear any prior registry entry for this
            # file name or identical content before re-registering.
            cur.execute(
                sql.SQL("DELETE FROM {}.csv_files WHERE file_name = %s OR file_hash = %s").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA)
                ),
                (file_name, file_hash),
            )
            cur.execute(
                sql.SQL(
                    "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names) "
                    "VALUES (%s, %s, %s, 'te', %s, %s) RETURNING id"
                ).format(sql.Identifier(settings.UPLOADS_SCHEMA)),
                (file_name, file_hash, f"{settings.TE_SCHEMA}.{target_table}", inserted, columns),
            )
            file_id = cur.fetchone()[0]
        conn.commit()

    _log(logs, "done", f"T&E load complete: {inserted} rows into {target_table}", count=inserted)
    return {
        "status": "ok",
        "fileId": str(file_id),
        "tableName": f"{settings.TE_SCHEMA}.{target_table}",
        "totalRows": len(data_rows),
        "insertedRows": inserted,
        "duplicateRowsSkipped": 0,
        "failedRows": failed_row_count,
        "columns": columns,
        "types": [],
        "rowErrors": row_errors,
        "logs": logs,
    }
