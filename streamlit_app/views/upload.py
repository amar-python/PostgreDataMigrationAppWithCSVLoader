"""Upload and preview (#255): choose CSV files, check them, map columns, and send them to the API."""

from __future__ import annotations

import base64
import hashlib
import os

import pandas as pd
import streamlit as st

import api_client
import auth
from outcomes import describe_result
from views import history, review

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 52428800))  # the API's own limit, in bytes of text
UPLOAD_TIMEOUT_SECONDS = 600  # a big import takes longer than the shell's 30 s
ALLOWED_TYPES = ["int8", "numeric", "date", "timestamptz", "boolean", "text"]  # api/services/csv_parse.py
NO_CANCEL = "Sent to the server; it can't be stopped now"  # the React app's own wording (#188)
DYNAMIC, TE = "New table from this file (dynamic)", "Test and Evaluation table"
CONFIRM = "I have checked the column names and types"
ss = st.session_state


def prepare(name: str, raw: bytes) -> tuple[str | None, str | None]:
    """(text, None) for a file the API will take, or (None, message) saying why not."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, f'{name} isn\'t UTF-8 text. Save it as "CSV UTF-8" and try again.'
    if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
        return None, f"{name} is larger than the {MAX_UPLOAD_BYTES / 1048576:g} MB the server accepts."
    return text, None


def build_payload(name: str, raw: bytes, text: str, *, mode: str, types: list[str] | None = None,
                  confirmed: bool = False, renames: dict[str, str] | None = None,
                  target: str | None = None) -> dict:
    """The body of POST /api/csv/upload. T&E carries no types and no mapping (the API refuses them there)."""
    p: dict = {"fileName": name, "content": text, "contentBase64": base64.b64encode(raw).decode(), "mode": mode}
    if mode == "te":
        p["targetTable"] = target
        return p
    p["types"] = types
    p["typesConfirmed"] = confirmed
    mapping = [{"original": o, "renamed": r.strip()} for o, r in (renames or {}).items() if r and r.strip()]
    if mapping:
        p["headerMapping"] = mapping
    return p


def file_key(name: str, raw: bytes) -> str:
    """A widget key for one chosen file: name and bytes, so two copies of the same file do not collide."""
    return hashlib.sha256(name.encode() + b"\0" + raw).hexdigest()[:12]


def _preview(name: str, text: str, digest: str) -> dict:
    cache = ss.setdefault("previews", {})
    if digest not in cache:  # the whole script re-runs on every click; do not re-parse each time
        cache[digest] = auth.call("POST", "/api/csv/preview", json={"fileName": name, "content": text})
    return cache[digest]


def _te_tables() -> list[str]:
    if "te_tables" not in ss:
        ss["te_tables"] = [t["table"] for t in auth.call("GET", "/api/te/tables")]
    return ss["te_tables"]


def _mapping_form(key: str, pv: dict) -> tuple[list[str], dict[str, str], bool]:
    types, renames = [], {}
    for i, (col, inferred) in enumerate(zip(pv["headers"], pv["inferredTypes"])):  # the file's raw header row
        a, b, c = st.columns([2, 2, 1])
        a.markdown(f"`{col}`")
        renames[col] = b.text_input(f"Rename {col}", key=f"rn-{key}-{i}", label_visibility="collapsed",
                                    placeholder="keep")
        types.append(c.selectbox(f"Type of {col}", ALLOWED_TYPES, index=ALLOWED_TYPES.index(inferred),
                                 key=f"ty-{key}-{i}", label_visibility="collapsed"))
    return types, renames, st.checkbox(CONFIRM, key=f"ok-{key}")


def _send(name: str, payload: dict, key: str) -> None:
    """The API cannot cancel an import, so say so while it runs."""
    with st.spinner(NO_CANCEL):
        try:
            ss.setdefault("results", {})[key] = auth.call(
                "POST", "/api/csv/upload", json=payload, timeout=UPLOAD_TIMEOUT_SECONDS)
        except api_client.ApiError as e:
            ss["results"][key] = str(e)
    review.uploads_list.clear()  # a new upload must show on Review and Import history at once
    history._uploads.clear()


def _show_result(name: str, res: dict | str) -> None:
    if isinstance(res, str):
        st.error(res)
        return
    level, message = describe_result(name, res)
    getattr(st, level)(message)
    if res.get("version"):
        st.caption(f"Version {res['version']} of dataset {res.get('dataset')}")
    check = res.get("schemaCheck")
    if check and not check.get("compatible"):
        parts = []
        if check.get("added"):
            parts.append("added: " + ", ".join(check["added"]))
        if check.get("removed"):
            parts.append("removed: " + ", ".join(check["removed"]))
        if check.get("changed"):
            parts.append("changed: " + ", ".join(f"{c['column']}: {c['was']} → {c['now']}" for c in check["changed"]))
        st.warning("The columns differ from the previous version. " + "; ".join(parts))
    if res.get("rowErrors"):
        st.table(pd.DataFrame(res["rowErrors"]))


def _render_file(f) -> dict | None:
    raw = f.getvalue()
    text, problem = prepare(f.name, raw)
    if problem:
        st.error(problem)
        return None
    key = file_key(f.name, raw)
    with st.expander(f"{f.name} · {len(raw):,} bytes", expanded=True):
        try:
            pv = _preview(f.name, text, key)
        except api_client.ApiError as e:
            st.error(str(e))
            return None
        if pv.get("status") != "ok":
            st.error(pv.get("message") or pv.get("reason") or str(pv.get("status")))
            return None
        st.dataframe(pd.DataFrame(pv["sampleRows"], columns=pv["columns"]), width="stretch", hide_index=True)
        match = pv.get("teTableMatch")
        mode = st.radio("Load as", [DYNAMIC, TE], index=1 if match else 0, key=f"mode-{key}", horizontal=True)
        if mode == TE:
            tables = _te_tables()
            target = st.selectbox("Into table", tables, index=tables.index(match) if match in tables else 0,
                                  key=f"tbl-{key}")
            payload, ready = build_payload(f.name, raw, text, mode="te", target=target), True
        else:
            types, renames, ready = _mapping_form(key, pv)
            payload = build_payload(f.name, raw, text, mode="dynamic", types=types, confirmed=ready, renames=renames)
        st.caption(NO_CANCEL + " (once you click Upload)")
        if st.button(f"Upload {f.name}", key=f"go-{key}", disabled=not ready):
            _send(f.name, payload, key)
        if key in ss.get("results", {}):
            _show_result(f.name, ss["results"][key])
    return {"key": key, "name": f.name, "payload": payload, "ready": ready}


def render() -> None:
    st.title("Upload")
    if not auth.can("upload"):
        st.info("Your role can't upload files.")
        return
    files = st.file_uploader("CSV files", type=["csv"], accept_multiple_files=True)
    st.caption("Saved mapping templates aren't available in this version.")
    rows = [r for r in (_render_file(f) for f in files) if r]
    if len(rows) > 1 and st.button("Upload all", disabled=not all(r["ready"] for r in rows)):
        bar = st.progress(0.0)
        for i, r in enumerate(rows, 1):
            _send(r["name"], r["payload"], r["key"])
            bar.progress(i / len(rows))
        st.rerun()
