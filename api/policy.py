"""Data classification and audit retention (M7, #111; BR-35, BR-37; decision 7, ADR-0003).

Per-deployment configuration, as ADR-0003 says: ``DATA_CLASSIFICATION`` (default
``OFFICIAL: Sensitive``) and ``AUDIT_RETENTION_YEARS`` (default 7; confirm against the client's
records authority). Every API response carries the classification in ``X-Data-Classification``, so
anything saved from it can be marked.

Nothing in the application deletes audit rows or preserved originals: triggers reject it (0006, 0007).
Any purge is an operator action outside the app, and must keep audit rows for at least
``AUDIT_RETENTION_YEARS``.
"""

from __future__ import annotations

from fastapi import Response

from api.config import CLASSIFICATIONS, settings

HEADER = "X-Data-Classification"


def check_config(classification: str, retention_years: int) -> None:
    """Refuse to start with a classification the deployment can't honour, or a retention under a year."""
    if classification == "PROTECTED":
        raise RuntimeError(
            "DATA_CLASSIFICATION=PROTECTED is not supported. PROTECTED needs IRAP-assessed hosting and "
            "ISM PROTECTED controls (#49); the design target is OFFICIAL: Sensitive.")
    if classification not in CLASSIFICATIONS:
        raise RuntimeError(f"DATA_CLASSIFICATION must be one of {', '.join(CLASSIFICATIONS)}; got {classification!r}.")
    if retention_years < 1:
        raise RuntimeError(f"AUDIT_RETENTION_YEARS must be at least 1; got {retention_years}.")


def current() -> dict:
    return {"classification": settings.DATA_CLASSIFICATION, "auditRetentionYears": settings.AUDIT_RETENTION_YEARS}


def mark_classification(response: Response) -> None:
    """Router dependency: put the deployment's classification on the response."""
    response.headers[HEADER] = settings.DATA_CLASSIFICATION
