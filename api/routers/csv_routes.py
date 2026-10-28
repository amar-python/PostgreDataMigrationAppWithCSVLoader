"""CSV pipeline endpoints — preview, upload, files list, table rows, error report."""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2 import sql
from pydantic import BaseModel, Field

from api.auth import allow, tenant_scope
from api.config import settings
from api.tenancy import uploads_schema
from api.db import Conn
from api.services.audit import coerce_file_id, record_audit, write_audit
from api.services.csv_parse import build_preview
from api.services.dynamic_loader import upload_dynamic
from api.services.originals import record_upload
from api.services.te_loader import match_te_table, upload_te

logger = logging.getLogger(__name__)

# BUG-035: auth is applied here (per-router) instead of at app level in
# api/main.py, so /api/health can stay unauthenticated for external monitoring.
router = APIRouter(
    prefix="/api/csv",
    tags=["csv"],
    dependencies=[Depends(tenant_scope)],
)


class PreviewRequest(BaseModel):
    fileName: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class UploadRequest(BaseModel):
    fileName: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    types: list[str] | None = None
    overwrite: bool = False
    mode: str = "dynamic"  # "dynamic" | "te"
    targetTable: str | None = None  # required when mode == "te"


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


@router.post("/upload", dependencies=[Depends(allow("upload"))])
def upload(req: UploadRequest) -> dict:
    if len(req.content.encode("utf-8")) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    if req.mode == "te":
        if not req.targetTable:
            raise HTTPException(422, "targetTable is required when mode is 'te'")
        result = upload_te(req.fileName, req.content, req.targetTable)
    elif req.mode == "dynamic":
        result = upload_dynamic(req.fileName, req.content, req.types, req.overwrite)
    else:
        raise HTTPException(422, f"Unknown mode '{req.mode}' — use 'dynamic' or 'te'")

    # M3b (#107): keep the original and its outcome, whatever the outcome was.
    upload_id = record_upload(req.fileName, req.content, req.mode, result)
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
                    "f.total_rows, f.duplicate_rows_skipped, f.failed_rows, u.uploader, u.id "
                    "FROM {s}.csv_files f LEFT JOIN LATERAL (SELECT uploader, id FROM {s}.uploads "
                    "  WHERE csv_file_id = f.id ORDER BY id DESC LIMIT 1) u ON true "
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
                }
                for r in cur.fetchall()
            ]


@router.get("/uploads", dependencies=[Depends(allow("list_files"))])
def list_uploads(limit: int = 100, offset: int = 0) -> list[dict]:
    """Every upload attempt and its outcome, newest first (M3b, #107; BR-23)."""
    with Conn() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL(
            "SELECT id, file_name, sha256, byte_size, uploader, mode, status, total_rows, imported_rows, "
            "failed_rows, csv_file_id, uploaded_at FROM {}.uploads ORDER BY id DESC LIMIT %s OFFSET %s"
        ).format(sql.Identifier(uploads_schema())), (max(1, min(limit, 500)), max(0, offset)))
        keys = ("id", "file_name", "sha256", "byte_size", "uploader", "mode", "status", "total_rows",
                "imported_rows", "failed_rows", "csv_file_id", "uploaded_at")
        out = [dict(zip(keys, r)) for r in cur.fetchall()]
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
            "SELECT status, total_rows, imported_rows, failed_rows, row_errors, logs, uploader, file_name "
            "FROM {}.uploads WHERE id = %s").format(sql.Identifier(uploads_schema())), (upload_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "No such upload")
    keys = ("status", "totalRows", "importedRows", "failedRows", "rowErrors", "logs", "uploader", "fileName")
    return {"id": str(upload_id), **dict(zip(keys, row))}


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
        "X-Content-SHA256": digest})


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
