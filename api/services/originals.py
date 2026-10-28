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


def record_upload(file_name: str, content: str, mode: str, result: dict) -> int | None:
    """Store the original and its outcome. Returns the upload id, or None if it couldn't be stored."""
    data = content.encode("utf-8")
    ok = result.get("status") == "ok"
    try:
        with Conn() as conn:
            with conn.cursor() as cur:
                s = sql.Identifier(uploads_schema())
                cur.execute(sql.SQL(
                    "INSERT INTO {}.uploads (file_name, sha256, byte_size, uploader, mode, status, "
                    "total_rows, imported_rows, failed_rows, csv_file_id, row_errors, logs) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id").format(s),
                    (file_name, hashlib.sha256(data).hexdigest(), len(data), current_actor(), mode,
                     outcome(result), result.get("totalRows"), result.get("insertedRows"),
                     result.get("failedRows"), coerce_file_id(result.get("fileId")) if ok else None,
                     Json((result.get("rowErrors") or [])[:settings.MAX_ROW_ERRORS_REPORTED]),
                     Json(result.get("logs") or [])))
                upload_id = cur.fetchone()[0]
                cur.execute(sql.SQL("INSERT INTO {}.upload_blobs (upload_id, content) VALUES (%s, %s)").format(s),
                            (upload_id, data))
                rows = parse_csv(content)  # ponytail: second parse after the loader's; share it if uploads get slow
                if rows:
                    execute_values(cur, sql.SQL("INSERT INTO {}.source_rows (upload_id, row_number, cells) VALUES %s")
                                   .format(s).as_string(cur), [(upload_id, n, r) for n, r in enumerate(rows)],
                                   page_size=1000)
            conn.commit()
        return upload_id
    except Exception as exc:  # noqa: BLE001 — the load has already committed; see the module docstring
        logger.error("Failed to store the original of %r: %s", file_name, exc)
        return None
