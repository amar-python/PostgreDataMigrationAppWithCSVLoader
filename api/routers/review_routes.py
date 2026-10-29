"""Review endpoints for stored uploads (M4a, #108; BR-25, BR-26, BR-27). See api/services/review.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import allow, tenant_scope
from api.db import Conn
from api.services import review

router = APIRouter(prefix="/api/csv/uploads", tags=["review"], dependencies=[Depends(tenant_scope)])


class DecisionRequest(BaseModel):
    decision: str
    reason: str


class EditRequest(BaseModel):
    value: str
    reason: str


def _run(fn, *args, commit: bool = False):
    with Conn() as conn:
        with conn.cursor() as cur:
            try:
                result = fn(cur, *args)
            except review.ReviewError as exc:
                conn.rollback()
                raise HTTPException(exc.status, str(exc)) from None
        if commit:
            conn.commit()
    return result


@router.get("/{upload_id}/rows", dependencies=[Depends(allow("read_rows"))])
def rows(upload_id: int, offset: int = 0, limit: int = 100) -> dict:
    """One page of every stored row, with current values, validation errors and decisions."""
    return _run(review.page, upload_id, offset, limit)


@router.put("/{upload_id}/rows/{row_number}/decision", dependencies=[Depends(allow("review_rows"))])
def decide(upload_id: int, row_number: int, req: DecisionRequest) -> dict:
    return _run(review.decide, upload_id, row_number, req.decision, req.reason, commit=True)


@router.put("/{upload_id}/rows/{row_number}/cells/{column}", dependencies=[Depends(allow("review_rows"))])
def edit(upload_id: int, row_number: int, column: str, req: EditRequest) -> dict:
    return _run(review.edit, upload_id, row_number, column, req.value, req.reason, commit=True)


@router.get("/{upload_id}/rows/{row_number}/history", dependencies=[Depends(allow("read_rows"))])
def history(upload_id: int, row_number: int) -> list[dict]:
    return _run(review.history, upload_id, row_number)
