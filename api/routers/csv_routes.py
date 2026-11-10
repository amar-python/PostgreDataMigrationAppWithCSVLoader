"""CSV pipeline endpoints — preview, upload, files list, table rows, error report."""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg2 import sql
from pydantic import BaseModel, Field

from api import policy
from api.auth import allow, tenant_scope
from api.config import settings
from api.tenancy import uploads_schema
from api.db import Conn
from api.services.audit import coerce_file_id, record_audit, write_audit
from api.services.csv_parse import build_preview
from api.services.dynamic_loader import upload_dynamic
from api.services.originals import record_upload
from api.services.reports import like_pattern
from api.services.staged_import import derive_state, state_columns, state_join
from api.services.te_loader import match_te_table, upload_te

logger = logging.getLogger(__name__)

# BUG-035: auth is applied here (per-router) instead of at app level in
# api/main.py, so /api/health can stay unauthenticated for external monitoring.
router = APIRouter(
    prefix="/api/csv",
    tags=["csv"],
    dependencies=[Depends(tenant_scope), Depends(policy.mark_classification)],
)


class PreviewRequest(BaseModel):
    fileName: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class HeaderRename(BaseModel):
    original: str = Field(max_length=255)
    renamed: str = Field(default="", max_length=128)  # blank keeps the original


class UploadRequest(BaseModel):
    fileName: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    types: list[str] | None = None
    overwrite: bool = False
    mode: str = "dynamic"  # "dynamic" | "te"
    targetTable: str | None = None  # required when mode == "te"
    headerMapping: list[HeaderRename] | None = Field(default=None, max_length=1000)  # dynamic mode only (#186)
    # The file's bytes as the browser read them, base64. Kept as the preserved
    # original so its hash matches the uploader's copy; `content` is still what loads (#185).
    contentBase64: str | None = None
    # True when a person reviewed `types` before this call (dynamic mode only, #195).
    typesConfirmed: bool = False


@router.post("/preview", dependencies=[Depends(allow("preview"))])
def preview(req: PreviewRequest) -> dict:
    if len(req.content.encode("utf-8")) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    # BUG-025: mirror the try/except contract that /upload has. An unexpected
    # parse error (regex catastrophic backtracking, memory error, etc.) must
    # not surface as a raw 500 to the frontend.
    try:
        result = build_preview(req.content)
    except Exception as exc:  # noqa: BLE001 — surface any parser failure as structured JSON
        logger.warning("CSV preview parse failed for %r: %s", req.fileName, exc)
        return {
            "status": "invalid_structure",
            "reason": "parse_failed",
            "message": "The CSV couldn't be parsed. Check the file's structure and try again.",
        }
    if result.get("status") == "ok":
        # Suggest a T&E table if the columns fit one (drives the mode picker in the UI)
        try:
            result["teTableMatch"] = match_te_table(result["columns"])
        except Exception:  # noqa: BLE001 — T&E match is best-effort, never block the preview
            result["teTableMatch"] = None
    return result


def _decode_original(b64: str | None) -> bytes | None:
    if b64 is None:
        return None
    # base64 inflates by 4/3; refuse before decoding rather than after.
    if len(b64) > settings.MAX_UPLOAD_BYTES * 4 // 3 + 4:
        raise HTTPException(413, "File too large")
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "contentBase64 is not valid base64") from None


@router.post("/upload", dependencies=[Depends(allow("upload"))])
def upload(req: UploadRequest, session: dict | None = Depends(tenant_scope)) -> dict:
    if len(req.content.encode("utf-8")) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    original = _decode_original(req.contentBase64)
    if req.mode == "te":
        if not req.targetTable:
            raise HTTPException(422, "targetTable is required when mode is 'te'")
        if req.headerMapping:
            # T&E columns must match the fixed schema exactly; a rename could
            # only be ignored, which is the silent failure #186 describes.
            raise HTTPException(422, "headerMapping is only supported in 'dynamic' mode")
        if req.typesConfirmed:
            raise HTTPException(422, "typesConfirmed is only supported in 'dynamic' mode")
        result = upload_te(req.fileName, req.content, req.targetTable, session=session)
    elif req.mode == "dynamic":
        if req.typesConfirmed and not req.types:
            raise HTTPException(422, "typesConfirmed requires the confirmed types to be sent in 'types'")
        mapping = [m.model_dump() for m in req.headerMapping] if req.headerMapping else None
        result = upload_dynamic(req.fileName, req.content, req.types, req.overwrite,
                                session=session, header_mapping=mapping, types_confirmed=req.typesConfirmed)
    else:
        raise HTTPException(422, f"Unknown mode '{req.mode}' — use 'dynamic' or 'te'")

    # M3b (#107): keep the original and its outcome, whatever the outcome was.
    flags = result.pop("_duplicateFlags", None)
    upload_id = record_upload(req.fileName, req.content, req.mode, result, original=original, flags=flags)
    result["uploadId"] = None if upload_id is None else str(upload_id)

    # O-04: record the load so audit_log covers creations, not just deletions.
    # Only a genuine load is audited: "duplicate_file" and "error" outcomes
    # changed nothing, so logging them would make the trail read as if data had
    # landed when it had not.
    if result.get("status") == "ok":
        record_audit(
            action="upload",
            file_id=coerce_file_id(result.get("fileId")),
            file_name=req.fileName,
            table_name=result.get("tableName"),
            mode=req.mode,
        )
    return result


