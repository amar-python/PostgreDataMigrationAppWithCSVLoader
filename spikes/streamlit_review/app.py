"""#154 spike: the M4 review screen in Streamlit, against the existing FastAPI API.

Throwaway learning code, not production. The React screen
(csv-table-hub-main/src/components/review-table.tsx) stays live.

    pip install -r spikes/streamlit_review/requirements.txt
    streamlit run spikes/streamlit_review/app.py

API_URL (default http://localhost:8000) and API_KEY (dev, no sign-in) come from the environment.
"""

from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
PAGE = 100
REVIEW_ROLES = {"reviewer", "tenant_admin"}  # api/auth.py PERMISSIONS["review_rows"]

st.set_page_config(page_title="Review", layout="wide")
ss = st.session_state  # per browser tab, held server-side: nothing lands in localStorage


def call(method: str, path: str, **kw):
    headers = {"Authorization": f"Bearer {ss.session['token']}"} if "session" in ss else \
        {"X-API-Key": os.environ.get("API_KEY", "")}
    r = requests.request(method, API + path, headers=headers, timeout=30, **kw)
    if r.status_code == 401 and "session" in ss:
        del ss["session"]
        st.rerun()
    if not r.ok:
        raise RuntimeError(r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith(
            "application/json") else r.text)
    return r.json()


# ── Sign-in ────────────────────────────────────────────────────────────────────

def sign_in():
    with st.sidebar.form("login"):
        tenant = st.text_input("Tenant")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            r = requests.post(f"{API}/api/auth/login", timeout=30,
                              json={"tenant": tenant, "username": username, "password": password})
            if r.ok:
                ss.clear()
                ss.session = r.json()
                st.rerun()
            st.error("Invalid tenant, username or password")


if "session" in ss:
    s = ss.session
    st.sidebar.write(f"**{s['username']}** · {s['tenant']} · `{s['role']}`")
    if st.sidebar.button("Sign out"):
        try:
            call("POST", "/api/auth/logout")
        except RuntimeError:
            pass
        ss.clear()  # all state, so the next tenant sees nothing of this one's (cf. #176)
        st.rerun()
    can_review = s["role"] in REVIEW_ROLES
else:
    sign_in()
    st.sidebar.caption("Or, in dev, carry on with the shared API key (no role checks).")
    can_review = True


# ── Dialogs ────────────────────────────────────────────────────────────────────

def _save(fn) -> None:
    try:
        fn()
    except RuntimeError as exc:
        st.error(str(exc))
        return
    st.rerun()


@st.dialog("Edit cell")
def edit_dialog(upload_id: str, row: dict, columns: list[str]):
    col = st.selectbox("Column", range(len(columns)), format_func=lambda i: columns[i])
    st.caption(f"Original: `{row['original'][col]}` · Current: `{row['current'][col]}`")
    value = st.text_input("New value", value=row["current"][col], key=f"v{row['rowNumber']}_{col}")
    reason = st.text_input("Reason (required)")
    if st.button("Save", type="primary", disabled=not reason.strip()):
        _save(lambda: call("PUT", f"/api/csv/uploads/{upload_id}/rows/{row['rowNumber']}/cells/{col}",
                           json={"value": value, "reason": reason}))


@st.dialog("Change decision")
def decision_dialog(upload_id: str, row: dict, decision: str):
    st.write(f"**{decision.title()}** row {row['rowNumber']}")
    reason = st.text_input("Reason (required)")
    if st.button("Save", type="primary", disabled=not reason.strip()):
        _save(lambda: call("PUT", f"/api/csv/uploads/{upload_id}/rows/{row['rowNumber']}/decision",
                           json={"decision": decision, "reason": reason}))


@st.dialog("Row history", width="large")
def history_dialog(upload_id: str, row_number: int):
    entries = call("GET", f"/api/csv/uploads/{upload_id}/rows/{row_number}/history")
    if not entries:
        st.write("No decisions or edits yet.")
    for e in entries:
        what = (f"**{e['decision']}**" if e["kind"] == "decision"
                else f"**{e['column']}**: `{e['oldValue']}` → `{e['newValue']}`")
        st.markdown(f"{e['at'][:19].replace('T', ' ')} · {e['actor']} · {what}  \n_{e['reason']}_")


# ── Screen ─────────────────────────────────────────────────────────────────────

try:
    uploads = call("GET", "/api/csv/uploads")
except (RuntimeError, requests.RequestException) as exc:
    st.error(f"Can't reach the API at {API}: {exc}")
    st.stop()
if not uploads:
    st.info("No uploads yet.")
    st.stop()

upload = st.selectbox("Upload", uploads, format_func=lambda u: f"#{u['id']} {u['file_name']} ({u['status']})")
uid = upload["id"]
total = upload["total_rows"] or 0
pages = max(1, -(-total // PAGE))
page_no = st.number_input(f"Page (of {pages})", 1, pages, 1, key=f"page{uid}")
data = call("GET", f"/api/csv/uploads/{uid}/rows", params={"offset": (page_no - 1) * PAGE, "limit": PAGE})
columns, rows = data["columns"], data["rows"]

st.subheader(data["fileName"])
st.caption(f"{data['total']} rows · {data['excludedRows']} excluded · {data['editedRows']} edited"
           + ("" if can_review else " · read-only for your role"))

grid = pd.DataFrame([r["current"] for r in rows], columns=columns,
                    index=[r["rowNumber"] for r in rows])
grid.insert(0, "status", ["Excluded" if r["decision"] == "exclude" else "Invalid" if r["errors"] else "Included"
                          for r in rows])


def tint(_):
    out = pd.DataFrame("", index=grid.index, columns=grid.columns)
    for r in rows:
        for i in r["editedColumns"]:
            out.loc[r["rowNumber"], columns[i]] = "background-color: rgba(59,130,246,.18)"
        for e in r["errors"]:
            if e["column"] in columns:
                out.loc[r["rowNumber"], e["column"]] = "background-color: rgba(239,68,68,.22)"
        if r["decision"] == "exclude":
            out.loc[r["rowNumber"]] = out.loc[r["rowNumber"]] + ";color:#9ca3af"  # st.dataframe ignores opacity
    return out


picked = st.dataframe(grid.style.apply(tint, axis=None), on_select="rerun", selection_mode="single-row",
                      key=f"grid{uid}_{page_no}", use_container_width=True, height=560)
sel = picked.selection.rows
if not sel:
    st.caption("Select a row to see its errors, original values and history.")
    st.stop()

row = rows[sel[0]]
st.markdown(f"### Row {row['rowNumber']}")
for e in row["errors"]:
    st.error(f"**{e['column']}**: {e['reason']}")
if row["decisionReason"]:
    st.info(f"Decision: **{row['decision']}**: {row['decisionReason']}")
for i in row["editedColumns"]:
    st.caption(f"{columns[i]}: original `{row['original'][i]}`, now `{row['current'][i]}`")

b = st.columns(4)
if b[0].button("History"):
    history_dialog(uid, row["rowNumber"])
if can_review:
    if b[1].button("Edit a cell"):
        edit_dialog(uid, row, columns)
    flip = "include" if row["decision"] == "exclude" else "exclude"
    if b[2].button(flip.title()):
        decision_dialog(uid, row, flip)
