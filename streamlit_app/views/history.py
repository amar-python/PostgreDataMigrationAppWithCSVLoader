"""The import-history screen (#253): every upload attempt in the tenant, why each ended as it did, and reports.

It replaces the React "Import history" page, which was the browser's own record kept in `localStorage`. This one
reads the server's (`GET /api/csv/uploads`, `GET /api/csv/uploads/{id}`), so it belongs to the tenant, shows
imports from any browser or device, and nothing about it is kept in the browser. **Behaviour change for users:
the history is no longer per browser.**

A second view, for roles that may read the audit log, shows the server's audit events with the React panel's
filters (`GET /api/audit/events`, BR-35).

Tables are `st.table` (real HTML: a screen reader and the accessibility scan can read them, and a browser test can
assert on them), so every text from a file is put in a code span first: `st.table` reads a cell as Markdown.

Not carried over from React: bulk selection and "Retry" (an import is retried from the upload screen), "Print /
save as PDF" (print the page from the browser), the in-app "App changelog" (release notes do that job), and the
header mapping and cancellation columns of the report (the server does not store them).
"""

from __future__ import annotations

import streamlit as st

import api_client
import auth
import exports
import history_model as h
import review_model as m

# Session-state keys. A form's own key (st.form("history_filters")) is taken by Streamlit, so these differ.
FILTERS = "history_applied"  # the filters last applied
PAGE = "history_page"  # the page of the list, from 0
PREPARED = "history_prepared"  # a report built for one set of filters
EVENT_FILTERS = "history_events_applied"
EVENT_PAGE = "history_events_page"
EVENT_PREPARED = "history_events_prepared"
VIEWS = ["Imports", "Server audit events"]
LIST_TTL_SECONDS = 30


@st.cache_data(ttl=LIST_TTL_SECONDS, show_spinner=False)
def _list(token: str, params: dict) -> list[dict]:
    """A page of imports. The token is part of the cache key: one entry per session, never shared."""
    return api_client.request("GET", "/api/csv/uploads", token=token, params=params)


def _cached(fn, *args):
    try:
        return fn(*args)
    except api_client.Unauthorized:
        auth.lost_session()
    except api_client.ApiError as e:
        st.error(str(e))
        st.stop()


def _read(method: str, path: str, **kwargs):
    try:
        return auth.call(method, path, **kwargs)
    except api_client.ApiError as e:
        st.error(str(e))
        st.stop()


def render() -> None:
    st.title("Import history")
    st.caption("Every upload in this tenant, from the server, whoever made it and from whichever browser.")
    views = VIEWS if auth.can("read_audit") else VIEWS[:1]
    view = st.radio("Show", views, horizontal=True, label_visibility="collapsed", key="history_view") \
        if len(views) > 1 else views[0]
    if view == VIEWS[0]:
        _imports(auth.session()["token"])
    else:
        _events()


# ── the imports ─────────────────────────────────────────────────────────────────────────────

def _move(key: str, step: int) -> None:
    st.session_state[key] = max(0, st.session_state.get(key, 0) + step)


def _imports(token: str) -> None:
    with st.form("history_filters"):
        left, right = st.columns(2)
        file = left.text_input("File name contains")
        status = right.selectbox("Status", [s for s, _ in h.STATUSES], format_func=dict(h.STATUSES).__getitem__)
        uploader = left.text_input("Uploaded by")
        date_from = right.date_input("From", value=None)
        date_to = right.date_input("To", value=None)
        applied = st.form_submit_button("Apply")
    if applied:
        st.session_state[FILTERS] = {"file": file, "status": status, "uploader": uploader,
                                     "date_from": date_from, "date_to": date_to}
        st.session_state[PAGE] = 0
    filters = st.session_state.get(FILTERS, {})
    page = st.session_state.get(PAGE, 0)

    if st.button("Refresh the list"):
        _list.clear()
        st.rerun()
    fetched = _cached(_list, token, h.uploads_params(**filters, offset=page * h.PAGE_SIZE))
    uploads, has_next = h.page_of(fetched)
    if not uploads:
        st.info("No imports match the filters." if filters else "No imports yet. Upload a CSV file to see it here.")
        if page:
            st.button("Previous page", on_click=_move, args=(PAGE, -1))
        return
    first = page * h.PAGE_SIZE + 1
    st.caption(f"Imports {first} to {first + len(uploads) - 1}, newest first.")
    st.table(h.uploads_frame(uploads))
    before, after, _ = st.columns([1, 1, 4])
    before.button("Previous page", on_click=_move, args=(PAGE, -1), disabled=page == 0)
    after.button("Next page", on_click=_move, args=(PAGE, 1), disabled=not has_next)

    _history_report(filters)

    st.divider()
    labels = {u["id"]: h.import_label(u) for u in uploads}
    chosen = st.selectbox("Details of an import", list(labels), index=None, format_func=labels.__getitem__,
                          placeholder="Choose an import to see why rows failed")
    if chosen is not None:
        _detail(next(u for u in uploads if u["id"] == chosen))


