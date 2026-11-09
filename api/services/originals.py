"""Keep each upload's original file and parsed rows (M3b, #107; BR-23, BR-24).

Every upload attempt is recorded in ``uploads`` with its outcome, and its bytes
and parsed rows go to ``upload_blobs`` and ``source_rows``. All three tables are
insert-only (migration 0007), so overwriting or deleting a migrated file never
loses its original.

Known limitation, the same as record_audit: the loaders commit their own
transaction, so this runs after the load. A failure here is logged at ERROR
and doesn't fail the upload. M6's single-transaction import (ADR-0002) closes it.
"""

from __future__ import annotations

import hashlib
import logging

from psycopg2 import sql
from psycopg2.extras import Json, execute_values

from api.config import settings
from api.db import Conn
from api.services.audit import coerce_file_id, current_actor
from api.services.csv_parse import parse_csv
from api.tenancy import uploads_schema

logger = logging.getLogger(__name__)

_STATUS = {"duplicate_file": "duplicate", "invalid_structure": "rejected", "error": "failed"}


def outcome(result: dict) -> str:
    status = result.get("status")
    if status == "ok":
        return "partly_imported" if result.get("failedRows") else "imported"
    return _STATUS.get(status, "failed")


def record_upload(file_name: str, content: str, mode: str, result: dict, *,
                  original: bytes | None = None, flags: list[dict] | None = None) -> int | None:
    """Store the original and its outcome. Returns the upload id, or None if it couldn't be stored.

    ``original`` is the file's bytes exactly as uploaded (#185); it is what gets hashed and
    kept. Without it the decoded ``content`` re-encoded as UTF-8 stands in, which loses a
    BOM or any invalid bytes. ``content`` still feeds the parsed ``source_rows`` view.
    ``flags`` are rows that duplicate an earlier version of the dataset (M5, BR-29), stored as ``row_flags``.
    """
    data = original if original is not None else content.encode("utf-8")
    ok = result.get("status") == "ok"
    try:
        with Conn() as conn:
            with conn.cursor() as cur:
                s = sql.Identifier(uploads_schema())
                cur.execute(sql.SQL(
                    "INSERT INTO {}.uploads (file_name, sha256, byte_size, uploader, mode, status, "
                    "total_rows, imported_rows, failed_rows, csv_file_id, row_errors, logs, columns, column_types) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id").format(s),
                    (file_name, hashlib.sha256(data).hexdigest(), len(data), current_actor(), mode,
                     outcome(result), result.get("totalRows"), result.get("insertedRows"),
                     result.get("failedRows"), coerce_file_id(result.get("fileId")) if ok else None,
                     Json((result.get("rowErrors") or [])[:settings.MAX_ROW_ERRORS_REPORTED]),
                     Json(result.get("logs") or []), result.get("columns"), result.get("types")))
                upload_id = cur.fetchone()[0]
                cur.execute(sql.SQL("INSERT INTO {}.upload_blobs (upload_id, content) VALUES (%s, %s)").format(s),
                            (upload_id, data))
                rows = parse_csv(content)  # ponytail: second parse after the loader's; share it if uploads get slow
                if rows:
                    execute_values(cur, sql.SQL("INSERT INTO {}.source_rows (upload_id, row_number, cells) VALUES %s")
                                   .format(s).as_string(cur), [(upload_id, n, r) for n, r in enumerate(rows)],
                                   page_size=1000)
                if flags:
                    execute_values(cur, sql.SQL("INSERT INTO {}.row_flags (upload_id, row_number, kind, "
                                                "matched_file_id, matched_file_name, matched_version) VALUES %s")
                                   .format(s).as_string(cur),
                                   [(upload_id, f["rowNumber"], "duplicate_of_earlier_version", int(f["matchedFileId"]),
                                     f["matchedFileName"], f["matchedVersion"]) for f in flags], page_size=1000)
            conn.commit()
        return upload_id
    except Exception as exc:  # noqa: BLE001 — the load has already committed; see the module docstring
        logger.error("Failed to store the original of %r: %s", file_name, exc)
        return None
