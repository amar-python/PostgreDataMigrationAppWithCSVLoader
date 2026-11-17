"""The optional rule that a dynamic-mode table is only created from column types a person confirmed (#242)."""

from __future__ import annotations

from fastapi import HTTPException

from api.config import settings


def require_confirmed_types(types: list[str] | None, confirmed: bool) -> None:
    """422 when API_REQUIRE_TYPE_CONFIRMATION is on and the request doesn't carry confirmed types.

    Both dynamic entry points call this before doing any work, so a refused request creates nothing.
    """
    if settings.REQUIRE_TYPE_CONFIRMATION and not (types and confirmed):
        raise HTTPException(
            422,
            "This server requires confirmed column types: send the types a person confirmed in 'types' "
            "together with 'typesConfirmed': true. Previewing the file (POST /api/csv/preview) shows the inferred types.",
        )
