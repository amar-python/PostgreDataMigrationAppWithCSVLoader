"""Outcome rules ported from csv-table-hub-main/src/lib/job-outcome.ts. Pure functions: no Streamlit, no API.

Overwrite no longer exists (M5) and Stop/cancel is gone, so their rules are not here.
"""

UPLOADS_LIMIT = 500  # the most uploads GET /api/csv/uploads returns (the server caps it)

STATUS_LABELS: dict[str, str] = {
    "imported": "Imported",
    "partly_imported": "Partly imported",
    "failed": "Failed",
    "rejected": "Rejected",
    "duplicate": "Duplicate",
    "staged": "Staged",
}

_ATTENTION = ("partly_imported", "failed", "rejected")


def needs_attention(status: str) -> bool:
    """An upload attempt a reviewer should look at: it failed outright or lost some rows (#187)."""
    return status in _ATTENTION


def failed_rows_note(u: dict) -> str | None:
    """"51 of 171 rows failed" for an upload with failures (#123); None when nothing failed."""
    failed = u.get("failed_rows")
    if not failed:
        return None
    total = u.get("total_rows")
    return f"{failed} of {total} rows failed" if total else f"{failed} rows failed"


def types_provenance_note(u: dict) -> str | None:
    """Says so when a table's column types were never confirmed by a person (#195); else None."""
    if u.get("types_provenance") == "inferred_unconfirmed":
        return "Column types were not confirmed by a person."
    return None


def describe_result(file_name: str, res: dict) -> tuple[str, str]:
    """(level, message) for one file's upload result: level is "success", "warning" or "error"."""
    status = res.get("status")
    if status == "ok":
        inserted = res.get("insertedRows")
        total = res.get("totalRows")
        failed = res.get("failedRows")
        msg = f"{file_name}: {inserted} of {total} rows imported"
        if failed:
            return "warning", f"{msg} · {failed} failed"
        return "success", msg
    if status == "duplicate_file":
        return "warning", f"{file_name}: already imported as {res.get('existingFileName')}; nothing was changed."
    # invalid_structure, error, and anything unknown: say why, never raise.
    detail = res.get("message") or res.get("reason") or status
    return "error", f"{file_name}: {detail}"
