"""CSV pipeline endpoints — preview, upload, files list, table rows, error report."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from psycopg2 import sql
from pydantic import BaseModel, Field

from api.config import settings
from api.db import Conn
from api.services.csv_parse import build_preview
from api.services.dynamic_loader import upload_dynamic
from api.services.te_loader import match_te_table, upload_te

router = APIRouter(prefix="/api/csv", tags=["csv"])


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
    result = build_preview(req.content)
    if result.get("status") == "ok":
        # Suggest a T&E table if the columns fit one (drives the mode picker in the UI)
        result["teTableMatch"] = match_te_table(result["columns"])
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


CSV_TABLE_NAME_RE = re.compile(r"^csv_[0-9a-f]{16}$")


@router.get("/tables/{table_name}/rows")
def table_rows(table_name: str, limit: int = 50) -> dict:
    if not CSV_TABLE_NAME_RE.fullmatch(table_name):
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
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT table_name, mode FROM {}.csv_files WHERE id = %s"
                ).format(sql.Identifier(settings.UPLOADS_SCHEMA)),
                (file_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, "File not found")
            table_name, mode = row
            if mode == "dynamic":
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(settings.UPLOADS_SCHEMA), sql.Identifier(table_name)
                    )
                )
            cur.execute(
                sql.SQL("DELETE FROM {}.csv_files WHERE id = %s").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA)
                ),
                (file_id,),
            )
        conn.commit()
    return {"status": "ok", "deleted": file_id}
