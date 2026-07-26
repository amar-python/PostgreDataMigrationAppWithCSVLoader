"""Dynamic mode: each CSV becomes its own typed table in the uploads schema.

Mirrors the frontend's previous Supabase flow (create_csv_table RPC + upsert):
  - table name derived from content hash: csv_<sha256[:16]>
  - columns typed via whitelist, plus _id / _row_hash / _created_at
  - in-file duplicate rows skipped via _row_hash
All identifiers go through psycopg2.sql.Identifier — no string interpolation.
"""

from __future__ import annotations

import hashlib
import json
import time

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

    schema = settings.UPLOADS_SCHEMA
    replaced_file_name: str | None = None

    with Conn() as conn:
        with conn.cursor() as cur:
            # Duplicate FILENAME check
            _log(logs, "duplicate_check", "Checking existing filename")
            cur.execute(
                sql.SQL(
                    "SELECT id, file_name, table_name, file_hash, row_count FROM {}.csv_files WHERE file_name = %s"
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
                    "SELECT id, file_name, table_name, row_count FROM {}.csv_files WHERE file_hash = %s"
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
                _log(logs, "error", "Mismatched column types length", "error")
                return {
                    "status": "error",
                    "message": "The number of provided column types does not match the number of columns.",
                    "logs": logs,
                }
            if types is not None:
                col_types = types
            else:
                col_types = ["text"] * len(columns)
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
                        row_errors.append(
                            {"rowNumber": row_number, "column": columns[c], "value": cell, "reason": reason}
                        )
                        failed = True
                        break
                    values.append(val)
                if failed:
                    continue
                row_hash = hashlib.sha256(
                    json.dumps(
                        raw_joined,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=False,
                    ).encode("utf-8")
                ).hexdigest()
                if row_hash in seen:
                    duplicates += 1
                    continue
                seen.add(row_hash)
                to_insert.append(tuple(values) + (row_hash,))

            _log(
                logs,
                "cast_rows",
                (
                    f"Cast {len(data_rows)} rows → {len(to_insert)} valid, "
                    f"{len(row_errors)} errors, {duplicates} in-file duplicates"
                ),
                "warn" if row_errors else "info",
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
                # page-size independent. See DEFECT_INSERTED_ROWS.md.
                stmt = sql.SQL(
                    "INSERT INTO {}.{} ({}) VALUES %s "
                    "ON CONFLICT (_row_hash) DO NOTHING RETURNING 1"
                ).format(sql.Identifier(schema), sql.Identifier(table_name), insert_cols)
                for i in range(0, len(to_insert), 500):
                    chunk = to_insert[i:i + 500]
                    returned = execute_values(
                        cur, stmt.as_string(cur), chunk, fetch=True)
                    inserted += len(returned)
            _log(logs, "insert", f"Inserted {inserted} rows", count=inserted)

            # Register
            _log(logs, "register", "Registering file in csv_files")
            cur.execute(
                sql.SQL(
                    "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names) "
                    "VALUES (%s, %s, %s, 'dynamic', %s, %s) RETURNING id"
                ).format(sql.Identifier(schema)),
                (file_name, file_hash, table_name, inserted, columns),
            )
            file_id = cur.fetchone()[0]

        conn.commit()

    _log(logs, "done", f"Import complete for {file_name}")
    return {
        "status": "ok",
        "fileId": str(file_id),
        "tableName": table_name,
        "totalRows": len(data_rows),
        "insertedRows": inserted,
        "duplicateRowsSkipped": duplicates,
        "failedRows": len(row_errors),
        "columns": columns,
        "types": col_types,
        "rowErrors": row_errors,
        "logs": logs,
        "overwritten": replaced_file_name is not None,
        "replacedFileName": replaced_file_name,
    }
