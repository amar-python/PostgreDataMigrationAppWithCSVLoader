"""Import history: the tenant's uploads read from the server (#253), with filters, a row-error view and exports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import api_client
import auth
import exports
from outcomes import STATUS_LABELS, UPLOADS_LIMIT, failed_rows_note

ANY = "Any"


def query_params(file: str, status: str | None, start: date | None, end: date | None) -> dict:
    """Only the filters that are set; the end date is inclusive, so the server gets the start of the next day."""
    p: dict = {"limit": UPLOADS_LIMIT}
    if file:
        p["file"] = file
    if status:
        p["status"] = status
    if start:
        p["from"] = datetime.combine(start, datetime.min.time()).isoformat()
    if end:
        p["to"] = datetime.combine(end + timedelta(days=1), datetime.min.time()).isoformat()
    return p


@st.cache_data(ttl=30)
def _uploads(token: str, params: tuple) -> list[dict]:
    return auth.call("GET", "/api/csv/uploads", params=dict(params))


def _dates(picked: tuple) -> tuple[date | None, date | None]:
    """A blank range is (); half a range (only a start so far) filters from that day on."""
    return (picked[0] if picked else None), (picked[1] if len(picked) > 1 else None)


def render() -> None:
    s = auth.session()
    if s is None:
        return
    st.title("Import history")
    st.caption("This history is shared by everyone in your tenant.")

    c1, c2, c3 = st.columns(3)
    file = c1.text_input("File name").strip()
    label = c2.selectbox("Status", [ANY, *STATUS_LABELS.values()])
    start, end = _dates(c3.date_input("Uploaded between", value=(), key="history_dates"))
    status = next((k for k, v in STATUS_LABELS.items() if v == label), None)

    try:
        uploads = _uploads(s["token"], tuple(query_params(file, status, start, end).items()))
    except api_client.ApiError as e:
        st.error(str(e))
        return
    if not uploads:
        st.info("No imports match these filters.")
        return

    if len(uploads) >= UPLOADS_LIMIT:
        st.caption(f"Showing the newest {UPLOADS_LIMIT}; narrow the filters to see older ones.")
    rows = exports.history_rows(uploads)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    d1, d2 = st.columns(2)
    d1.download_button("History CSV", exports.to_csv(exports.HISTORY_HEADERS, rows), "import-history.csv", "text/csv")
    d2.download_button("History XLSX", exports.to_xlsx("Import history", exports.HISTORY_HEADERS, rows),
                       "import-history.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    by_id = {u["id"]: u for u in uploads}
    uid = st.selectbox("Show errors for", list(by_id), index=None, key="history_upload",
                       format_func=lambda i: f"#{i} {by_id[i]['file_name']} ({STATUS_LABELS.get(by_id[i]['status'], by_id[i]['status'])})")
    if uid is None:
        return
    u = by_id[uid]
    if note := failed_rows_note(u):
        st.caption(note)
    try:
        detail = auth.call("GET", f"/api/csv/uploads/{uid}")
    except api_client.ApiError as e:
        st.error(str(e))
        return
    errs = exports.error_rows(u, detail)
    if errs:
        st.table(pd.DataFrame(errs, columns=exports.ERROR_HEADERS))
    else:
        st.caption("No row errors.")
    stem = Path(u["file_name"]).stem
    e1, e2 = st.columns(2)
    e1.download_button("Errors CSV", exports.to_csv(exports.ERROR_HEADERS, errs), f"{stem}-errors.csv", "text/csv")
    e2.download_button("Errors XLSX", exports.to_xlsx("Errors", exports.ERROR_HEADERS, errs), f"{stem}-errors.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
