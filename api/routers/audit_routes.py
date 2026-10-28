"""BUG-041: csv_uploads.audit_log was write-only (populated by delete_file in
csv_routes.py, never read back). This router surfaces it as a paginated,
API-key-guarded feed so the trail is actually consultable.

O-04 update: the table is no longer delete-only. Successful uploads also write a
row, through the shared writer in api/services/audit.py, so this feed now covers
creations as well as destructions. Integration coverage lives in
tests/test_api_integration.py::AuditLogTrail."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from psycopg2 import sql

from api.auth import allow, tenant_scope
from api.tenancy import uploads_schema
from api.db import Conn
from api.services.audit import verify_chain

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(tenant_scope)],
)


@router.get("/log", dependencies=[Depends(allow("read_audit"))])
def audit_log(limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {}.audit_log").format(
                    sql.Identifier(uploads_schema())
                )
            )
            total = cur.fetchone()[0]
            cur.execute(
                sql.SQL(
                    "SELECT id, action, file_id, file_name, table_name, mode, performed_at, actor "
                    "FROM {}.audit_log ORDER BY performed_at DESC LIMIT %s OFFSET %s"
                ).format(sql.Identifier(uploads_schema())),
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
                    "actor": r[7],
                }
                for r in cur.fetchall()
            ]
    return {"total": total, "limit": limit, "offset": offset, "entries": entries}


@router.get("/verify", dependencies=[Depends(allow("read_audit"))])
def audit_verify() -> dict:
    """Recompute this tenant's audit hash chain (M3a, #107). ``intact`` is false
    if any row was changed, removed or inserted out of order."""
    with Conn() as conn:
        with conn.cursor() as cur:
            return verify_chain(cur)
