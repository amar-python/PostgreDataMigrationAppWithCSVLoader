"""Approval and staged import endpoints (M6, #110; BR-32, BR-33, BR-34). See api/services/staged_import.py."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api import policy
from api.auth import allow, tenant_scope
from api.concurrency import import_slot
from api.config import settings
from api.db import Conn
from api.routers.csv_routes import HeaderRename
from api.services import staged_import
from api.services.type_confirmation import require_confirmed_types
from typing import Any
from psycopg2.extensions import cursor
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

router = APIRouter(prefix="/api/csv/uploads", tags=["import"], dependencies=[Depends(tenant_scope), Depends(policy.mark_classification)])


class StageRequest(BaseModel):
    fileName: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    types: list[str] | None = None
    typesConfirmed: bool = Field(
        default=False,
        description="A person confirmed `types` (#195); the import records it in the registry. "
                    "A server started with API_REQUIRE_TYPE_CONFIRMATION=true answers 422 unless this is true "
                    "and `types` is sent (#242).")
    headerMapping: list[HeaderRename] | None = Field(default=None, max_length=1000)
    contentBase64: str | None = None  # the file's bytes as uploaded, kept as the preserved original (#185)


class SubmitRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ApprovalRequest(BaseModel):
    decision: str
    reason: str | None = Field(default=None, max_length=2000)


def _run(fn: Callable[..., T], *args: Any, commit: bool = True) -> T:
    """Run one workflow step in one transaction, answering WorkflowError with its status."""
    with Conn() as conn:
        with conn.cursor() as cur:
            try:
                result = fn(cur, *args)
            except staged_import.WorkflowError as exc:
                conn.rollback()
                raise HTTPException(exc.status, {"message": str(exc), **exc.extra}) from None
        if commit:
            conn.commit()
    return result


@router.post("", dependencies=[Depends(allow("upload")), Depends(import_slot)])
def stage(req: StageRequest) -> dict[str, Any]:
    """Store an upload for review; nothing is imported. Answers 409 for an exact duplicate, 422 for a bad file."""
    if len(req.content.encode("utf-8")) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    original = None
    if req.contentBase64 is not None:
        if len(req.contentBase64) > settings.MAX_UPLOAD_BYTES * 4 // 3 + 4:
            raise HTTPException(413, "File too large")
        try:
            original = base64.b64decode(req.contentBase64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "contentBase64 is not valid base64") from None
    if req.typesConfirmed and not req.types:
        raise HTTPException(422, "typesConfirmed requires the confirmed types to be sent in 'types'")
    require_confirmed_types(req.types, req.typesConfirmed)  # #242, when the server is set to require it
    mapping = [m.model_dump() for m in req.headerMapping] if req.headerMapping else None
    result = _run(staged_import.stage, req.fileName, req.content, req.types, mapping, original, req.typesConfirmed)
    if result["status"] == "duplicate_file":
        raise HTTPException(409, result)
    if result["status"] != "staged":
        raise HTTPException(422, result)
    return result


@router.get("/{upload_id}/workflow", dependencies=[Depends(allow("read_rows"))])
def workflow(upload_id: int) -> dict[str, Any]:
    """The upload's state, its latest submission, approval and import, and the history of each."""
    def read(cur: cursor, uid: int) -> dict[str, Any]:
        st = staged_import.state_of(cur, uid)
        if st is None:
            raise staged_import.WorkflowError(404, "No such upload")
        return {**st, "history": staged_import.history(cur, uid)}
    return _run(read, upload_id, commit=False)


@router.post("/{upload_id}/submit", dependencies=[Depends(allow("submit_import"))])
def submit(upload_id: int, req: SubmitRequest | None = None) -> dict[str, Any]:
    return _run(staged_import.submit, upload_id, req.note if req else None)


@router.post("/{upload_id}/approval", dependencies=[Depends(allow("approve_import"))])
def approval(upload_id: int, req: ApprovalRequest, session: dict[str, Any] | None = Depends(tenant_scope)) -> dict[str, Any]:
    return _run(staged_import.decide_approval, upload_id, req.decision, req.reason, session)


@router.post("/{upload_id}/import", dependencies=[Depends(allow("run_import")), Depends(import_slot)])
def run_import(upload_id: int, idempotency_key: str = Header(default="", alias="Idempotency-Key"),
               session: dict[str, Any] | None = Depends(tenant_scope)) -> dict[str, Any]:
    """Import an approved upload in one transaction. Send an Idempotency-Key and reuse it to retry."""
    try:
        return staged_import.import_upload(upload_id, idempotency_key, session)
    except staged_import.WorkflowError as exc:
        raise HTTPException(exc.status, {"message": str(exc), **exc.extra}) from None
