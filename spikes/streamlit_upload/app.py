"""#254 spike: the upload and preview screen in Streamlit. THROWAWAY learning code.

Answers the issue's seven questions against the real API; see README.md for what it found and what
strained. It reuses the app shell's sign-in and session handling (streamlit_app/, #251) and nothing else.
The React screen stays live. Nothing here is wired into CI, the build or the offline bundle.

    cd spikes/streamlit_upload && python -m streamlit run app.py
"""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "streamlit_app"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import api_client  # noqa: E402
import auth  # noqa: E402
from views import sign_in  # noqa: E402

api_client.TIMEOUT_SECONDS = 600  # the shell's 30 s is too short for a big import; the real screen needs a per-call timeout

ALLOWED_TYPES = ["int8", "numeric", "date", "timestamptz", "boolean", "text"]  # api/services/csv_parse.py
NO_CANCEL = "Sent to the server; it can't be stopped now"  # the React app's own wording (#188)
DYNAMIC, TE = "New table from this file (dynamic)", "Test and Evaluation table"
ss = st.session_state

st.set_page_config(page_title="Upload (spike)", layout="wide")
auth.enforce_session()
if not auth.signed_in():
    sign_in.render()
    st.stop()

s = auth.session()
with st.sidebar:
    st.markdown(f"**{s['username']}** · {s['tenant']}  \n`{s['role']}`")
    if st.button("Sign out"):
        auth.sign_out()
        st.rerun()
if not auth.can("upload"):
    st.title("Upload and preview (spike)")
    st.info(f"The role {s['role']} can't upload files.")
    st.stop()


def preview(name: str, text: str, digest: str) -> dict:
    cache = ss.setdefault("previews", {})
    if digest not in cache:  # the whole script re-runs on every click; do not re-parse each time
        cache[digest] = auth.call("POST", "/api/csv/preview", json={"fileName": name, "content": text})
    return cache[digest]


def te_tables() -> list[str]:
    if "te_tables" not in ss:
        ss["te_tables"] = [t["table"] for t in auth.call("GET", "/api/te/tables")]
    return ss["te_tables"]


def mapping_editor(key: str, pv: dict) -> dict:
    """Q2: rename headers and choose types, in a data_editor. Returns the fields to add to the upload."""
    frame = pd.DataFrame({"Column in file": pv["headers"],
                          "Rename to (blank keeps it)": "", "Type": pv["inferredTypes"]})
    edited = st.data_editor(
        frame, key=f"map-{key}", hide_index=True, width="stretch", num_rows="fixed",
        disabled=["Column in file"],
        column_config={
            "Rename to (blank keeps it)": st.column_config.TextColumn(max_chars=128),
            "Type": st.column_config.SelectboxColumn(options=ALLOWED_TYPES, required=True),
        })
    confirmed = st.checkbox("I have checked the column names and types", key=f"ok-{key}")
    mapping = [{"original": o, "renamed": r.strip()} for o, r in
               zip(edited["Column in file"], edited["Rename to (blank keeps it)"]) if r and r.strip()]
    out: dict = {"types": list(edited["Type"]), "typesConfirmed": confirmed}
    if mapping:
        out["headerMapping"] = mapping
    return out


def mapping_form(key: str, pv: dict) -> dict:
    """Q2, the alternative: ordinary widgets instead of a canvas grid. Same fields out."""
    cols = pv["headers"]  # the mapping is applied to the file's raw header row
    types, mapping = [], []
    for i, (col, inferred) in enumerate(zip(cols, pv["inferredTypes"])):
        a, b, c = st.columns([2, 2, 1])
        a.markdown(f"`{col}`")
        new = b.text_input(f"Rename {col}", key=f"rn-{key}-{i}", label_visibility="collapsed", placeholder="keep")
        types.append(c.selectbox(f"Type of {col}", ALLOWED_TYPES, index=ALLOWED_TYPES.index(inferred),
                                 key=f"ty-{key}-{i}", label_visibility="collapsed"))
        if new.strip():
            mapping.append({"original": col, "renamed": new.strip()})
    out: dict = {"types": types, "typesConfirmed": st.checkbox("I have checked the column names and types",
                                                                 key=f"ok-{key}")}
    if mapping:
        out["headerMapping"] = mapping
    return out


