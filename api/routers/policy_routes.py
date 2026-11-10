"""The deployment's data classification and audit retention (M7, #111). See api/policy.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api import policy
from api.auth import tenant_scope

router = APIRouter(prefix="/api/policy", tags=["policy"],
                   dependencies=[Depends(tenant_scope), Depends(policy.mark_classification)])


@router.get("")
def get_policy() -> dict:
    """Open to any signed-in member, or a request with the shared key: it only says how to handle the data."""
    return policy.current()
