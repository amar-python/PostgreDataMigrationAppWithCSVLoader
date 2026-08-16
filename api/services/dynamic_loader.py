"""Dynamic mode: each CSV becomes its own typed table in the uploads schema.

Mirrors the frontend's previous Supabase flow (create_csv_table RPC + upsert):
  - table name derived from content hash: csv_<sha256[:16]>
  - columns typed via whitelist, plus _id / _row_hash / _created_at
  - in-file duplicate rows skipped via _row_hash
All identifiers go through psycopg2.sql.Identifier — no string interpolation.
"""

from __future__ import annotations

import hashlib
import logging
import time

import psycopg2.errors
from psycopg2 import sql
from psycopg2.extras import execute_values

from api.config import settings
from api.db import Conn
from api.services.csv_parse import (
    ALLOWED_TYPES,
    cast_value,
    parse_csv,
    sanitize_columns,
    valid_identifier,
)

logger = logging.getLogger(__name__)

_TYPE_SQL = {
    "int8": "int8",
    "numeric": "numeric",
    "date": "date",
    "timestamptz": "timestamptz",
    "boolean": "boolean",
    "text": "text",
}


def _log(logs: list, step: str, message: str, level: str = "info", count: int | None = None):
    entry = {"ts": int(time.time() * 1000), "step": step, "level": level, "message": message}
    if count is not None:
        entry["count"] = count
    logs.append(entry)


def upload_dynamic(
    file_name: str,
    content: str,
    types: list[str] | None,
    overwrite: bool,
) -> dict:
    logs: list[dict] = []
    _log(logs, "receive", f'Received "{file_name}" ({len(content)} chars)')

    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _log(logs, "hash", f"Computed content hash {file_hash[:12]}…")

    rows = parse_csv(content)
    _log(logs, "parse", f"Parsed {len(rows)} raw rows (including header)", count=len(rows))
    if not rows:
        return {
            "status": "invalid_structure",
            "reason": "empty",
            "message": "This CSV is empty — no header row and no data rows were detected.",
            "logs": logs,
        }
    if len(rows) == 1:
        return {
            "status": "invalid_structure",
            "reason": "header_only",
            "message": "This CSV has a header row but no data rows. Add at least one data row and try again.",
            "logs": logs,
        }
    if all((c or "").strip() == "" for c in rows[0]):
        return {
            "status": "invalid_structure",
            "reason": "no_columns",
            "message": "This CSV's first row is blank, so we can't detect any column headers.",
            "logs": logs,
        }

    # BUG-027 guard: reject files above the configured row cap before doing any
    # per-row work. `rows` includes the header, so subtract one.
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

    schema = settings.UPLOADS_SCHEMA

    try:
        return _do_upload(file_name, types, overwrite, logs, schema, rows, file_hash)
    except psycopg2.Error as exc:
        # Mirror te_loader's structured-error contract: an unexpected DB error
        # (e.g. a column type edge case not caught by cast_value) should not
        # surface as a raw 500 to the frontend.
        logger.warning("Dynamic upload failed for %r: %s", file_name, exc)
        _log(logs, "error", "Database error while loading the CSV", "error")
        return {
            "status": "error",
            "message": "The CSV could not be loaded due to a database error. Check the file's data types and try again.",
            "logs": logs,
        }


