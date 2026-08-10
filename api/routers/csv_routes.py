"""CSV pipeline endpoints — preview, upload, files list, table rows, error report."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import sql
from pydantic import BaseModel, Field

from api.auth import require_api_key
from api.config import settings
from api.db import Conn
from api.services.csv_parse import build_preview
from api.services.dynamic_loader import upload_dynamic
from api.services.te_loader import match_te_table, upload_te

# BUG-035: auth is applied here (per-router) instead of at app level in
# api/main.py, so /api/health can stay unauthenticated for external monitoring.
router = APIRouter(
    prefix="/api/csv",
    tags=["csv"],
    dependencies=[Depends(require_api_key)],
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


@router.post("/preview")
def preview(req: PreviewRequest) -> dict:
    if len(req.content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    # BUG-025: mirror the try/except contract that /upload has. An unexpected
    # parse error (regex catastrophic backtracking, memory error, etc.) must
    # not surface as a raw 500 to the frontend.
    try:
        result = build_preview(req.content)
    except Exception as exc:  # noqa: BLE001 — surface any parser failure as structured JSON
        return {
            "status": "invalid_structure",
            "reason": "parse_failed",
            "message": f"The CSV couldn't be parsed: {str(exc)[:200]}",
        }
    if result.get("status") == "ok":
        # Suggest a T&E table if the columns fit one (drives the mode picker in the UI)
        try:
            result["teTableMatch"] = match_te_table(result["columns"])
        except Exception:  # noqa: BLE001 — T&E match is best-effort, never block the preview
            result["teTableMatch"] = None
    return result


@router.post("/upload")
def upload(req: UploadRequest) -> dict:
    if len(req.content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    if req.mode == "te":
        if not req.targetTable:
            raise HTTPException(422, "targetTable is required when mode is 'te'")
        return upload_te(req.fileName, req.content, req.targetTable)
    if req.mode != "dynamic":
        raise HTTPException(422, f"Unknown mode '{req.mode}' — use 'dynamic' or 'te'")
    return upload_dynamic(req.fileName, req.content, req.types, req.overwrite)


@router.get("/files")
def list_files() -> list[dict]:
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT id, file_name, table_name, mode, row_count, column_names, created_at "
                    "FROM {}.csv_files ORDER BY created_at DESC"
                ).format(sql.Identifier(settings.UPLOADS_SCHEMA))
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
                }
                for r in cur.fetchall()
            ]


@router.get("/tables/{table_name}/rows")
def table_rows(table_name: str, limit: int = 50) -> dict:
    if not table_name.startswith("csv_") or len(table_name) > 64:
        raise HTTPException(422, "Invalid table name")
    limit = max(1, min(limit, 200))
    with Conn() as conn:
        with conn.cursor() as cur:
            # Only serve tables that are registered uploads
            cur.execute(
                sql.SQL("SELECT 1 FROM {}.csv_files WHERE table_name = %s").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA)
                ),
                (table_name,),
            )
            if cur.fetchone() is None:
                raise HTTPException(404, "Table not found")
            cur.execute(
                sql.SQL("SELECT * FROM {}.{} ORDER BY _id LIMIT %s").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA), sql.Identifier(table_name)
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


@router.delete("/files/{file_id}")
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
                ).format(sql.Identifier(settings.UPLOADS_SCHEMA)),
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
                    (settings.UPLOADS_SCHEMA, table_name),
                )
                if cur.fetchone() is not None:
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                            sql.Identifier(settings.UPLOADS_SCHEMA),
                            sql.Identifier(table_name),
                        )
                    )
            cur.execute(
                sql.SQL("DELETE FROM {}.csv_files WHERE id = %s").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA)
                ),
                (file_id,),
            )
            # Persist audit record so deletions are traceable after the table is gone.
            cur.execute(
                sql.SQL(
                    "INSERT INTO {}.audit_log "
                    "(action, file_id, file_name, table_name, mode) "
                    "VALUES ('delete', %s, %s, %s, %s)"
                ).format(sql.Identifier(settings.UPLOADS_SCHEMA)),
                (file_id, file_name, table_name, mode),
            )
            conn.commit()
            return {"status": "ok", "deleted": file_id}
