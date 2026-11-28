"""The review screen (#252): every stored row of an upload with its problems, and a reviewer's edits and decisions.

It replaces the React screen (review-table.tsx) and is the #154 spike made ready to ship. What changed from the
spike, each a strain it found:

* Click-to-edit is not possible on the grid (it is drawn on a canvas), so a row is chosen by selecting it OR by
  typing its number in a plain "Row number" box. The box is what keyboard and screen-reader users and the
  headless tests use; the two stay in step.
* Edits and decisions are forms inside the page, not dialogs: Enter saves, a missing reason is refused before
  anything is sent, and the headless tests can drive them.
* The list of uploads is cached for a short time, keyed by the session token (so two people never share an
  entry) and cleared on sign-out; the rows are never cached, because they change as people review them.

Changes are saved with the upload for review. They don't change the imported table (M4a, #108).
"""

from __future__ import annotations

import streamlit as st

import api_client
import auth
import review_model as m

UPLOADS_TTL_SECONDS = 30
FLASH = "review_flash"  # one message for the next run: what was just saved
UPLOAD = "review_upload"  # the upload being reviewed, kept by id so a refreshed list does not move it


@st.cache_data(ttl=UPLOADS_TTL_SECONDS, show_spinner=False)
def _uploads(token: str) -> list[dict]:
    """Every upload attempt, newest first. The token is the cache key: one entry per session, never shared."""
    return api_client.request("GET", "/api/csv/uploads", token=token)


def _load_uploads(token: str) -> list[dict]:
    try:
        return _uploads(token)
    except api_client.Unauthorized:
        auth.lost_session()
    except api_client.ApiError as e:
        st.error(str(e))
        st.stop()


def _read(method: str, path: str, **kwargs):
    """A read the screen cannot go on without: on failure say why and stop."""
    try:
        return auth.call(method, path, **kwargs)
    except api_client.ApiError as e:
        st.error(str(e))
        st.stop()


def render() -> None:
    s = auth.current()
    st.title("Review")
    flash = st.session_state.pop(FLASH, None)
    if flash:
        st.success(flash)

    uploads = _load_uploads(s["token"])
    only_problems = st.checkbox("Only failed or partly failed uploads", key="review_only_problems")
    if st.button("Refresh the list"):
        _uploads.clear()
        st.rerun()
    if not uploads:
        st.info("No uploads yet.")
        return
    shown = m.filter_attempts(uploads, only_problems)
    if not shown:
        st.info("No failed or partly failed uploads.")
        return

    labels = {u["id"]: m.attempt_label(u) for u in shown}
    ids = list(labels)
    kept = st.session_state.get(UPLOAD)
    uid = st.selectbox("Upload", ids, index=ids.index(kept) if kept in ids else 0, format_func=labels.__getitem__)
    st.session_state[UPLOAD] = uid
    upload = next(u for u in shown if u["id"] == uid)
    if not m.reviewable(upload):  # #187: a rejected file stored no rows
        st.info("This upload was rejected, so no rows were stored and there is nothing to review.")
        if upload.get("failure_reason"):
            st.caption(f"Why: {m.literal(upload['failure_reason'])}")
        return

    pages = m.page_count(upload["total_rows"] or 0)
    page_no = st.number_input(f"Page (of {pages})", 1, pages, 1, key=f"review_page_{uid}")
    data = _read(
        "GET", f"/api/csv/uploads/{uid}/rows", params={"offset": (page_no - 1) * m.PAGE_SIZE, "limit": m.PAGE_SIZE}
    )
    columns, types, rows = data["columns"], data["types"], data["rows"]
    can_review = auth.can("review_rows")

    st.subheader(m.literal(data["fileName"]))
    st.caption(m.summary(data))
    if not can_review:
        st.caption("Only reviewers and tenant admins can make changes.")
    if not rows:
        st.info("This upload has no stored rows.")
        return

    first, last = rows[0]["rowNumber"], rows[-1]["rowNumber"]
    chooser = st.container()  # drawn above the table, filled after it: the table says what was clicked
    frame = m.grid_frame(rows, columns, m.status_column(columns))
    picked = st.dataframe(
        frame.style.apply(lambda _: m.tint(rows, frame, columns), axis=None),
        column_config={c: st.column_config.Column(f"{c} ({t})") for c, t in zip(columns, types)},
        on_select="rerun",
        selection_mode="single-row",
        key=f"review_grid_{uid}_{page_no}",
        width="stretch",
        height=min(560, 38 + 35 * len(rows)),
    )

    # A click on the table moves the Row number box to that row. Anything else (typing a number) leaves the
    # table alone. A number left from another page needs no handling: the box's range changes with the page,
    # which makes Streamlit start it empty (checked headless and in a browser, as an upgrade could change it).
    row_key, seen_key = f"review_row_{uid}", f"review_seen_{uid}_{page_no}"
    clicked = rows[picked.selection.rows[0]]["rowNumber"] if picked.selection.rows else None
    if clicked != st.session_state.get(seen_key):
        st.session_state[seen_key] = clicked
        if clicked is not None:
            st.session_state[row_key] = clicked
    with chooser:
        number = st.number_input(
            "Row number",
            first,
            last,
            value=None,
            step=1,
            key=row_key,
            placeholder=f"{first} to {last}",
            help="Select a row in the table, or type its number.",
        )
    if number is None:
        st.caption("Select a row in the table, or type its number, to see its problems, original values and history.")
        return
    _detail(uid, next(r for r in rows if r["rowNumber"] == number), columns, types, can_review)


