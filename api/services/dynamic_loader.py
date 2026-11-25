"""Dynamic mode: each CSV becomes its own typed table in the uploads schema.

  - a repeated filename is the next version of its dataset, never an overwrite (M5, decision 2):
    table name csv_<slug>_v<n>, where slug comes from the filename
  - the same bytes twice in one tenant are refused (exact-file dedup, BR-28)
  - columns typed via whitelist, plus _id / _row_hash / _created_at
  - in-file duplicate rows skipped via _row_hash; rows already in an earlier version
    of the dataset are loaded but flagged, and the user decides per row (decision 3, BR-29)
All identifiers go through psycopg2.sql.Identifier — no string interpolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import psycopg2.errors
from psycopg2 import sql
from psycopg2.extensions import connection, cursor
from psycopg2.extras import execute_values

from api.config import settings
from api.db import Conn, fetch_one
from api.services.csv_parse import (
    ALLOWED_TYPES,
    apply_header_mapping,
    cast_value,
    parse_csv,
    sanitize_columns,
    valid_identifier,
)
from api.services.load_common import RowErrors, ok_result, ragged, rows_failed, too_many_rows
from api.services.load_common import log as _log
from api.services.results import DuplicateFlag, LoadResult, LogEntry, SchemaCheck
from api.tenancy import uploads_schema

logger = logging.getLogger(__name__)

_TYPE_SQL = {
    "int8": "int8",
    "numeric": "numeric",
    "date": "date",
    "timestamptz": "timestamptz",
    "boolean": "boolean",
    "text": "text",
}


def dataset_slug(file_name: str) -> str:
    """Lower-case ASCII slug of a filename without .csv, at most 40 characters.

    Must agree with the backfill expression in alembic/versions/0009_versioned_datasets.py.
    """
    s = re.sub(r"[^a-z0-9]+", "_", re.sub(r"\.csv$", "", file_name, flags=re.I).lower()).strip("_")
    return s[:40].strip("_") or "dataset"


_SYSTEM_COLUMNS = (
    "_id",
    "_row_hash",
    "_created_at",
    "_source_row_id",
    "_import_id",
)  # the last two: staged imports (M6)
_UDT = {"boolean": "bool"}  # information_schema udt_name where it differs from our type name


def _schema_diff(
    cur: cursor, schema: str, prior_table: str, columns: list[str], col_types: list[str]
) -> SchemaCheck | None:
    """How the new columns compare with the previous version's. None if that table is gone.

    Additions are compatible; a removed or retyped column is not. Informational only: the
    previous version's table is never altered, so nothing destructive can happen here.
    """
    cur.execute(
        "SELECT column_name, udt_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
        (schema, prior_table),
    )
    old = {n: t for n, t in cur.fetchall() if n not in _SYSTEM_COLUMNS}
    if not old:
        return None
    new = {c: _UDT.get(t, t) for c, t in zip(columns, col_types)}
    removed = [c for c in old if c not in new]
    changed = [{"column": c, "was": old[c], "now": new[c]} for c in new if c in old and old[c] != new[c]]
    return {
        "compatible": not removed and not changed,
        "added": [c for c in new if c not in old],
        "removed": removed,
        "changed": changed,
    }


def _earlier_version_matches(
    cur: cursor, schema: str, priors: list[tuple[Any, ...]], hashes: list[str], rows: list[int]
) -> list[DuplicateFlag]:
    """Rows (by number) whose hash is already in an earlier version's table. Newest matching version wins.

    ``priors`` is newest first: (registry id, file name, table name, version). A prior whose
    table has gone is skipped. Hashes made before the v2 scheme (#178) simply won't match.
    """
    by_hash = dict(zip(hashes, rows))
    pending = set(by_hash)
    flags: list[DuplicateFlag] = []
    for file_id, file_name, table_name, version in priors:
        if not pending:
            break
        todo = list(pending)
        hits: list[str] = []
        cur.execute("SAVEPOINT prior_table")
        try:
            for i in range(0, len(todo), 5000):
                cur.execute(
                    sql.SQL("SELECT _row_hash FROM {}.{} WHERE _row_hash = ANY(%s)").format(
                        sql.Identifier(schema), sql.Identifier(table_name)
                    ),
                    (todo[i : i + 5000],),
                )
                hits += [h for (h,) in cur.fetchall()]
        except psycopg2.errors.UndefinedTable:
            cur.execute("ROLLBACK TO SAVEPOINT prior_table")
            continue
        cur.execute("RELEASE SAVEPOINT prior_table")
        for h in hits:
            pending.discard(h)
            flags.append(
                {
                    "rowNumber": by_hash[h],
                    "matchedFileId": str(file_id),
                    "matchedFileName": file_name,
                    "matchedVersion": version,
                }
            )
    return sorted(flags, key=lambda f: f["rowNumber"])


def upload_dynamic(
    file_name: str,
    content: str,
    types: list[str] | None,
    overwrite: bool,
    *,
    session: dict[str, Any] | None = None,
    header_mapping: list[dict[str, Any]] | None = None,
    types_confirmed: bool = False,
    on_commit: Callable[[cursor, LoadResult], None] | None = None,
) -> LoadResult:
    """Load ``content`` as a new version of its dynamic dataset.

    ``on_commit(cur, result)`` runs on the load's cursor just before the commit, given the "ok" result
    this call will return. Whatever it writes commits with the load. If it raises, the load rolls back
    and the exception propagates; only ``psycopg2`` errors from the load itself become an error dict (#288).
    """
    logs: list[LogEntry] = []
    _log(logs, "receive", f'Received "{file_name}" ({len(content)} chars)')

    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _log(logs, "hash", f"Computed content hash {file_hash[:12]}…")

    rows = parse_csv(content)
    _log(logs, "parse", f"Parsed {len(rows)} raw rows (including header)", count=len(rows))
    refused = _structure_problem(rows, logs)
    if refused:
        return refused

    # #186: honour confirmed header renames; the column name in the table is
    # the renamed one, not the CSV's original.
    rows, refused = _apply_header_mapping(rows, header_mapping, logs)
    if refused:
        return refused

    # BUG-027 guard: reject files above the configured row cap before doing any
    # per-row work. `rows` includes the header, so subtract one.
    refused = too_many_rows(len(rows) - 1, logs)
    if refused:
        return refused

    schema = uploads_schema()
    # #195: only types a person explicitly confirmed count as confirmed; omitted types
    # fall back to text and a bare `types` list is not proof anyone looked at it.
    provenance = "user_confirmed" if (types and types_confirmed) else "inferred_unconfirmed"

    try:
        return _do_upload(
            file_name,
            types,
            overwrite,
            logs,
            schema,
            rows,
            file_hash,
            session=session,
            types_provenance=provenance,
            on_commit=on_commit,
        )
    except psycopg2.errors.UniqueViolation:
        return _lost_race(file_name, file_hash, logs)
    except psycopg2.Error as exc:
        return _database_error(file_name, exc, logs)


def _lost_race(file_name: str, file_hash: str, logs: list[LogEntry]) -> LoadResult:
    """#81: an identical concurrent upload won a race that _do_upload could not settle itself (e.g. both
    creating csv_<hash> at once). Nothing from this request was committed."""
    _log(logs, "duplicate_check", "Lost race to a concurrent identical upload", "warn")
    return {
        "status": "duplicate_file",
        "reason": "content",
        "existingFileName": file_name,
        "tableName": f"csv_{file_hash[:16]}",
        "existingRowCount": 0,
        "logs": logs,
    }


def _database_error(file_name: str, exc: psycopg2.Error, logs: list[LogEntry]) -> LoadResult:
    """Mirror te_loader's structured-error contract: an unexpected DB error (e.g. a column type edge case not
    caught by cast_value) should not surface as a raw 500 to the frontend."""
    logger.warning("Dynamic upload failed for %r: %s", file_name, exc)
    _log(logs, "error", "Database error while loading the CSV", "error")
    return {
        "status": "error",
        "message": "The CSV could not be loaded due to a database error. Check the file's data types and try again.",
        "logs": logs,
    }


def _structure_problem(rows: list[list[str]], logs: list[LogEntry]) -> LoadResult | None:
    """The response for a CSV with no data to load (empty, header only, blank header), or None if it has some."""
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
    return None


def _apply_header_mapping(
    rows: list[list[str]], header_mapping: list[dict[str, Any]] | None, logs: list[LogEntry]
) -> tuple[list[list[str]], LoadResult | None]:
    """``rows`` with the confirmed header renames applied (#186), or the error response for an invalid mapping."""
    mapped_headers, mapping_error = apply_header_mapping(rows[0], header_mapping)
    if mapping_error:
        _log(logs, "header_mapping", mapping_error, "error")
        return rows, {"status": "error", "reason": "invalid_header_mapping", "message": mapping_error, "logs": logs}
    if header_mapping:
        renamed_count = sum(1 for a, b in zip(rows[0], mapped_headers) if a != b)
        _log(logs, "header_mapping", f"Renamed {renamed_count} column header(s)", count=renamed_count)
        rows = [mapped_headers] + rows[1:]
    return rows, None


def _do_upload(
    file_name: str,
    types: list[str] | None,
    overwrite: bool,
    logs: list[LogEntry],
    schema: str,
    rows: list[list[str]],
    file_hash: str,
    *,
    session: dict[str, Any] | None = None,
    types_provenance: str = "inferred_unconfirmed",
    on_commit: Callable[[cursor, LoadResult], None] | None = None,
) -> LoadResult:
    with Conn() as conn:
        with conn.cursor() as cur:
            target = _prepare_version(cur, schema, file_name, file_hash, rows[0], types, overwrite, logs)
            if isinstance(target, dict):
                return target
            dataset, version, priors, columns, col_types, schema_check, table_name = target

            data_rows = rows[1:]
            cast = _cast_and_log(data_rows, columns, col_types, logs)

            # #123: if every row failed, nothing was migrated. Roll back the new
            # table (and any overwrite) and report a failed upload, not a success.
            if data_rows and cast.errors.failed == len(data_rows):
                conn.rollback()
                return _every_row_failed(cast.errors, len(data_rows), columns, col_types, logs)

            flags = _flag_earlier_versions(cur, schema, priors, cast, logs)

            inserted = _insert(cur, schema, table_name, columns, cast.to_insert)
            _log(logs, "insert", f"Inserted {inserted} rows", count=inserted)

            registered = _register(
                conn,
                cur,
                schema,
                file_name,
                file_hash,
                table_name,
                inserted,
                columns,
                len(data_rows),
                cast,
                types_provenance,
                dataset,
                version,
                logs,
            )
            if isinstance(registered, dict):
                return registered

            _log(logs, "done", f"Import complete for {file_name}")
            result = _ok(
                registered,
                table_name,
                len(data_rows),
                inserted,
                cast,
                columns,
                col_types,
                types_provenance,
                logs,
                dataset,
                version,
                schema_check,
                flags,
            )
            if on_commit is not None:
                on_commit(cur, result)
        conn.commit()
    return result


class _Version(NamedTuple):
    """The new version of a dataset that an upload becomes, with its table created."""

    dataset: str
    version: int
    priors: list[tuple[Any, ...]]
    columns: list[str]
    col_types: list[str]
    schema_check: SchemaCheck | None
    table_name: str


def _prepare_version(
    cur: cursor,
    schema: str,
    file_name: str,
    file_hash: str,
    header: list[str],
    types: list[str] | None,
    overwrite: bool,
    logs: list[LogEntry],
) -> _Version | LoadResult:
    """Lock the dataset, pick its next version and create that version's table; or the response that stops the load
    (the same content is already loaded, or the types are invalid)."""
    dataset = dataset_slug(file_name)
    # One upload per dataset at a time, so two uploads of the same filename can't pick the
    # same version. Released at commit or rollback.
    # ponytail: held through row casting; take it just before the insert if big same-name uploads queue.
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{schema}.{dataset}",))
    if overwrite:
        _log(logs, "overwrite", "Overwrite is not supported (decision 2): storing a new version instead", "warn")

    duplicate = _same_content(cur, schema, file_hash, logs)
    if duplicate:
        return duplicate
    priors, version = _versions(cur, schema, dataset, logs)
    checked = _columns_and_types(header, types, logs)
    if isinstance(checked, dict):
        return checked
    columns, col_types = checked
    schema_check = _compare_with_previous(cur, schema, priors, columns, col_types, logs)

    table_name = f"csv_{dataset}_v{version}"
    _create_table(cur, schema, table_name, columns, col_types, logs)
    return _Version(dataset, version, priors, columns, col_types, schema_check, table_name)


def _cast_and_log(
    data_rows: list[list[str]], columns: list[str], col_types: list[str], logs: list[LogEntry]
) -> CastRows:
    cast = cast_rows(data_rows, columns, col_types)
    _log(
        logs,
        "cast_rows",
        f"Cast {len(data_rows)} rows → {len(cast.to_insert)} valid, {cast.errors.failed} errors, "
        f"{cast.duplicates} in-file duplicates",
        "warn" if cast.errors.failed else "info",
        count=len(cast.to_insert),
    )
    return cast


def _flag_earlier_versions(
    cur: cursor, schema: str, priors: list[tuple[Any, ...]], cast: CastRows, logs: list[LogEntry]
) -> list[DuplicateFlag]:
    """BR-29: rows whose exact content is already in an earlier version of this dataset are
    still loaded, but flagged. The user decides per row (decision 3), through review."""
    flags = _earlier_version_matches(cur, schema, priors, [r[-1] for r in cast.to_insert], cast.insert_rows)
    if flags:
        _log(
            logs,
            "cross_upload_duplicates",
            f"{len(flags)} rows already exist in an earlier version",
            "warn",
            count=len(flags),
        )
    return flags


def _ok(
    file_id: object,
    table_name: str,
    total_rows: int,
    inserted: int,
    cast: CastRows,
    columns: list[str],
    col_types: list[str],
    types_provenance: str,
    logs: list[LogEntry],
    dataset: str,
    version: int,
    schema_check: SchemaCheck | None,
    flags: list[DuplicateFlag],
) -> LoadResult:
    return ok_result(
        file_id,
        table_name,
        total_rows,
        inserted,
        cast.duplicates,
        cast.errors.failed,
        columns,
        col_types,
        typesProvenance=types_provenance,
        rowErrors=cast.errors.items,
        logs=logs,
        dataset=dataset,
        version=version,
        schemaCheck=schema_check,
        duplicateRowsAcrossUploads=len(flags),
        crossUploadDuplicates=flags[: settings.MAX_ROW_ERRORS_REPORTED],
        # Full list for store_upload, which stores it; the route removes it before replying.
        _duplicateFlags=flags,
        # Never overwritten (decision 2). Kept so older clients reading these fields still work.
        overwritten=False,
        replacedFileName=None,
    )


def _same_content(cur: cursor, schema: str, file_hash: str, logs: list[LogEntry]) -> LoadResult | None:
    """Exact-file duplicate check (BR-28). The registry is per tenant, so this is a per-tenant check."""
    _log(logs, "duplicate_check", "Checking existing content hash")
    cur.execute(
        sql.SQL("SELECT file_name, table_name, row_count FROM {}.csv_files WHERE file_hash = %s").format(
            sql.Identifier(schema)
        ),
        (file_hash,),
    )
    content_match = cur.fetchone()
    if not content_match:
        return None
    _log(logs, "duplicate_check", f"Content matches existing file ({content_match[0]})", "warn")
    return {
        "status": "duplicate_file",
        "reason": "content",
        "existingFileName": content_match[0],
        "tableName": content_match[1],
        "existingRowCount": content_match[2] or 0,
        "logs": logs,
    }


def _versions(cur: cursor, schema: str, dataset: str, logs: list[LogEntry]) -> tuple[list[tuple[Any, ...]], int]:
    """Earlier versions of this dataset, newest first, and the version this upload becomes."""
    cur.execute(
        sql.SQL(
            "SELECT id, file_name, table_name, version FROM {}.csv_files WHERE dataset = %s ORDER BY version DESC"
        ).format(sql.Identifier(schema)),
        (dataset,),
    )
    priors = cur.fetchall()
    version = priors[0][3] + 1 if priors else 1
    _log(logs, "version", f'"{dataset}" version {version}', count=version)
    return priors, version


def _columns_and_types(
    header: list[str], types: list[str] | None, logs: list[LogEntry]
) -> tuple[list[str], list[str]] | LoadResult:
    """The table's column names and types, or the error response if the header or the types cannot be used."""
    columns = sanitize_columns(header)
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

    if types is not None and len(types) != len(columns):
        msg = f"Provided {len(types)} column types but the CSV has {len(columns)} columns."
        _log(logs, "error", msg, "error")
        return {"status": "error", "message": msg, "logs": logs}
    col_types = types if types else ["text"] * len(columns)
    if any(t not in ALLOWED_TYPES for t in col_types):
        _log(logs, "error", "Unsupported column type provided", "error")
        return {"status": "error", "message": "Unsupported column type provided.", "logs": logs}
    return columns, col_types


def _compare_with_previous(
    cur: cursor,
    schema: str,
    priors: list[tuple[Any, ...]],
    columns: list[str],
    col_types: list[str],
    logs: list[LogEntry],
) -> SchemaCheck | None:
    """How the columns compare with the previous version's. Informational: its table is never altered."""
    if not priors:
        return None
    schema_check = _schema_diff(cur, schema, priors[0][2], columns, col_types)
    if schema_check:
        schema_check["comparedTo"] = {"fileName": priors[0][1], "version": priors[0][3], "tableName": priors[0][2]}
        _log(
            logs,
            "schema_check",
            "Columns match the previous version"
            if schema_check["compatible"]
            else "Columns differ from the previous version",
            "info" if schema_check["compatible"] else "warn",
        )
    return schema_check


def _create_table(
    cur: cursor, schema: str, table_name: str, columns: list[str], col_types: list[str], logs: list[LogEntry]
) -> None:
    """Plain CREATE, not IF NOT EXISTS: a name clash must fail, not append to a stranger's table."""
    col_defs = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(_TYPE_SQL[t])) for c, t in zip(columns, col_types)
    )
    _log(logs, "create_table", f"create table {table_name} ({len(columns)} cols)")
    cur.execute(
        sql.SQL(
            "CREATE TABLE {}.{} "
            "(_id BIGSERIAL PRIMARY KEY, {}, _row_hash TEXT NOT NULL UNIQUE, "
            "_created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ).format(sql.Identifier(schema), sql.Identifier(table_name), col_defs)
    )


@dataclass
class CastRows:
    """The rows of a file, cast to their column types: what to insert, and what failed or repeated."""

    to_insert: list[tuple[Any, ...]] = field(default_factory=list)  # cast values, then the row hash
    insert_rows: list[int] = field(default_factory=list)  # source row number of each to_insert entry
    errors: RowErrors = field(default_factory=RowErrors)
    duplicates: int = 0  # rows identical to an earlier row of the same file, skipped


def row_hash(cells: list[str]) -> str:
    """#178: the hash of a row's raw cells. JSON serialization prevents ambiguous concatenation.

    A U+001F join was vulnerable: cells containing U+001F caused distinct rows to hash identically (silent data loss).
    """
    return (
        "v2:" + hashlib.sha256(json.dumps(cells, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    )


def cast_rows(data_rows: list[list[str]], columns: list[str], col_types: list[str]) -> CastRows:
    """Cast every row; a row with a cell that does not cast, or cells beyond the header, is an error."""
    out = CastRows()
    seen: set[str] = set()
    for r, raw in enumerate(data_rows):
        row_number = r + 1
        if ragged(raw, len(columns), row_number, out.errors):
            continue
        cast = _cast_cells(raw, columns, col_types, row_number, out.errors)
        if cast is None:
            continue
        values, cells = cast
        h = row_hash(cells)
        if h in seen:
            out.duplicates += 1
            continue
        seen.add(h)
        out.to_insert.append(tuple(values) + (h,))
        out.insert_rows.append(row_number)
    return out


def _cast_cells(
    raw: list[str], columns: list[str], col_types: list[str], row_number: int, errors: RowErrors
) -> tuple[list[Any], list[str]] | None:
    """The cast values and raw cells of one row (a short row's missing cells are empty), or None if a cell failed."""
    values: list[Any] = []
    cells: list[str] = []
    for c in range(len(columns)):
        cell = raw[c] if c < len(raw) else ""
        cells.append(cell)
        ok, val, reason = cast_value(cell, col_types[c])
        if not ok:
            errors.add(row_number, columns[c], cell, reason)
            return None
        values.append(val)
    return values, cells


def _every_row_failed(
    errors: RowErrors, total_rows: int, columns: list[str], col_types: list[str], logs: list[LogEntry]
) -> LoadResult:
    msg = f"None of the {total_rows} rows could be imported, so nothing was saved."
    e = errors.first()
    if e:
        msg += f' First problem: row {e["rowNumber"]}, column "{e["column"]}": {e["reason"]}'
    return rows_failed(msg, errors, total_rows, logs, columns=columns, types=col_types)


def _insert(cur: cursor, schema: str, table_name: str, columns: list[str], to_insert: list[tuple[Any, ...]]) -> int:
    """Insert the cast rows in pages of 500. Returns how many went in."""
    inserted = 0
    if not to_insert:
        return inserted
    insert_cols = sql.SQL(", ").join([sql.Identifier(c) for c in columns] + [sql.Identifier("_row_hash")])
    # RETURNING + fetch=True is deliberate: execute_values pages at 100
    # by default and cur.rowcount reflects only the last page, which
    # under-counted every file over 100 rows. Counting returned rows is
    # page-size independent. See docs/DEFECT_INSERTED_ROWS.md.
    stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s ON CONFLICT (_row_hash) DO NOTHING RETURNING 1").format(
        sql.Identifier(schema), sql.Identifier(table_name), insert_cols
    )
    for i in range(0, len(to_insert), 500):
        chunk = to_insert[i : i + 500]
        returned = execute_values(cur, stmt.as_string(cur), chunk, fetch=True)
        inserted += len(returned)
    return inserted


def _register(
    conn: connection,
    cur: cursor,
    schema: str,
    file_name: str,
    file_hash: str,
    table_name: str,
    inserted: int,
    columns: list[str],
    total_rows: int,
    cast: CastRows,
    types_provenance: str,
    dataset: str,
    version: int,
    logs: list[LogEntry],
) -> int | LoadResult:
    """Add the upload to csv_files and return its id, or the "duplicate_file" response if it lost a race.

    The duplicate checks above are racy (check-then-act, no lock held across the row-casting work), so a
    concurrent identical upload can slip past them; the registry's UNIQUE indexes are the real guard, and a
    violation here becomes the same structured "duplicate_file" response the earlier check returns.
    """
    _log(logs, "register", "Registering file in csv_files")
    try:
        cur.execute(
            sql.SQL(
                "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names, "
                "total_rows, duplicate_rows_skipped, failed_rows, types_provenance, dataset, version) "
                "VALUES (%s, %s, %s, 'dynamic', %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
            ).format(sql.Identifier(schema)),
            (
                file_name,
                file_hash,
                table_name,
                inserted,
                columns,
                total_rows,
                cast.duplicates,
                cast.errors.failed,
                types_provenance,
                dataset,
                version,
            ),
        )
        return int(fetch_one(cur)[0])
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cur.execute(
            sql.SQL(
                "SELECT file_name, table_name, row_count FROM {}.csv_files WHERE file_name = %s OR file_hash = %s"
            ).format(sql.Identifier(schema)),
            (file_name, file_hash),
        )
        existing = cur.fetchone()
        _log(logs, "duplicate_check", "Lost race to a concurrent identical upload", "warn")
        return {
            "status": "duplicate_file",
            "reason": "content",  # only UNIQUE (file_hash) can fail here: versions are serialised by the lock
            "existingFileName": existing[0] if existing else file_name,
            "tableName": existing[1] if existing else table_name,
            "existingRowCount": (existing[2] or 0) if existing else 0,
            "logs": logs,
        }