def _do_upload(
    file_name: str,
    types: list[str] | None,
    overwrite: bool,
    logs: list[dict],
    schema: str,
    rows: list[list[str]],
    file_hash: str,
) -> dict:
    replaced_file_name: str | None = None
    with Conn() as conn:
        with conn.cursor() as cur:
            # Duplicate FILENAME check
            _log(logs, "duplicate_check", "Checking existing filename")
            cur.execute(
                sql.SQL(
                    "SELECT id, file_name, table_name, file_hash, row_count, mode "
                    "FROM {}.csv_files WHERE file_name = %s"
                ).format(sql.Identifier(schema)),
                (file_name,),
            )
            name_match = cur.fetchone()
            if name_match:
                if not overwrite:
                    _log(logs, "duplicate_check", f"Filename already exists ({name_match[1]})", "warn")
                    return {
                        "status": "duplicate_file",
                        "reason": "content" if name_match[3] == file_hash else "name",
                        "existingFileName": name_match[1],
                        "tableName": name_match[2],
                        "existingRowCount": name_match[4] or 0,
                        "logs": logs,
                    }
                _log(logs, "overwrite", f'Overwriting previous upload "{name_match[1]}"', "warn")
                # table_name is only a bare identifier owned by this schema for
                # dynamic-mode rows (csv_<hash>); TE-mode rows store "schema.table"
                # pointing at a shared T&E table that must never be dropped here.
                # Same guard as te_loader._cleanup_prior_registry_entries.
                if name_match[5] == "dynamic" and name_match[2].startswith("csv_"):
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                            sql.Identifier(schema), sql.Identifier(name_match[2])
                        )
                    )
                cur.execute(
                    sql.SQL("DELETE FROM {}.csv_files WHERE id = %s").format(sql.Identifier(schema)),
                    (name_match[0],),
                )
                replaced_file_name = name_match[1]

            # Duplicate CONTENT check
            _log(logs, "duplicate_check", "Checking existing content hash")
            cur.execute(
                sql.SQL(
                    "SELECT id, file_name, table_name, row_count, mode "
                    "FROM {}.csv_files WHERE file_hash = %s"
                ).format(sql.Identifier(schema)),
                (file_hash,),
            )
            content_match = cur.fetchone()
            if content_match:
                if not overwrite:
                    _log(logs, "duplicate_check", f"Content matches existing file ({content_match[1]})", "warn")
                    return {
                        "status": "duplicate_file",
                        "reason": "content",
                        "existingFileName": content_match[1],
                        "tableName": content_match[2],
                        "existingRowCount": content_match[3] or 0,
                        "logs": logs,
                    }
                _log(logs, "overwrite", f'Overwriting previous content match "{content_match[1]}"', "warn")
                # Same TE-vs-dynamic guard as above.
                if content_match[4] == "dynamic" and content_match[2].startswith("csv_"):
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                            sql.Identifier(schema), sql.Identifier(content_match[2])
                        )
                    )
                cur.execute(
                    sql.SQL("DELETE FROM {}.csv_files WHERE id = %s").format(sql.Identifier(schema)),
                    (content_match[0],),
                )
                replaced_file_name = replaced_file_name or content_match[1]

            # Column validation
            columns = sanitize_columns(rows[0])
            if not columns:
                _log(logs, "error", "No usable column names in header", "error")
                return {"status": "error", "message": "No columns found in the CSV header.", "logs": logs}
            if len(set(columns)) != len(columns):
                dupe = next(c for i, c in enumerate(columns) if columns.index(c) != i)
                msg = f'Duplicate sanitized column name "{dupe}" — rename headers in the CSV.'
                _log(logs, "validate_columns", msg, "error")
                return {"status": "error", "message": msg, "logs": logs}
            if any(not valid_identifier(c) for c in columns):
                _log(logs, "validate_columns", "Sanitized column names invalid", "error")
                return {
                    "status": "error",
                    "message": "Column headers could not be converted to safe identifiers.",
                    "logs": logs,
                }
            _log(logs, "validate_columns", f"Validated {len(columns)} columns", count=len(columns))

            # Types
            if types is not None and len(types) != len(columns):
                msg = f"Provided {len(types)} column types but the CSV has {len(columns)} columns."
                _log(logs, "error", msg, "error")
                return {"status": "error", "message": msg, "logs": logs}
            col_types = types if types else ["text"] * len(columns)
            if any(t not in ALLOWED_TYPES for t in col_types):
                _log(logs, "error", "Unsupported column type provided", "error")
                return {"status": "error", "message": "Unsupported column type provided.", "logs": logs}

            # Create table
            table_name = f"csv_{file_hash[:16]}"
            col_defs = sql.SQL(", ").join(
                sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(_TYPE_SQL[t]))
                for c, t in zip(columns, col_types)
            )
            _log(logs, "create_table", f"create table {table_name} ({len(columns)} cols)")
            cur.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {}.{} "
                    "(_id BIGSERIAL PRIMARY KEY, {}, _row_hash TEXT NOT NULL UNIQUE, "
                    "_created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                ).format(sql.Identifier(schema), sql.Identifier(table_name), col_defs)
            )

            # Cast rows
            data_rows = rows[1:]
            seen: set[str] = set()
            to_insert: list[tuple] = []
            row_errors: list[dict] = []
            failed_row_count = 0
            duplicates = 0

            for r, raw in enumerate(data_rows):
                row_number = r + 1
                values: list = []
                raw_joined: list[str] = []
                failed = False
                for c in range(len(columns)):
                    cell = raw[c] if c < len(raw) else ""
                    raw_joined.append(cell)
                    ok, val, reason = cast_value(cell, col_types[c])
                    if not ok:
                        # BUG-027: cap row_errors so a pathological file doesn't
                        # produce a 200MB JSON response. Summary count still
                        # reflects the true failure count via failed_row_count.
                        if len(row_errors) < settings.MAX_ROW_ERRORS_REPORTED:
                            row_errors.append(
                                {"rowNumber": row_number, "column": columns[c], "value": cell, "reason": reason}
                            )
                        failed = True
                        failed_row_count += 1
                        break
                    values.append(val)
                if failed:
                    continue
                # BUG-022: ASCII unit separator (U+001F) between cells prevents
                # ["ab","cd"] and ["a","bcd"] from hashing to the same value.
                row_hash = hashlib.sha256(
                    "\x1f".join(raw_joined).encode("utf-8")
                ).hexdigest()
                if row_hash in seen:
                    duplicates += 1
                    continue
                seen.add(row_hash)
                to_insert.append(tuple(values) + (row_hash,))

            _log(
                logs,
                "cast_rows",
                f"Cast {len(data_rows)} rows → {len(to_insert)} valid, {failed_row_count} errors, {duplicates} in-file duplicates",
                "warn" if failed_row_count else "info",
                count=len(to_insert),
            )

            # Insert
            inserted = 0
            if to_insert:
                insert_cols = sql.SQL(", ").join(
                    [sql.Identifier(c) for c in columns] + [sql.Identifier("_row_hash")]
                )
                # RETURNING + fetch=True is deliberate: execute_values pages at 100
                # by default and cur.rowcount reflects only the last page, which
                # under-counted every file over 100 rows. Counting returned rows is
                # page-size independent. See docs/DEFECT_INSERTED_ROWS.md.
                stmt = sql.SQL(
                    "INSERT INTO {}.{} ({}) VALUES %s "
                    "ON CONFLICT (_row_hash) DO NOTHING RETURNING 1"
                ).format(sql.Identifier(schema), sql.Identifier(table_name), insert_cols)
                for i in range(0, len(to_insert), 500):
                    chunk = to_insert[i : i + 500]
                    returned = execute_values(
                        cur, stmt.as_string(cur), chunk, fetch=True)
                    inserted += len(returned)
            _log(logs, "insert", f"Inserted {inserted} rows", count=inserted)

            # Register. The duplicate checks above are racy (check-then-act, no
            # lock held across the row-casting work), so a concurrent identical
            # upload can slip past them; the registry's UNIQUE indexes are the
            # real guard, and we turn a violation here into the same
            # structured "duplicate_file" response the earlier check returns.
            _log(logs, "register", "Registering file in csv_files")
            try:
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names) "
                        "VALUES (%s, %s, %s, 'dynamic', %s, %s) RETURNING id"
                    ).format(sql.Identifier(schema)),
                    (file_name, file_hash, table_name, inserted, columns),
                )
                file_id = cur.fetchone()[0]
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                cur.execute(
                    sql.SQL(
                        "SELECT file_name, table_name, row_count FROM {}.csv_files "
                        "WHERE file_name = %s OR file_hash = %s"
                    ).format(sql.Identifier(schema)),
                    (file_name, file_hash),
                )
                existing = cur.fetchone()
                _log(logs, "duplicate_check", "Lost race to a concurrent identical upload", "warn")
                return {
                    "status": "duplicate_file",
                    "reason": "content" if existing and existing[0] != file_name else "name",
                    "existingFileName": existing[0] if existing else file_name,
                    "tableName": existing[1] if existing else table_name,
                    "existingRowCount": (existing[2] or 0) if existing else 0,
                    "logs": logs,
                }

        conn.commit()

    _log(logs, "done", f"Import complete for {file_name}")
    return {
        "status": "ok",
        "fileId": str(file_id),
        "tableName": table_name,
        "totalRows": len(data_rows),
        "insertedRows": inserted,
        "duplicateRowsSkipped": duplicates,
        "failedRows": failed_row_count,
        "columns": columns,
        "types": col_types,
        "rowErrors": row_errors,
        "logs": logs,
        "overwritten": replaced_file_name is not None,
        "replacedFileName": replaced_file_name,
    }