# ── one row ─────────────────────────────────────────────────────────────────────────────────


def _detail(uid: str, row: dict, columns: list[str], types: list[str], can_review: bool) -> None:
    st.subheader(f"Row {row['rowNumber']}")
    for line in m.error_lines(row):
        st.error(line)
    decision = m.decision_line(row)
    if decision:
        st.info(decision)
    for line in m.edit_lines(row, columns):
        st.caption(line)

    ver = st.session_state.get(f"review_ver_{uid}", 0)  # bumped after each save, so the forms start empty again
    if not can_review:
        st.markdown("**History**")
        _history(uid, row["rowNumber"])
        return
    flip = "include" if row["decision"] == "exclude" else "exclude"
    edit_tab, decide_tab, history_tab = st.tabs(["Edit a cell", f"{flip.title()} row", "History"])
    with edit_tab:
        _edit(uid, row, columns, types, ver)
    with decide_tab:
        _decide(uid, row, flip, ver)
    with history_tab:
        _history(uid, row["rowNumber"])


def _history(uid: str, row_number: int) -> None:
    try:
        entries = auth.call("GET", f"/api/csv/uploads/{uid}/rows/{row_number}/history")
    except api_client.ApiError as e:
        st.error(str(e))
        return
    if not entries:
        st.write("No changes yet.")
    for entry in entries:
        st.markdown(m.history_line(entry))


def _edit(uid: str, row: dict, columns: list[str], types: list[str], ver: int) -> None:
    n = row["rowNumber"]
    # Outside the form, so choosing a column shows that column's original value straight away.
    i = st.selectbox(
        "Column", range(len(columns)), format_func=lambda k: f"{columns[k]} ({types[k]})", key=f"review_col_{uid}"
    )
    st.caption(
        f"Original value: {m.literal(row['original'][i] or '(empty)')} · "
        f"Current value: {m.literal(row['current'][i] or '(empty)')}"
    )
    with st.form(f"review_edit_{uid}_{ver}"):
        value = st.text_input("New value", value=row["current"][i], key=f"review_value_{uid}_{n}_{i}_{ver}")
        reason = st.text_input("Reason for the change (required)", key=f"review_why_{uid}_{n}_{i}_{ver}")
        submitted = st.form_submit_button("Save", type="primary")
    if not submitted:
        return
    if not reason.strip():
        st.error("A reason is required")
        return
    # By position, not name: a column may be called "2024", which the API would read as a position, or hold a "/".
    _save(
        uid,
        ver,
        "PUT",
        f"/api/csv/uploads/{uid}/rows/{n}/cells/{i}",
        {"value": value, "reason": reason},
        f"Saved: row {n}, {m.literal(columns[i])}.",
    )


def _decide(uid: str, row: dict, flip: str, ver: int) -> None:
    n = row["rowNumber"]
    with st.form(f"review_decide_{uid}_{ver}"):
        reason = st.text_input(f"Reason to {flip} this row (required)", key=f"review_decide_why_{uid}_{n}_{ver}")
        submitted = st.form_submit_button(f"{flip.title()} this row", type="primary")
    if not submitted:
        return
    if not reason.strip():
        st.error("A reason is required")
        return
    _save(
        uid,
        ver,
        "PUT",
        f"/api/csv/uploads/{uid}/rows/{n}/decision",
        {"decision": flip, "reason": reason},
        f"Saved: row {n} {'excluded' if flip == 'exclude' else 'included'}.",
    )


def _save(uid: str, ver: int, method: str, path: str, body: dict, done: str) -> None:
    try:
        auth.call(method, path, json=body)
    except api_client.ApiError as e:  # the API's own words: a frozen upload (409), the same value (422)...
        st.error(str(e))
        return
    st.session_state[f"review_ver_{uid}"] = ver + 1
    st.session_state[FLASH] = done
    st.rerun()