@router.get("/files", dependencies=[Depends(allow("list_files"))])
def list_files() -> list[dict]:
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT f.id, f.file_name, f.table_name, f.mode, f.row_count, f.column_names, f.created_at, "
                    "f.total_rows, f.duplicate_rows_skipped, f.failed_rows, u.uploader, u.id, f.types_provenance "
                    "FROM {s}.csv_files f LEFT JOIN LATERAL (SELECT x.uploader, x.id FROM {s}.uploads x "
                    "  WHERE x.csv_file_id = f.id "
                    "     OR x.id = (SELECT i.upload_id FROM {s}.imports i WHERE i.csv_file_id = f.id) "
                    "  ORDER BY x.id DESC LIMIT 1) u ON true "
                    "ORDER BY f.created_at DESC, f.id DESC"
                ).format(s=sql.Identifier(uploads_schema()))
            )
            return [
                {
                    "id": str(r[0]),
                    "file_name": r[1],
                    "table_name": r[2],
                    "mode": r[3],
                    "row_count": r[4],
                    "column_names": r[5],
                    "created_at": r[6].isoformat(),
                    "total_rows": r[7],
                    "duplicate_rows_skipped": r[8],
                    "failed_rows": r[9],
                    "uploader": r[10],
                    "upload_id": None if r[11] is None else str(r[11]),
                    "types_provenance": r[12],
                }
                for r in cur.fetchall()
            ]


_UPLOAD_STATUSES = ("staged", "imported", "partly_imported", "failed", "duplicate", "rejected")
# The first logged error, else the first warning: why a failed, rejected, duplicate or partly imported upload
# came out as it did (M7, #111; BR-35). Staged and fully imported uploads have none.
_FAILURE_REASON = (
    "CASE WHEN u.status IN ('failed', 'rejected', 'duplicate', 'partly_imported') THEN "
    "(SELECT t.l ->> 'message' FROM jsonb_array_elements(COALESCE(u.logs, '[]'::jsonb)) WITH ORDINALITY t(l, n) "
    " WHERE t.l ->> 'level' IN ('error', 'warn') ORDER BY (t.l ->> 'level' = 'error') DESC, t.n LIMIT 1) END"
)


@router.get("/uploads", dependencies=[Depends(allow("list_files"))])
def list_uploads(
    limit: int = 100,
    offset: int = 0,
    status: str | None = Query(None, description="one of " + ", ".join(_UPLOAD_STATUSES)),
    uploader: str | None = None,
    file: str | None = Query(None, description="file name contains this text, ignoring case"),
    date_from: datetime | None = Query(None, alias="from", description="uploaded on or after this time"),
    date_to: datetime | None = Query(None, alias="to", description="uploaded before this time"),
) -> list[dict]:
    """Every upload attempt and its outcome, newest first (M3b, #107; BR-23), filterable (M7, #111; BR-35).

    ``state`` is the M6 workflow state; ``failureReason`` says why an attempt didn't import cleanly.
    """
    if status is not None and status not in _UPLOAD_STATUSES:
        raise HTTPException(422, f"Unknown status {status!r}; expected one of {list(_UPLOAD_STATUSES)}")
    where, params = [], []
    for clause, value in (("u.status = %s", status), ("u.uploader = %s", uploader),
                          ("u.file_name ILIKE %s ESCAPE '\\'", None if file is None else like_pattern(file)),
                          ("u.uploaded_at >= %s", date_from), ("u.uploaded_at < %s", date_to)):
        if value is not None:
            where.append(sql.SQL(clause))
            params.append(value)
    clause = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL("")
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL(
            "SELECT u.id, u.file_name, u.sha256, u.byte_size, u.uploader, u.mode, u.status, u.total_rows, "
            "u.imported_rows, u.failed_rows, u.csv_file_id, u.uploaded_at, {reason}, {cols} "
            "FROM {s}.uploads u {join}{where} ORDER BY u.id DESC LIMIT %s OFFSET %s"
        ).format(reason=sql.SQL(_FAILURE_REASON), cols=state_columns(), s=sql.Identifier(uploads_schema()),
                 join=state_join(), where=clause), [*params, max(1, min(limit, 500)), max(0, offset)])
        keys = ("id", "file_name", "sha256", "byte_size", "uploader", "mode", "status", "total_rows",
                "imported_rows", "failed_rows", "csv_file_id", "uploaded_at", "failure_reason")
        out = []
        for r in cur.fetchall():
            u = dict(zip(keys, r[:13]))
            u["state"] = derive_state(u["status"], r[13], r[14], r[15])
            out.append(u)
    for u in out:
        u["id"] = str(u["id"])
        u["csv_file_id"] = None if u["csv_file_id"] is None else str(u["csv_file_id"])
        u["uploaded_at"] = u["uploaded_at"].isoformat()
    return out