def send(payload: dict, key: str) -> None:
    """Q3: the API cannot cancel an import, so say so, and show that something is happening."""
    with st.spinner(NO_CANCEL):
        try:
            ss.setdefault("results", {})[key] = auth.call("POST", "/api/csv/upload", json=payload)
        except api_client.ApiError as e:
            ss["results"][key] = {"status": "error", "message": str(e), "httpStatus": e.status}


def show_result(res: dict) -> None:
    """Q6: what came back, in words, including a repeated file, the version, and the rows that failed."""
    status = res.get("status")
    if status == "ok":
        msg = f"{res['insertedRows']} of {res['totalRows']} rows imported into {res['tableName']}"
        (st.warning if res.get("failedRows") else st.success)(msg + (f", {res['failedRows']} failed" if res.get("failedRows") else ""))
        if res.get("version"):
            st.caption(f"Version {res['version']} of dataset {res.get('dataset')}"
                       + (f", {res['duplicateRowsAcrossUploads']} rows already in an earlier version"
                          if res.get("duplicateRowsAcrossUploads") else ""))
        if res.get("rowErrors"):
            st.dataframe(pd.DataFrame(res["rowErrors"]), width="stretch", hide_index=True)
    elif status == "duplicate_file":
        st.warning(f"Already imported as {res.get('existingFileName')} ({res.get('reason')}); nothing was changed.")
    else:
        st.error(res.get("message") or res.get("reason") or f"Failed: {status}")


def render_file(f, simple: bool) -> dict | None:
    raw = f.getvalue()
    digest = hashlib.sha256(raw).hexdigest()[:12]
    key = f"{digest}"
    text = raw.decode("utf-8", errors="replace")
    with st.expander(f"{f.name} · {len(raw):,} bytes", expanded=True):
        try:
            pv = preview(f.name, text, digest)
        except api_client.ApiError as e:
            st.error(str(e))
            return None
        if pv.get("status") != "ok":
            st.error(pv.get("message") or pv.get("reason") or str(pv.get("status")))
            return None
        st.dataframe(pd.DataFrame(pv["sampleRows"], columns=pv["columns"]), width="stretch", hide_index=True)
        match = pv.get("teTableMatch")
        mode = st.radio("Load as", [DYNAMIC, TE], index=1 if match else 0, key=f"mode-{key}", horizontal=True)
        payload = {"fileName": f.name, "content": text, "contentBase64": base64.b64encode(raw).decode()}
        if mode == TE:
            tables = te_tables()
            payload.update(mode="te", targetTable=st.selectbox(
                "Into table", tables, index=tables.index(match) if match in tables else 0, key=f"tbl-{key}"))
            ready = True
        else:
            payload.update(mode="dynamic", **(mapping_form if simple else mapping_editor)(key, pv))
            ready = payload["typesConfirmed"]
        st.caption(NO_CANCEL + " (once you click Upload)")
        if st.button(f"Upload {f.name}", key=f"go-{key}", disabled=not ready):
            send(payload, key)
        if key in ss.get("results", {}):
            show_result(ss["results"][key])
    return {"key": key, "payload": payload, "ready": ready}


st.title("Upload and preview (spike)")
simple = st.toggle("Use ordinary widgets instead of the grid editor", key="simple")
files = st.file_uploader("CSV files", type=["csv"], accept_multiple_files=True)
rows = [r for r in (render_file(f, simple) for f in files) if r]
if len(rows) > 1 and st.button("Upload all", disabled=not all(r["ready"] for r in rows)):  # Q4: several files
    bar = st.progress(0.0)
    for i, r in enumerate(rows, 1):
        send(r["payload"], r["key"])
        bar.progress(i / len(rows))
    st.rerun()
