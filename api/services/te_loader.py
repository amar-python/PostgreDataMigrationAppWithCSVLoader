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

#289 (M0 decision 4, "partial imports are not permitted"): the load is all or nothing. If any row fails,
whether at the client-side check or in the database, the whole load is rolled back and the response is an
``error`` listing every failing row (``rowErrors``, capped) with ``insertedRows`` 0. The savepoints are kept
only so that one upload can report all the bad rows at once.

BUG-027: Also enforces ``settings.MAX_ROWS`` (previously dynamic mode only).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import psycopg2.errors
from psycopg2 import sql
from psycopg2.extensions import connection, cursor

from api.config import TE_TABLES
from api.db import Conn, fetch_one
from api.services.csv_parse import (
    cast_value,
    parse_csv,
    pg_type_to_allowed_type,
    sanitize_columns,
)
from api.services.destructive_ops import _require_delete
from api.services.load_common import (
    RowErrors,
    insert_with_row_fallback,
    ok_result,
    ragged,
    rows_failed,
    too_many_rows,
)
from api.services.load_common import log as _log
from api.services.results import LoadResult, LogEntry, RowError
from api.tenancy import te_schema, uploads_schema


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
                (te_schema(), table),
            )
            return [r[0] for r in cur.fetchall()]


def _te_column_types(cur: cursor, table: str) -> dict[str, str]:
    """Return ``{column_name: data_type}`` for a T&E table via one query."""
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (te_schema(), table),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def match_te_table(columns: list[str]) -> str | None:
    """Best-effort match: the T&E table whose column set contains all CSV columns."""
    for table in TE_TABLES:
        te_cols = set(te_table_columns(table))
        if te_cols and set(columns).issubset(te_cols):
            return table
    return None


def _cleanup_prior_registry_entries(cur: cursor, file_name: str, file_hash: str) -> None:
    """Remove prior T&E registry entries for this file. Uses sql.Identifier, no f-strings.

    Only non-dynamic entries are ever removed, and no table is dropped: a T&E entry
    points at a shared T&E table whose rows stay. Dynamic uploads are versions of a
    dataset (M5, decision 2) and are never replaced from the T&E path, whether they
    match by name or by identical content (#287, BR-51); ``upload_te`` refuses an
    upload whose content is already a dynamic dataset before reaching here.
    """
    cur.execute(
        sql.SQL("DELETE FROM {s}.csv_files WHERE mode <> 'dynamic' AND (file_name = %s OR file_hash = %s)").format(
            s=sql.Identifier(uploads_schema())
        ),
        (file_name, file_hash),
    )


def upload_te(
    file_name: str,
    content: str,
    target_table: str,
    *,
    session: dict[str, Any] | None = None,
    on_commit: Callable[[cursor, LoadResult], None] | None = None,
) -> LoadResult:
    """Load ``content`` into a T&E table.

    ``on_commit(cur, result)`` runs on the load's cursor just before the commit, given the "ok" result
    this call will return. Whatever it writes commits with the load. If it raises, the load rolls back
    and the exception propagates (#288).
    """
    logs: list[LogEntry] = []
    _log(logs, "receive", f'Received "{file_name}" for T&E table "{target_table}"')
    checked = _check_file(content, target_table, logs)
    if isinstance(checked, dict):
        return checked
    rows, columns = checked
    data_rows = rows[1:]
    errors = RowErrors()
    batch_insert_stmt, insert_stmt = _insert_statements(target_table, columns)

    with Conn() as conn:
        with conn.cursor() as cur:
            col_types = _cast_types(cur, target_table, columns, logs)

            # A re-upload overwrites the earlier load, so it needs delete permission
            # up front. The cleanup itself waits until a row has actually landed
            # (#170, #215): a re-upload that fails every row must change nothing.
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            refused = _check_earlier_loads(cur, file_name, file_hash, session, logs)
            if refused:
                return refused

            # Pre-validate every row client-side; drop failures into row errors.
            to_insert = cast_te_rows(data_rows, columns, col_types, errors)
            _log(
                logs,
                "cast_rows",
                f"Client-side validated {len(data_rows)} rows → {len(to_insert)} valid, {errors.failed} type errors",
                "warn" if errors.failed else "info",
                count=len(to_insert),
            )

            # Batch insert survivors. If a constraint (FK, UNIQUE, CHECK on an
            # unmapped column, etc.) trips, roll back the chunk and fall back
            # to per-row to identify the bad row(s).
            inserted = insert_with_row_fallback(cur, batch_insert_stmt, insert_stmt, to_insert, errors)

            # #170, #289: all or nothing (M0 decision 4: partial imports are not permitted). If any row
            # failed, at the client-side type check or in the database, nothing is migrated: roll back and
            # preserve any prior load rather than cleaning it up. The per-row savepoints stay, because
            # they are what lets one upload report every bad row instead of only the first.
            if data_rows and (inserted == 0 or errors.failed > 0):
                conn.rollback()
                return _not_imported(errors, len(data_rows), target_table, columns, logs)

            # Register the load in the shared registry (mode='te'), replacing any
            # earlier entry for this file. Only reached once a row has landed.
            _cleanup_prior_registry_entries(cur, file_name, file_hash)
            file_id = _register(
                conn, cur, file_name, file_hash, target_table, inserted, columns, len(data_rows), errors.failed, logs
            )
            if isinstance(file_id, dict):
                return file_id
            _log(logs, "done", f"T&E load complete: {inserted} rows into {target_table}", count=inserted)
            result = _ok_result(
                file_id, target_table, data_rows, inserted, errors.failed, columns, col_types, errors.items, logs
            )
            if on_commit is not None:
                on_commit(cur, result)
        conn.commit()
    return result


