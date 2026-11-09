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
import time

import psycopg2.errors
from psycopg2 import sql
from psycopg2.extras import execute_values

from api.config import settings
from api.tenancy import uploads_schema
from api.db import Conn
from api.services.csv_parse import (
    ALLOWED_TYPES,
    apply_header_mapping,
    cast_value,
    extra_cells,
    parse_csv,
    ragged_row_reason,
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


def dataset_slug(file_name: str) -> str:
    """Lower-case ASCII slug of a filename without .csv, at most 40 characters.

    Must agree with the backfill expression in alembic/versions/0009_versioned_datasets.py.
    """
    s = re.sub(r"[^a-z0-9]+", "_", re.sub(r"\.csv$", "", file_name, flags=re.I).lower()).strip("_")
    return s[:40].strip("_") or "dataset"


_SYSTEM_COLUMNS = ("_id", "_row_hash", "_created_at", "_source_row_id", "_import_id")  # the last two: staged imports (M6)
_UDT = {"boolean": "bool"}  # information_schema udt_name where it differs from our type name


def _schema_diff(cur, schema: str, prior_table: str, columns: list[str], col_types: list[str]) -> dict | None:
    """How the new columns compare with the previous version's. None if that table is gone.

    Additions are compatible; a removed or retyped column is not. Informational only: the
    previous version's table is never altered, so nothing destructive can happen here.
    """
    cur.execute("SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s", (schema, prior_table))
    old = {n: t for n, t in cur.fetchall() if n not in _SYSTEM_COLUMNS}
    if not old:
        return None
    new = {c: _UDT.get(t, t) for c, t in zip(columns, col_types)}
    removed = [c for c in old if c not in new]
    changed = [{"column": c, "was": old[c], "now": new[c]} for c in new if c in old and old[c] != new[c]]
    return {"compatible": not removed and not changed,
            "added": [c for c in new if c not in old], "removed": removed, "changed": changed}


def _earlier_version_matches(cur, schema: str, priors: list, hashes: list[str], rows: list[int]) -> list[dict]:
    """Rows (by number) whose hash is already in an earlier version's table. Newest matching version wins.

    ``priors`` is newest first: (registry id, file name, table name, version). A prior whose
    table has gone is skipped. Hashes made before the v2 scheme (#178) simply won't match.
    """
    by_hash = dict(zip(hashes, rows))
    pending = set(by_hash)
    flags: list[dict] = []
    for file_id, file_name, table_name, version in priors:
        if not pending:
            break
        todo = list(pending)
        hits: list[str] = []
        cur.execute("SAVEPOINT prior_table")
        try:
            for i in range(0, len(todo), 5000):
                cur.execute(sql.SQL("SELECT _row_hash FROM {}.{} WHERE _row_hash = ANY(%s)").format(
                    sql.Identifier(schema), sql.Identifier(table_name)), (todo[i:i + 5000],))
                hits += [h for (h,) in cur.fetchall()]
        except psycopg2.errors.UndefinedTable:
            cur.execute("ROLLBACK TO SAVEPOINT prior_table")
            continue
        cur.execute("RELEASE SAVEPOINT prior_table")
        for h in hits:
            pending.discard(h)
            flags.append({"rowNumber": by_hash[h], "matchedFileId": str(file_id),
                          "matchedFileName": file_name, "matchedVersion": version})
    return sorted(flags, key=lambda f: f["rowNumber"])


def upload_dynamic(
    file_name: str,
    content: str,
    types: list[str] | None,
    overwrite: bool,
    *,
    session: dict | None = None,
    header_mapping: list[dict] | None = None,
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

    # #186: honour confirmed header renames; the column name in the table is
    # the renamed one, not the CSV's original.
    mapped_headers, mapping_error = apply_header_mapping(rows[0], header_mapping)
    if mapping_error:
        _log(logs, "header_mapping", mapping_error, "error")
        return {"status": "error", "reason": "invalid_header_mapping", "message": mapping_error, "logs": logs}
    if header_mapping:
        renamed_count = sum(1 for a, b in zip(rows[0], mapped_headers) if a != b)
        _log(logs, "header_mapping", f"Renamed {renamed_count} column header(s)", count=renamed_count)
        rows = [mapped_headers] + rows[1:]

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

    schema = uploads_schema()

    try:
        return _do_upload(file_name, types, overwrite, logs, schema, rows, file_hash, session=session)
    except psycopg2.errors.UniqueViolation:
        # #81: an identical concurrent upload won a race that _do_upload could
        # not settle itself (e.g. both creating csv_<hash> at once). Nothing
        # from this request was committed.
        _log(logs, "duplicate_check", "Lost race to a concurrent identical upload", "warn")
        return {
            "status": "duplicate_file",
            "reason": "content",
            "existingFileName": file_name,
            "tableName": f"csv_{file_hash[:16]}",
            "existingRowCount": 0,
            "logs": logs,
        }
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
    *,
    session: dict | None = None,
) -> dict:
    with Conn() as conn:
        with conn.cursor() as cur:
            dataset = dataset_slug(file_name)
            # One upload per dataset at a time, so two uploads of the same filename can't pick the
            # same version. Released at commit or rollback.
            # ponytail: held through row casting; take it just before the insert if big same-name uploads queue.
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{schema}.{dataset}",))
            if overwrite:
                _log(logs, "overwrite", "Overwrite is not supported (decision 2): storing a new version instead", "warn")

            # Exact-file duplicate check. The registry is per tenant, so this is a per-tenant check.
            _log(logs, "duplicate_check", "Checking existing content hash")
            cur.execute(
                sql.SQL(
                    "SELECT file_name, table_name, row_count FROM {}.csv_files WHERE file_hash = %s"
                ).format(sql.Identifier(schema)),
                (file_hash,),
            )
            content_match = cur.fetchone()
            if content_match:
                _log(logs, "duplicate_check", f"Content matches existing file ({content_match[0]})", "warn")
                return {
                    "status": "duplicate_file",
                    "reason": "content",
                    "existingFileName": content_match[0],
                    "tableName": content_match[1],
                    "existingRowCount": content_match[2] or 0,
                    "logs": logs,
                }

            # Earlier versions of this dataset, newest first.
            cur.execute(
                sql.SQL(
                    "SELECT id, file_name, table_name, version FROM {}.csv_files "
                    "WHERE dataset = %s ORDER BY version DESC"
                ).format(sql.Identifier(schema)),
                (dataset,),
            )
            priors = cur.fetchall()
            version = priors[0][3] + 1 if priors else 1
            _log(logs, "version", f'"{dataset}" version {version}', count=version)

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

            # Compare with the previous version. Informational: its table is never altered.
            schema_check = None
            if priors:
                schema_check = _schema_diff(cur, schema, priors[0][2], columns, col_types)
                if schema_check:
                    schema_check["comparedTo"] = {"fileName": priors[0][1], "version": priors[0][3],
                                                  "tableName": priors[0][2]}
                    _log(logs, "schema_check", "Columns match the previous version" if schema_check["compatible"]
                         else "Columns differ from the previous version",
                         "info" if schema_check["compatible"] else "warn")

            # Create table. Plain CREATE, not IF NOT EXISTS: a name clash must fail, not append to a stranger's table.
            table_name = f"csv_{dataset}_v{version}"
            col_defs = sql.SQL(", ").join(
                sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(_TYPE_SQL[t]))
                for c, t in zip(columns, col_types)
            )
            _log(logs, "create_table", f"create table {table_name} ({len(columns)} cols)")
            cur.execute(
                sql.SQL(
                    "CREATE TABLE {}.{} "
                    "(_id BIGSERIAL PRIMARY KEY, {}, _row_hash TEXT NOT NULL UNIQUE, "
                    "_created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                ).format(sql.Identifier(schema), sql.Identifier(table_name), col_defs)
            )

            # Cast rows
            data_rows = rows[1:]
            seen: set[str] = set()
            to_insert: list[tuple] = []
            insert_rows: list[int] = []  # source row number of each to_insert entry
            row_errors: list[dict] = []
            failed_row_count = 0
            duplicates = 0

            for r, raw in enumerate(data_rows):
                row_number = r + 1
                values: list = []
                raw_joined: list[str] = []
                failed = False
                extra = extra_cells(raw, len(columns))
                if extra:
                    if len(row_errors) < settings.MAX_ROW_ERRORS_REPORTED:
                        row_errors.append({"rowNumber": row_number, "column": "(beyond header)",
                                           "value": extra[0], "reason": ragged_row_reason(raw, len(columns))})
                    failed_row_count += 1
                    continue
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
                # #178: JSON serialization prevents ambiguous concatenation.
                # U+001F join was vulnerable: cells containing U+001F caused
                # distinct rows to hash identically (silent data loss).
                row_hash = "v2:" + hashlib.sha256(
                    json.dumps(raw_joined, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                if row_hash in seen:
                    duplicates += 1
                    continue
                seen.add(row_hash)
                to_insert.append(tuple(values) + (row_hash,))
                insert_rows.append(row_number)

            _log(
                logs,
                "cast_rows",
                f"Cast {len(data_rows)} rows → {len(to_insert)} valid, {failed_row_count} errors, {duplicates} in-file duplicates",
                "warn" if failed_row_count else "info",
                count=len(to_insert),
            )

            # #123: if every row failed, nothing was migrated. Roll back the new
            # table (and any overwrite) and report a failed upload, not a success.
            if data_rows and failed_row_count == len(data_rows):
                conn.rollback()
                msg = f"None of the {len(data_rows)} rows could be imported, so nothing was saved."
                if row_errors:
                    e = row_errors[0]
                    msg += f' First problem: row {e["rowNumber"]}, column "{e["column"]}": {e["reason"]}'
                _log(logs, "error", msg, "error")
                return {"status": "error", "message": msg, "rowErrors": row_errors,
                        "totalRows": len(data_rows), "failedRows": failed_row_count,
                        "columns": columns, "types": col_types, "logs": logs}

            # BR-29: rows whose exact content is already in an earlier version of this dataset are
            # still loaded, but flagged. The user decides per row (decision 3), through review.
            flags = _earlier_version_matches(cur, schema, priors, [r[-1] for r in to_insert], insert_rows)
            if flags:
                _log(logs, "cross_upload_duplicates", f"{len(flags)} rows already exist in an earlier version",
                     "warn", count=len(flags))

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
                        "INSERT INTO {}.csv_files (file_name, file_hash, table_name, mode, row_count, column_names, "
                        "total_rows, duplicate_rows_skipped, failed_rows, dataset, version) "
                        "VALUES (%s, %s, %s, 'dynamic', %s, %s, %s, %s, %s, %s, %s) RETURNING id"
                    ).format(sql.Identifier(schema)),
                    (file_name, file_hash, table_name, inserted, columns,
                     len(data_rows), duplicates, failed_row_count, dataset, version),
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
                    "reason": "content",  # only UNIQUE (file_hash) can fail here: versions are serialised by the lock
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
        "dataset": dataset,
        "version": version,
        "schemaCheck": schema_check,
        "duplicateRowsAcrossUploads": len(flags),
        "crossUploadDuplicates": flags[:settings.MAX_ROW_ERRORS_REPORTED],
        # Full list for record_upload, which stores it; the route removes it before replying.
        "_duplicateFlags": flags,
        # Never overwritten (decision 2). Kept so older clients reading these fields still work.
        "overwritten": False,
        "replacedFileName": None,
    }
