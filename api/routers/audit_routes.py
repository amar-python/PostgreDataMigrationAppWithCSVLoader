"""BUG-041: csv_uploads.audit_log was write-only (populated by delete_file in
csv_routes.py, never read back). This router surfaces it as a paginated,
API-key-guarded feed so the trail is actually consultable.

O-04 update: the table is no longer delete-only. Successful uploads also write a
row, through the shared writer in api/services/audit.py, so this feed now covers
creations as well as destructions. Integration coverage lives in
tests/system/test_api_integration.py::AuditLogTrail."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg2 import sql

from api import policy
from api.auth import allow, tenant_scope
from api.tenancy import uploads_schema
from api.db import Conn
from api.config import settings
from api.services.audit import VALID_ACTIONS, verify_chain
from api.services.reports import csv_text, like_pattern

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(tenant_scope), Depends(policy.mark_classification)],
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


_EVENT_COLUMNS = ("id", "performed_at", "actor", "action", "file_id", "file_name", "table_name", "mode",
                  "before_value", "after_value")


@router.get("/events", dependencies=[Depends(allow("read_audit"))], response_model=None)
def audit_events(
    actor: str | None = None,
    action: str | None = None,
    file: str | None = Query(None, description="file name contains this text, ignoring case"),
    table: str | None = Query(None, description="table name contains this text, ignoring case"),
    date_from: datetime | None = Query(None, alias="from", description="on or after this time"),
    date_to: datetime | None = Query(None, alias="to", description="before this time"),
    limit: int | None = None,
    offset: int = 0,
    format: str = Query("json", pattern="^(json|csv)$"),
) -> Response | dict:
    """A filtered report of this tenant's audit log, newest first (M7, #111; BR-35).

    Filters combine with AND. ``format=csv`` downloads the matching rows (up to API_MAX_ROWS) with spreadsheet
    formulas neutralised; JSON pages at 100 by default and 1000 at most. Both carry the classification.
    """
    if action is not None and action not in VALID_ACTIONS:
        raise HTTPException(422, f"Unknown action {action!r}; expected one of {sorted(VALID_ACTIONS)}")
    where, params = [], []
    for column, value in (("actor", actor), ("action", action)):
        if value is not None:
            where.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            params.append(value)
    for column, value in (("file_name", file), ("table_name", table)):
        if value is not None:
            where.append(sql.SQL("{} ILIKE %s ESCAPE '\\'").format(sql.Identifier(column)))
            params.append(like_pattern(value))
    if date_from is not None:
        where.append(sql.SQL("performed_at >= %s"))
        params.append(date_from)
    if date_to is not None:
        where.append(sql.SQL("performed_at < %s"))
        params.append(date_to)
    clause = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL("")
    cap = settings.MAX_ROWS if format == "csv" else 1000
    limit = max(1, min(limit if limit is not None else (cap if format == "csv" else 100), cap))
    offset = max(0, offset)
    schema = sql.Identifier(uploads_schema())
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}.audit_log{}").format(schema, clause), params)
        total = cur.fetchone()[0]
        cur.execute(sql.SQL("SELECT {} FROM {}.audit_log{} ORDER BY id DESC LIMIT %s OFFSET %s").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in _EVENT_COLUMNS), schema, clause), [*params, limit, offset])
        rows = cur.fetchall()
    marking = {policy.HEADER: settings.DATA_CLASSIFICATION}
    if format == "csv":
        table_rows = [[r[0], r[1].isoformat(), *r[2:8], *(None if v is None else json.dumps(v) for v in r[8:])]
                      for r in rows]
        text = csv_text(list(_EVENT_COLUMNS), table_rows)
        return Response(text, media_type="text/csv", headers={
            **marking, "Content-Disposition": 'attachment; filename="audit-events.csv"',
            "X-Total-Count": str(total)})
    entries = [{"id": str(r[0]), "performedAt": r[1].isoformat(), "actor": r[2], "action": r[3], "fileId": r[4],
                "fileName": r[5], "tableName": r[6], "mode": r[7], "before": r[8], "after": r[9]} for r in rows]
    return {"classification": settings.DATA_CLASSIFICATION, "total": total, "limit": limit, "offset": offset,
            "entries": entries}
