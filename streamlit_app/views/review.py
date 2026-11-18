"""Review: an upload's rows with their errors, and for a reviewer, exclude/include, edit a cell and history (#252).

Forms are inline in the row panel. A row is picked with the "Row number" input; clicking a grid row writes into it.
"""

from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

import api_client
import auth
from outcomes import failed_rows_note, needs_attention

PAGE = 100
NEED_REASON = "Give a reason."


@st.cache_data(ttl=30)
def uploads_list(token: str) -> list[dict]:
    return auth.call("GET", "/api/csv/uploads")


def _tint(grid: pd.DataFrame, rows: list[dict], columns: list[str]):
    def paint(_):
        out = pd.DataFrame("", index=grid.index, columns=grid.columns)
        for r in rows:
            for i in r["editedColumns"]:
                out.loc[r["rowNumber"], columns[i]] = "background-color: rgba(59,130,246,.18)"
            for e in r["errors"]:
                if e["column"] in columns:
                    out.loc[r["rowNumber"], e["column"]] = "background-color: rgba(239,68,68,.22)"
            if r["decision"] == "exclude":
                out.loc[r["rowNumber"]] = out.loc[r["rowNumber"]] + ";color:#9ca3af"
        return out
    return paint


def _grid_picked(grid_key: str, row_key: str, numbers: list[int]) -> None:
    sel = st.session_state[grid_key].selection.rows
    if sel:
        st.session_state[row_key] = numbers[sel[0]]


def _save(path: str, body: dict, reason: str, history_key: str) -> None:
    if not reason.strip():
        st.error(NEED_REASON)
        return
    try:
        auth.call("PUT", path, json={**body, "reason": reason.strip()})
    except api_client.ApiError as e:
        st.error(str(e))
        return
    uploads_list.clear()
    st.session_state.pop(history_key, None)
    st.rerun()


def _history(entries: list[dict]) -> None:
    if not entries:
        st.write("No decisions or edits yet.")
    for e in entries:
        what = (f"**{e['decision']}**" if e["kind"] == "decision"
                else f"**{e['column']}**: `{e['oldValue']}` → `{e['newValue']}`")
        st.markdown(f"{e['at'][:19].replace('T', ' ')} · {e['actor']} · {what}  \n_{e['reason']}_")


def _row_panel(uid: int, row: dict, columns: list[str]) -> None:
    n = row["rowNumber"]
    base = f"/api/csv/uploads/{uid}/rows/{n}"
    hist_key = f"review_hist_{uid}_{n}"
    st.markdown(f"### Row {n}")
    for e in row["errors"]:
        st.error(f"{e['column']}: {e['reason']}")
    if row["decisionReason"]:
        st.info(f"Decision: **{row['decision']}**: {row['decisionReason']}")
    for i in row["editedColumns"]:
        st.caption(f"{columns[i]}: original `{row['original'][i]}`, now `{row['current'][i]}`")

    if st.button("History", key=f"review_histbtn_{uid}_{n}"):
        try:
            st.session_state[hist_key] = auth.call("GET", f"{base}/history")
        except api_client.ApiError as e:
            st.error(str(e))
    if hist_key in st.session_state:
        _history(st.session_state[hist_key])

    if not auth.can("review_rows"):
        return
    flip = "include" if row["decision"] == "exclude" else "exclude"
    with st.form(f"review_decision_{uid}_{n}"):
        reason = st.text_input("Reason (required)", key=f"review_dreason_{uid}_{n}")
        if st.form_submit_button(flip.title()):
            _save(f"{base}/decision", {"decision": flip}, reason, hist_key)
    with st.form(f"review_edit_{uid}_{n}"):
        col = st.selectbox("Column", range(len(columns)), format_func=lambda i: columns[i],
                           key=f"review_col_{uid}_{n}")
        value = st.text_input("New value", key=f"review_value_{uid}_{n}")
        reason = st.text_input("Reason (required)", key=f"review_ereason_{uid}_{n}")
        if st.form_submit_button("Save edit"):
            _save(f"{base}/cells/{col}", {"value": value}, reason, hist_key)


def render() -> None:
    s = auth.session()
    if s is None:
        return
    st.title("Review")
    try:
        uploads = uploads_list(s["token"])
    except api_client.ApiError as e:
        st.error(str(e))
        return
    if not uploads:
        st.info("No uploads yet.")
        return

    only = st.checkbox("Only failed or partly imported")
    shown = [u for u in uploads if needs_attention(u["status"])] if only else uploads
    if not shown:
        st.info("No failed or partly imported uploads.")
        return
    by_id = {u["id"]: u for u in shown}
    uid = st.selectbox("Upload", list(by_id), key="review_upload",
                       format_func=lambda i: f"#{i} {by_id[i]['file_name']} ({by_id[i]['status']})")
    upload = by_id[uid]
    if note := failed_rows_note(upload):
        st.caption(note)
    if upload["status"] == "rejected":
        st.info("This upload was rejected, so there are no rows to review."
                + (f" Reason: {upload['failure_reason']}" if upload.get("failure_reason") else ""))
        return

    pages = max(1, -(-(upload["total_rows"] or 0) // PAGE))
    page_no = st.number_input(f"Page (of {pages})", 1, pages, 1, key=f"review_page_{uid}") if pages > 1 else 1
    try:
        data = auth.call("GET", f"/api/csv/uploads/{uid}/rows",
                         params={"offset": (page_no - 1) * PAGE, "limit": PAGE})
    except api_client.ApiError as e:
        st.error(str(e))
        return
    columns, rows = data["columns"], data["rows"]
    st.subheader(data["fileName"])
    st.caption(f"{data['total']} rows · {data['excludedRows']} excluded · {data['editedRows']} edited"
               + ("" if auth.can("review_rows") else " · read-only for your role"))
    if not rows:
        st.info("This upload has no rows on this page.")
        return

    numbers = [r["rowNumber"] for r in rows]
    grid = pd.DataFrame([r["current"] for r in rows], columns=columns, index=numbers)
    grid.insert(0, "status", ["Excluded" if r["decision"] == "exclude" else "Invalid" if r["errors"] else "Included"
                              for r in rows])
    row_key, grid_key = f"review_row_{uid}_{page_no}", f"review_grid_{uid}_{page_no}"
    st.session_state.setdefault(row_key, numbers[0])
    st.dataframe(grid.style.apply(_tint(grid, rows, columns), axis=None), on_select=partial(_grid_picked, grid_key, row_key, numbers),
                 selection_mode="single-row", key=grid_key, width="stretch", height=560)
    n = st.number_input("Row number", numbers[0], numbers[-1], key=row_key)
    row = next((r for r in rows if r["rowNumber"] == n), None)
    if row is None:
        st.caption("No such row on this page.")
        return
    _row_panel(uid, row, columns)
