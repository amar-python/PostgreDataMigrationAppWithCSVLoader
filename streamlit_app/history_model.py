"""What the import-history screen (#253) asks the API and what it shows, decided without Streamlit.

The history is the server's own record (`GET /api/csv/uploads`), so it belongs to the tenant and survives
browsers and devices; the React screen kept it in the browser's `localStorage` (and that is the leak #176 was).
A second view shows the server's audit events (`GET /api/audit/events`, BR-35). Text from a file goes through
`review_model.literal`, as on the review screen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

import review_model as m

PAGE_SIZE = 25  # imports a page of the list shows
EXPORT_PAGE = 500  # the most the API gives in one request
EXPORT_LIMIT = 5_000  # the most one report holds; above it the report says it is cut short
EVENTS_PAGE = 100  # audit events a page shows (the API's default)
ERROR_ROWS_SHOWN = 200  # failed rows shown at once; the report has all the server kept

STATUSES = [
    ("", "All statuses"),
    ("imported", "Imported"),
    ("partly_imported", "Partly imported"),
    ("failed", "Failed"),
    ("rejected", "Rejected"),
    ("duplicate", "Duplicate"),
    ("staged", "Staged"),
]

# The actions the API records (api/services/audit.py VALID_ACTIONS). A test fails if the two drift apart.
AUDIT_ACTIONS = (
    "upload",
    "delete",
    "password_reset",
    "row_decision",
    "cell_edit",
    "submit",
    "approve",
    "reject",
    "import",
)


# ── what is asked ───────────────────────────────────────────────────────────────────────────


def day_start(day: date) -> str:
    """Midnight UTC at the start of `day`, as the API takes a time."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()


def _range(params: dict, date_from: date | None, date_to: date | None) -> None:
    if date_from:
        params["from"] = day_start(date_from)
    if date_to:  # the whole of that day: up to, not including, the next midnight
        params["to"] = day_start(date_to + timedelta(days=1))


def uploads_params(
    file: str = "",
    status: str = "",
    uploader: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = PAGE_SIZE + 1,
    offset: int = 0,
) -> dict:
    """The query for the list of imports. Blank filters are left out. One more than a page is asked for, so
    the screen knows whether there is a next page without a count (the API gives none)."""
    params: dict = {"limit": limit, "offset": offset}
    for key, value in (("file", file), ("status", status), ("uploader", uploader)):
        if value and value.strip():
            params[key] = value.strip()
    _range(params, date_from, date_to)
    return params


def events_params(
    actor: str = "",
    action: str = "",
    file: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = EVENTS_PAGE,
    offset: int = 0,
    fmt: str = "json",
) -> dict:
    params: dict = {"limit": limit, "offset": offset}
    for key, value in (("actor", actor), ("action", action), ("file", file)):
        if value and value.strip():
            params[key] = value.strip()
    _range(params, date_from, date_to)
    if fmt != "json":
        params["format"] = fmt
        del params["limit"], params["offset"]  # a download is every matching event, up to the API's own cap
    return params


def collect(fetch, cap: int | None = None, page: int | None = None) -> tuple[list, bool]:
    """Every row that `fetch(limit, offset)` gives, up to `cap`: (the rows, whether there were more than `cap`)."""
    cap = EXPORT_LIMIT if cap is None else cap
    page = EXPORT_PAGE if page is None else page
    rows: list = []
    while len(rows) <= cap:
        want = min(page, cap + 1 - len(rows))  # one past the cap, to know there is more
        batch = fetch(want, len(rows))
        rows += batch
        if len(batch) < want:
            break
    return rows[:cap], len(rows) > cap


def page_of(rows: list, size: int = PAGE_SIZE) -> tuple[list, bool]:
    """(the rows to show, whether there is a next page) from a list fetched with one row more than the page."""
    return rows[:size], len(rows) > size


# ── what is shown ───────────────────────────────────────────────────────────────────────────