def _history_report(filters: dict) -> None:
    """A report of every import that matches the filters, not only this page: built on request, then offered."""
    key = repr(sorted((k, str(v)) for k, v in filters.items()))
    prepared = st.session_state.get(PREPARED)
    if st.button("Prepare a report of all matching imports"):
        rows, capped = h.collect(lambda limit, offset: _read(
            "GET", "/api/csv/uploads", params=h.uploads_params(**filters, limit=limit, offset=offset)))
        report = exports.history_rows(rows)
        prepared = {"key": key, "count": len(rows), "capped": capped,
                    "csv": exports.to_csv(exports.HISTORY_HEADERS, report),
                    "xlsx": exports.to_xlsx("History", exports.HISTORY_HEADERS, report)}
        st.session_state[PREPARED] = prepared
    if prepared and prepared["key"] == key:
        n = prepared["count"]
        st.caption(f"Report of {n} import{'' if n == 1 else 's'}" + (f", cut short at {h.EXPORT_LIMIT}: narrow the "
                                                                      "filters for the rest." if prepared["capped"] else "."))
        one, two, _ = st.columns([1, 1, 4])
        one.download_button("Download CSV", prepared["csv"], exports.report_name("history", "csv"), exports.CSV_TYPE)
        two.download_button("Download XLSX", prepared["xlsx"], exports.report_name("history", "xlsx"), exports.XLSX_TYPE)


def _detail(upload: dict) -> None:
    uid = upload["id"]
    detail = _read("GET", f"/api/csv/uploads/{uid}")
    st.subheader(m.literal(detail["fileName"]))
    st.caption(h.outcome_line(upload, detail))
    reason = upload.get("failure_reason")
    if reason:
        st.info(f"Why: {m.literal(reason)}")
    errors = detail.get("rowErrors") or []
    if errors:
        st.markdown("**Rows that failed**")
        st.table(h.errors_frame(errors[:h.ERROR_ROWS_SHOWN]))
        note = h.errors_note(min(len(errors), h.ERROR_ROWS_SHOWN), detail.get("failedRows"))
        if note:
            st.caption(note)
    elif detail.get("failedRows"):
        st.caption("No failure reasons were stored for this upload.")
    report = exports.error_rows(detail["fileName"], errors, reason if not errors else None)
    if report:
        one, two, _ = st.columns([1, 1, 4])
        one.download_button("Error report (CSV)", exports.to_csv(exports.ERROR_HEADERS, report),
                            exports.report_name("errors", "csv", detail["fileName"]), exports.CSV_TYPE,
                            key=f"history_errors_csv_{uid}")
        two.download_button("Error report (XLSX)", exports.to_xlsx("Errors", exports.ERROR_HEADERS, report),
                            exports.report_name("errors", "xlsx", detail["fileName"]), exports.XLSX_TYPE,
                            key=f"history_errors_xlsx_{uid}")
    with st.expander("What the server did, step by step"):
        logs = detail.get("logs") or []
        if logs:
            st.table(h.log_frame(logs))
        else:
            st.write("No step log was stored for this upload.")
    st.caption("To change a row after an import, open it on the Review page.")


# ── the server's audit events ───────────────────────────────────────────────────────────────

def _events() -> None:
    with st.form("history_events"):
        left, right = st.columns(2)
        actor = left.text_input("Actor")
        action = right.selectbox("Action", ["", *h.AUDIT_ACTIONS], format_func=lambda a: a or "All")
        file = left.text_input("File")
        date_from = right.date_input("From", value=None)
        date_to = right.date_input("To", value=None)
        applied = st.form_submit_button("Apply")
    if applied:
        st.session_state[EVENT_FILTERS] = {"actor": actor, "action": action, "file": file, "date_from": date_from,
                                           "date_to": date_to}
        st.session_state[EVENT_PAGE] = 0
    filters = st.session_state.get(EVENT_FILTERS, {})
    page = st.session_state.get(EVENT_PAGE, 0)

    data = _read("GET", "/api/audit/events", params=h.events_params(**filters, offset=page * h.EVENTS_PAGE))
    st.caption(h.events_summary(data))
    if data["entries"]:
        st.table(h.events_frame(data["entries"]))
    else:
        st.info("No events match the filters.")
    before, after, _ = st.columns([1, 1, 4])
    before.button("Previous events", on_click=_move, args=(EVENT_PAGE, -1), disabled=page == 0)
    after.button("Next events", on_click=_move, args=(EVENT_PAGE, 1),
                 disabled=(page + 1) * data["limit"] >= data["total"])

    key = repr(sorted((k, str(v)) for k, v in filters.items()))
    prepared = st.session_state.get(EVENT_PREPARED)
    if st.button("Prepare a CSV of all matching events"):
        body, headers = _read_file("/api/audit/events", params=h.events_params(**filters, fmt="csv"))
        prepared = {"key": key, "csv": body}
        st.session_state[EVENT_PREPARED] = prepared
    if prepared and prepared["key"] == key:
        st.download_button("Download CSV", prepared["csv"], "audit-events.csv", exports.CSV_TYPE,
                           key="history_events_csv")
        st.caption("The server has already neutralised spreadsheet formulas in this file.")


def _read_file(path: str, **kwargs):
    s = auth.session()
    try:
        return api_client.download("GET", path, token=s["token"], **kwargs)
    except api_client.Unauthorized:
        auth.lost_session()
    except api_client.ApiError as e:
        st.error(str(e))
        st.stop()
