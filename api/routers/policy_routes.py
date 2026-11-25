"""The deployment's data classification and audit retention (M7, #111). See api/policy.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api import policy
from api.auth import tenant_scope
from typing import Any

router = APIRouter(prefix="/api/policy", tags=["policy"],
                   dependencies=[Depends(tenant_scope), Depends(policy.mark_classification)])


@router.get("")
def get_policy() -> dict[str, Any]:
    """Open to any signed-in member, or an anonymous local-dev request (#298): it only says how to handle the data."""
    return policy.current()