def status_label(status: str) -> str:
    return m.ATTEMPT_LABEL.get(status, status)


def _text(value: object) -> str:
    """A text from a file or a person, for a table cell: st.table reads a cell as Markdown, so it is quoted.
    (st.dataframe does not, but it is drawn on a canvas that a screen reader and an accessibility scan cannot see.)"""
    return m.literal(value) if value not in (None, "") else ""


def _number(value: int | None) -> str:
    """A count for a table cell, as text: a column that mixes numbers and blanks cannot be sent to the browser as numbers."""
    return "" if value is None else str(value)


def uploads_frame(uploads: list[dict]) -> pd.DataFrame:
    """The list of imports as a table, indexed by the upload's number."""
    return pd.DataFrame(
        [
            {
                "#": int(u["id"]),
                "File": _text(u["file_name"]),
                "Status": status_label(u["status"]),
                "Rows": _number(u.get("total_rows")),
                "Imported": _number(u.get("imported_rows")),
                "Failed": _number(u.get("failed_rows")),
                "Uploaded (UTC)": m.when(u["uploaded_at"]),
                "Uploaded by": _text(u.get("uploader")),
                "Mode": u.get("mode") or "",
            }
            for u in uploads
        ],
        columns=["#", "File", "Status", "Rows", "Imported", "Failed", "Uploaded (UTC)", "Uploaded by", "Mode"],
    ).set_index("#")


def import_label(upload: dict) -> str:
    return m.attempt_label(upload)


def outcome_line(upload: dict, detail: dict) -> str:
    """How one import ended, in a sentence."""
    total, failed = detail.get("totalRows"), detail.get("failedRows")
    parts = [status_label(detail["status"] if "status" in detail else upload["status"])]
    if failed:
        parts.append(f"{failed} of {'?' if total is None else total} rows failed")
    elif total is not None:
        parts.append(f"{total} row{'' if total == 1 else 's'}")
    if detail.get("uploader") or upload.get("uploader"):
        parts.append(f"uploaded by {detail.get('uploader') or upload.get('uploader')}")
    parts.append(m.when(upload["uploaded_at"]))
    return " · ".join(parts)


def errors_frame(row_errors: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Row": e.get("rowNumber"),
                "Column": _text(e.get("column")),
                "Value": _text(e.get("value")),
                "Reason": _text(e["reason"]),
            }
            for e in row_errors
        ],
        columns=["Row", "Column", "Value", "Reason"],
    ).set_index("Row")


def errors_note(shown: int, failed: int | None) -> str | None:
    """Says so when the server kept fewer reasons than rows failed (it keeps the first few; see API_MAX_ROW_ERRORS)."""
    if failed and failed > shown:
        return f"Showing the first {shown} of {failed} failed rows: the server keeps the reasons for the first {shown} only."
    return None


def log_frame(logs: list[dict]) -> pd.DataFrame:
    """The server's step log for one import, oldest first."""
    rows = []
    for entry in logs:
        at = datetime.fromtimestamp(entry["ts"] / 1000, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        rows.append(
            {
                "Time (UTC)": at,
                "Step": entry["step"],
                "Level": entry["level"],
                "Message": _text(entry["message"]),
                "Count": _number(entry.get("count")),
            }
        )
    return pd.DataFrame(rows, columns=["Time (UTC)", "Step", "Level", "Message", "Count"]).set_index("Time (UTC)")


def events_frame(entries: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "When (UTC)": m.when(e["performedAt"]),
                "Actor": _text(e.get("actor")),
                "Action": e["action"],
                "File": _text(e.get("fileName")),
                "Table": _text(e.get("tableName")),
            }
            for e in entries
        ],
        columns=["When (UTC)", "Actor", "Action", "File", "Table"],
    ).set_index("When (UTC)")


def events_summary(page: dict) -> str:
    n = page["total"]
    return f"{n} event{'' if n == 1 else 's'} · {page['classification']}"