@router.get("/uploads/{upload_id}", dependencies=[Depends(allow("list_files"))])
def upload_detail(upload_id: int) -> dict:
    """One upload's outcome, why its rows failed, and its step log (M3c, #107).
    Stored on the server, so any session in the tenant can read them."""
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL(
            "SELECT u.status, u.total_rows, u.imported_rows, u.failed_rows, u.row_errors, u.logs, u.uploader, "
            "u.file_name, {cols} FROM {s}.uploads u {join} WHERE u.id = %s"
        ).format(cols=state_columns(), s=sql.Identifier(uploads_schema()), join=state_join()), (upload_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "No such upload")
    keys = ("status", "totalRows", "importedRows", "failedRows", "rowErrors", "logs", "uploader", "fileName")
    return {"id": str(upload_id), **dict(zip(keys, row[:8])), "state": derive_state(row[0], *row[8:11])}


@router.get("/uploads/{upload_id}/original", dependencies=[Depends(allow("read_rows"))])
def upload_original(upload_id: int) -> Response:
    """The file exactly as it was uploaded (M3b; BR-24)."""
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL(
            "SELECT u.file_name, u.sha256, b.content FROM {s}.uploads u "
            "JOIN {s}.upload_blobs b ON b.upload_id = u.id WHERE u.id = %s"
        ).format(s=sql.Identifier(uploads_schema())), (upload_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "No such upload")
    name, digest, content = row
    return Response(bytes(content), media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "X-Content-SHA256": digest, policy.HEADER: settings.DATA_CLASSIFICATION})


@router.get("/tables/{table_name}/rows", dependencies=[Depends(allow("read_rows"))])
def table_rows(table_name: str, limit: int = 50) -> dict:
    if not table_name.startswith("csv_") or len(table_name) > 64:
        raise HTTPException(422, "Invalid table name")
    limit = max(1, min(limit, 200))
    with Conn() as conn:
        with conn.cursor() as cur:
            # Only serve tables that are registered uploads
            cur.execute(
                sql.SQL("SELECT 1 FROM {}.csv_files WHERE table_name = %s").format(
                    sql.Identifier(uploads_schema())
                ),
                (table_name,),
            )
            if cur.fetchone() is None:
                raise HTTPException(404, "Table not found")
            cur.execute(
                sql.SQL("SELECT * FROM {}.{} ORDER BY _id LIMIT %s").format(
                    sql.Identifier(uploads_schema()), sql.Identifier(table_name)
                ),
                (limit,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    # JSON-safe: stringify anything exotic (dates, Decimals)
    for row in rows:
        for k, v in row.items():
            if v is not None and not isinstance(v, (str, int, float, bool)):
                row[k] = str(v)
    return {"rows": rows}


@router.delete("/files/{file_id}", dependencies=[Depends(allow("delete_file"))])
def delete_file(file_id: int) -> dict:
    if not settings.allow_destructive:
        raise HTTPException(
            403,
            "Destructive operations are disabled. "
            "Set API_ALLOW_DESTRUCTIVE=true to enable DELETE.",
        )
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT table_name, mode, file_name FROM {}.csv_files WHERE id = %s"
                ).format(sql.Identifier(uploads_schema())),
                (file_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, "File not found")
            table_name, mode, file_name = row
            if mode == "dynamic":
                # Schema whitelist: only drop tables that live in the uploads schema.
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                    """,
                    (uploads_schema(), table_name),
                )
                if cur.fetchone() is not None:
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                            sql.Identifier(uploads_schema()),
                            sql.Identifier(table_name),
                        )
                    )
            cur.execute(
                sql.SQL("DELETE FROM {}.csv_files WHERE id = %s").format(
                    sql.Identifier(uploads_schema())
                ),
                (file_id,),
            )
            # Persist audit record so deletions are traceable after the table is
            # gone. Shares the single writer in api/services/audit.py (O-04), and
            # rides this transaction so the row and the delete commit together.
            write_audit(cur, "delete", file_id, file_name, table_name, mode)
            conn.commit()
            return {"status": "ok", "deleted": file_id}
