"""The imported-files screen (#255): the React page's "Migrated files" list, a look inside each table, and why rows failed.

Part of replacing `_authenticated/index.tsx`, which showed this list under the uploader. Here it is its own page, so
the upload screen does not ask the API for the list on every re-run.

The list is cached for 30 seconds per session and cleared after an upload ("Refresh the list" does it too). Not carried
over: nothing (the React list had no delete button either; deleting a file is the API's `DELETE /api/csv/files/{id}`).
"""

from __future__ import annotations

import streamlit as st

import api_client
import auth
import exports
import files_model as f
import history_model as h
import review_model as m

LIST_TTL_SECONDS = 30
PAGE = "files_page"


@st.cache_data(ttl=LIST_TTL_SECONDS, show_spinner=False)
def _files(token: str) -> list[dict]:
    """Every imported file, newest first. The token is the cache key: one entry per session, never shared."""
    return api_client.request("GET", "/api/csv/files", token=token)


def _read(method: str, path: str, **kwargs):
    try:
        return auth.call(method, path, **kwargs)
    except api_client.ApiError as e:
        st.error(m.literal(e))
        st.stop()


def render() -> None:
    st.title("Imported files")
    st.caption("Every file imported into this tenant, whoever uploaded it. The Review page shows the stored rows of one.")
    try:
        files = _files(auth.session()["token"])
    except api_client.Unauthorized:
        auth.lost_session()
    except api_client.ApiError as e:
        st.error(m.literal(e))
        st.stop()
    if st.button("Refresh the list"):
        _files.clear()
        st.rerun()
    if not files:
        st.info("No files yet. Upload a CSV file on the Upload page.")
        return

    pages = f.page_count(len(files))
    page = st.number_input(f"Page (of {pages})", 1, pages, 1, key=PAGE)
    start = (page - 1) * f.PAGE_SIZE
    shown = files[start:start + f.PAGE_SIZE]
    st.caption(f"Files {start + 1} to {start + len(shown)} of {len(files)}, newest first.")
    st.table(f.files_frame(shown, start + 1))

    st.divider()
    labels = {x["id"]: f.file_label(x) for x in shown}
    chosen = st.selectbox("Look inside a file", list(labels), index=None, format_func=labels.__getitem__,
                          placeholder="Choose a file to preview its table")
    if chosen is not None:
        _inside(next(x for x in shown if x["id"] == chosen))


def _inside(file: dict) -> None:
    st.subheader(m.literal(file["file_name"]))
    data = _read("GET", f"/api/csv/tables/{file['table_name']}/rows", params={"limit": f.PREVIEW_ROWS})
    columns = file.get("column_names") or []
    rows = data["rows"]
    if rows:
        st.dataframe(f.preview_frame(columns, rows), hide_index=True, width="stretch")
    else:
        st.write("The table has no rows.")
    for note in f.table_notes(file):
        st.caption(note)
    if file.get("upload_id") and (file.get("failed_rows") or 0) > 0:
        _failed(file)


def _failed(file: dict) -> None:
    """Why rows failed, read from the server so every user in the tenant sees the same reasons (M3c, #107)."""
    detail = _read("GET", f"/api/csv/uploads/{file['upload_id']}")
    errors = detail.get("rowErrors") or []
    if not errors:
        st.caption("No failure reasons were stored for this upload.")
        return
    st.markdown("**Rows that failed**")
    st.table(h.errors_frame(errors[:h.ERROR_ROWS_SHOWN]))
    note = h.errors_note(min(len(errors), h.ERROR_ROWS_SHOWN), detail.get("failedRows"))
    if note:
        st.caption(note)
    rows = exports.error_rows(file["file_name"], errors)
    st.download_button("Error report (CSV)", exports.to_csv(exports.ERROR_HEADERS, rows),
                       exports.report_name("errors", "csv", file["file_name"]), exports.CSV_TYPE,
                       key=f"files_errors_{file['id']}")
