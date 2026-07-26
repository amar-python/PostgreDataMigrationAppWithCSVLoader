"""T&E mode: load a CSV into one of the 12 fixed T&E tables (te_dev schema).

The CSV's sanitized headers must all be existing columns of the target table.
Casting is delegated to PostgreSQL: each row inserts inside a savepoint so a
bad row rolls back alone and is reported, without aborting the batch.
"""

from __future__ import annotations

import hashlib
import re
import time

from psycopg2 import sql

from api.config import TE_TABLES, settings
from api.db import Conn
from api.services.csv_parse import parse_csv, sanitize_columns

_DYNAMIC_TABLE_NAME_RE = re.compile(r"^csv_[0-9a-f]{16}$")


def _log(logs: list, step: str, message: str, level: str = "info", count: int | None = None):
    entry = {"ts": int(time.time() * 1000), "step": step, "level": level, "message": message}
    if count is not None:
        entry["count"] = count
    logs.append(entry)


def te_table_columns(table: str) -> list[str]:
    """Column names of a T&E table."""
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


def match_te_table(columns: list[str]) -> str | None:
    """Best-effort match: the T&E table whose column set contains all CSV columns."""
    for table in TE_TABLES:
        te_cols = set(te_table_columns(table))
        if te_cols and set(columns).issubset(te_cols):
            return table
    return None


def _drop_dynamic_upload_table(cur, table_name: str) -> None:
    if _DYNAMIC_TABLE_NAME_RE.fullmatch(table_name):
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                sql.Identifier(settings.UPLOADS_SCHEMA), sql.Identifier(table_name)
            )
        )


def _cleanup_prior_registry_entries(cur, file_name: str, file_hash: str) -> None:
    cur.execute(
        sql.SQL(
            "SELECT table_name, mode FROM {}.csv_files WHERE file_name = %s OR file_hash = %s"
        ).format(sql.Identifier(settings.UPLOADS_SCHEMA)),
        (file_name, file_hash),
    )
    for table_name, mode in cur.fetchall():
        if mode == "dynamic":
            _drop_dynamic_upload_table(cur, table_name)
    cur.execute(
        sql.SQL("DELETE FROM {}.csv_files WHERE file_name = %s OR file_hash = %s").format(
            sql.Identifier(settings.UPLOADS_SCHEMA)
        ),
        (file_name, file_hash),
    )


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

    with Conn() as conn:
        with conn.cursor() as cur:
            for r, raw in enumerate(data_rows):
                row_number = r + 1
                values = [
                    (raw[c].strip() if c < len(raw) and raw[c].strip() != "" else None)
                    for c in range(len(columns))
                ]
                cur.execute("SAVEPOINT row_sp")
                try:
                    cur.execute(insert_stmt, values)
                    inserted += 1
                except Exception as exc:  # noqa: BLE001 — report DB cast/constraint errors per row
                    cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                    row_errors.append(
                        {
                            "rowNumber": row_number,
                            "reason": str(exc).split("\n")[0],
                        }
                    )
                finally:
                    cur.execute("RELEASE SAVEPOINT row_sp")

            # Register the load in the shared registry (mode='te')
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            # T&E loads may be re-run; clear any prior registry entry for this
            # file name or identical content before re-registering.
            _cleanup_prior_registry_entries(cur, file_name, file_hash)
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
        "failedRows": len(row_errors),
        "columns": columns,
        "types": [],
        "rowErrors": row_errors,
        "logs": logs,
    }
