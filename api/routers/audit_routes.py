"""BUG-041: csv_uploads.audit_log was write-only (populated by delete_file in
csv_routes.py, never read back). This router surfaces it as a paginated,
API-key-guarded feed so the deletion trail is actually consultable."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg2 import sql

from api.auth import require_api_key
from api.config import settings
from api.db import Conn

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/log")
def audit_log(limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {}.audit_log").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA)
                )
            )
            total = cur.fetchone()[0]
            cur.execute(
                sql.SQL(
                    "SELECT id, action, file_id, file_name, table_name, mode, performed_at "
                    "FROM {}.audit_log ORDER BY performed_at DESC LIMIT %s OFFSET %s"
                ).format(sql.Identifier(settings.UPLOADS_SCHEMA)),
                (limit, offset),
            )
            entries = [
                {
                    "id": str(r[0]),
                    "action": r[1],
                    "fileId": r[2],
                    "fileName": r[3],
                    "tableName": r[4],
                    "mode": r[5],
                    "performedAt": r[6].isoformat(),
                }
                for r in cur.fetchall()
            ]
    return {"total": total, "limit": limit, "offset": offset, "entries": entries}