def _check_file(
    content: str, target_table: str, logs: list[LogEntry]
) -> tuple[list[list[str]], list[str]] | LoadResult:
    """The parsed rows and sanitized columns, or the error response if the file cannot load into ``target_table``.

    The CSV's sanitized headers must all be existing columns of the target table.
    """
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
    refused = too_many_rows(len(rows) - 1, logs)
    if refused:
        return refused

    columns = sanitize_columns(rows[0])
    table_cols = te_table_columns(target_table)
    if not table_cols:
        return {
            "status": "error",
            "message": f'T&E table "{target_table}" not found in schema {te_schema()}. Run deploy_all.sh dev first.',
            "logs": logs,
        }
    unknown = [c for c in columns if c not in table_cols]
    if unknown:
        return {
            "status": "error",
            "message": f"CSV columns not present in {te_schema()}.{target_table}: {', '.join(unknown)}",
            "logs": logs,
        }
    _log(logs, "validate_columns", f"All {len(columns)} CSV columns exist on {target_table}")
    return rows, columns


def _insert_statements(target_table: str, columns: list[str]) -> tuple[sql.Composed, sql.Composed]:
    """The batch INSERT (``VALUES %s``, for execute_values) and the one-row INSERT the fallback uses."""
    batch_insert_stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
        sql.Identifier(te_schema()),
        sql.Identifier(target_table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
    )
    insert_stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
        sql.Identifier(te_schema()),
        sql.Identifier(target_table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    return batch_insert_stmt, insert_stmt


def _cast_types(cur: cursor, target_table: str, columns: list[str], logs: list[LogEntry]) -> list[str | None]:
    """BUG-028: each column's type to validate against, from one lookup; None where Postgres must cast it."""
    col_pg_types = _te_column_types(cur, target_table)
    col_types: list[str | None] = [pg_type_to_allowed_type(col_pg_types.get(c, "text")) for c in columns]
    unmapped = [c for c, t in zip(columns, col_types) if t is None]
    if unmapped:
        _log(
            logs,
            "validate_columns",
            f"Columns fall back to server-side cast: {', '.join(unmapped)}",
            "info",
        )
    return col_types


def _check_earlier_loads(
    cur: cursor, file_name: str, file_hash: str, session: dict[str, Any] | None, logs: list[LogEntry]
) -> LoadResult | None:
    """Refuse content that is already a dynamic dataset; require delete permission to replace an earlier load."""
    cur.execute(
        sql.SQL(
            "SELECT mode, file_name, table_name, row_count FROM {s}.csv_files"
            " WHERE (file_name = %s AND mode <> 'dynamic') OR file_hash = %s"
        ).format(s=sql.Identifier(uploads_schema())),
        (file_name, file_hash),
    )
    prior = cur.fetchall()
    # #287 (BR-51): identical content already stored as a dynamic dataset. Replacing
    # it would drop that dataset's table, so refuse, whoever the caller is and
    # whatever API_ALLOW_DESTRUCTIVE says. Nothing has been written yet.
    dataset = next((p for p in prior if p[0] == "dynamic"), None)
    if dataset is not None:
        _log(
            logs,
            "duplicate_check",
            f'Identical content is already the dataset "{dataset[1]}"; nothing was imported',
            "warn",
        )
        return {
            "status": "duplicate_file",
            "reason": "content",
            "existingMode": "dynamic",
            "existingFileName": dataset[1],
            "tableName": dataset[2],
            "existingRowCount": dataset[3],
            "message": (
                f'This file\'s content is already stored as the dataset "{dataset[1]}". '
                "A T&E upload cannot replace a dataset, so nothing was imported."
            ),
            "logs": logs,
        }
    if prior:
        _require_delete(session)
    return None


def cast_te_rows(
    data_rows: list[list[str]], columns: list[str], col_types: list[str | None], errors: RowErrors
) -> list[tuple[int, list[Any]]]:
    """``(source row number, values)`` for each row that passes the client-side check; failures go to ``errors``."""
    to_insert: list[tuple[int, list[Any]]] = []
    for r, raw in enumerate(data_rows):
        row_number = r + 1
        if ragged(raw, len(columns), row_number, errors):
            continue
        values = _cast_te_cells(raw, columns, col_types, row_number, errors)
        if values is not None:
            to_insert.append((row_number, values))
    return to_insert


def _cast_te_cells(
    raw: list[str], columns: list[str], col_types: list[str | None], row_number: int, errors: RowErrors
) -> list[Any] | None:
    """One row's values: an empty cell is NULL, an unmapped type goes to Postgres as text. None if a cell failed."""
    values: list[Any] = []
    for c, col_type in enumerate(col_types):
        cell = raw[c].strip() if c < len(raw) else ""
        if cell == "":
            values.append(None)
            continue
        if col_type is None:
            values.append(cell)
            continue
        ok, val, reason = cast_value(cell, col_type)
        if not ok:
            errors.add(row_number, columns[c], cell, reason or "type error")
            return None
        values.append(val)
    return values


def _not_imported(
    errors: RowErrors, total_rows: int, target_table: str, columns: list[str], logs: list[LogEntry]
) -> LoadResult:
    if errors.failed >= total_rows:
        msg = f"None of the {total_rows} rows could be imported into {target_table}, so nothing was saved."
    else:
        msg = (
            f"{errors.failed} of the {total_rows} rows could not be imported into "
            f"{target_table}, so nothing was saved. Fix them and upload the file again."
        )
    e = errors.first()
    if e:
        msg += f" First problem: row {e['rowNumber']}, {e.get('column', '')}: {e.get('reason', '')}"
    return rows_failed(msg, errors, total_rows, logs, insertedRows=0, columns=columns)


def _register(
    conn: connection,
    cur: cursor,
    file_name: str,
    file_hash: str,
    target_table: str,
    inserted: int,
    columns: list[str],
    total_rows: int,
    failed: int,
    logs: list[LogEntry],
) -> int | LoadResult:
    """Add the load to csv_files and return its id, or the error response if a concurrent load got there first."""
    try:
        cur.execute(
            sql.SQL(
                "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names, "
                "total_rows, duplicate_rows_skipped, failed_rows) "
                "VALUES (%s, %s, %s, 'te', %s, %s, %s, 0, %s) RETURNING id"
            ).format(sql.Identifier(uploads_schema())),
            (file_name, file_hash, f"{te_schema()}.{target_table}", inserted, columns, total_rows, failed),
        )
    except psycopg2.errors.UniqueViolation:
        # #81: a concurrent load of the same file registered first.
        # Roll back this load's rows too, so nothing lands twice.
        conn.rollback()
        _log(logs, "duplicate_check", "Lost race to a concurrent load of the same file", "warn")
        return {
            "status": "error",
            "message": "The same file was loaded concurrently and that load finished first. Nothing was imported by this request.",
            "logs": logs,
        }
    return int(fetch_one(cur)[0])


def _ok_result(
    file_id: object,
    target_table: str,
    data_rows: list[list[str]],
    inserted: int,
    failed_row_count: int,
    columns: list[str],
    col_types: list[str | None],
    row_errors: list[RowError],
    logs: list[LogEntry],
) -> LoadResult:
    return ok_result(
        file_id,
        f"{te_schema()}.{target_table}",
        len(data_rows),
        inserted,
        0,
        failed_row_count,
        columns,
        # #190: stored with the upload so review revalidates against the target's types.
        # Columns Postgres casts itself (uuid, enums, ...) review as text.
        [t or "text" for t in col_types],
        rowErrors=row_errors,
        logs=logs,
    )
