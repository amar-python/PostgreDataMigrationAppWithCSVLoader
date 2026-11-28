"""The upload and preview screen (#255): choose CSV files, check the columns, import them, and see what happened.

It replaces the React upload page (`_authenticated/index.tsx`) and is the #254 spike made ready to ship; the spike's
README found what to do about each of its seven questions. In short:

* **Preview** is the server's (`POST /api/csv/preview`), read from the first 512 KB, so a big file is not sent twice.
* **Column mapping** is ordinary widgets (a text box and a type box per column), not the canvas grid editor: the widgets
  have labels, and a browser test, a keyboard and a screen reader can use them. The Upload button waits for "I have
  checked the column names and types", and then `types` and `typesConfirmed: true` are sent (#195, #242).
* **No cancel:** the API cannot stop an import, so the screen says "Sent to the server; it can't be stopped now"
  before the click and while it runs (#188). A wait that runs out is not reported as "can't reach the API": the server
  may still be importing, so the screen says so and points to Import history.
* **Several files:** each has its own preview and mapping, and "Upload all" sends them in turn.
* **Mode:** a file shaped like a Test and Evaluation table starts as one (`teTableMatch`); the mapping and the
  confirmation are not offered there, because the API refuses a header mapping or `typesConfirmed` for a T&E load.
* **Endpoint:** the direct one, `POST /api/csv/upload`, as React uses.

Not carried over from React: saved mapping templates (the owner has not decided where they would live; they were kept
per browser, and Streamlit has no `localStorage`), the browser's upload report (this session's outcomes are shown
instead, and the server's record is Import history), and "Overwrite" (since M5 a repeated name is the next version, and
the API ignores the flag).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

import api_client
import auth
import exports
import history_model as h
import outcomes
import review_model as m
import upload_model as u

RESULTS = "upload_results"  # this session's outcomes, newest first (held by Streamlit on the server, not the browser)
GENERATION = "upload_generation"  # bumped to empty the file chooser after an upload
PREVIEWS = "upload_previews"  # a file's preview, by digest: the script re-runs on every click and must not re-ask
TE_TABLES = "upload_te_tables"
SHOWN_ERRORS = 50  # row errors shown for one upload; the report has all the server kept


def render() -> None:
    st.title("Upload")
    if not auth.can("upload"):
        st.info(f"The role {auth.current()['role']} can't upload files.")
        return
    st.write(
        "Choose CSV files, check the columns and types, then import. Each file becomes its own table. "
        f"The most a file may hold is {u.format_bytes(u.max_bytes())}."
    )
    generation = st.session_state.get(GENERATION, 0)
    chosen = st.file_uploader("CSV files", type=["csv"], accept_multiple_files=True, key=f"upload_files_{generation}")
    show([(f.name, f.getvalue()) for f in chosen])
    report()


# ── the files chosen ────────────────────────────────────────────────────────────────────────


def show(files: list[tuple[str, bytes]]) -> None:
    """One section per chosen file, and what to send. (Separate from the chooser so it can be tested with bytes.)"""
    ready = []
    files, repeated = u.chosen_once(files)
    for name in repeated:
        st.caption(f"{m.literal(name)} was chosen twice; it is shown once.")
    for name, raw in files:
        try:
            prepared = u.prepare(name, raw)
        except u.Refused as e:
            st.error(f"{m.literal(e.name)} {e.reason}")
            continue
        item = _one(prepared)
        if item:
            ready.append(item)
    if not ready:
        return
    if len(ready) > 1:
        st.write(f"{len(ready)} files are ready to check.")
        if st.button("Upload all", disabled=not all(i["ready"] for i in ready)):
            _send(ready)


def _preview(prepared: u.Prepared) -> dict | None:
    cache = st.session_state.setdefault(PREVIEWS, {})
    if prepared.digest not in cache:
        text, truncated = u.preview_text(prepared)
        try:
            pv = auth.call("POST", "/api/csv/preview", json={"fileName": prepared.name, "content": text})
        except api_client.ApiError as e:
            st.error(m.literal(prepared.name) + ": " + m.literal(e))
            return None
        pv["truncated"] = truncated
        pv["previewBytes"] = len(text.encode("utf-8"))
        cache[prepared.digest] = pv
    return cache[prepared.digest]


def _te_tables() -> list[str]:
    if TE_TABLES not in st.session_state:
        try:
            tables = auth.call("GET", "/api/te/tables")
        except api_client.ApiError:
            tables = []  # a suggestion only: loading as a new table still works
        st.session_state[TE_TABLES] = [t["table"] for t in tables if t.get("exists", True)]
    return st.session_state[TE_TABLES]


def _one(prepared: u.Prepared) -> dict | None:
    key = u.key_for(prepared)
    with st.expander(f"{u.format_bytes(len(prepared.raw))} · {m.literal(prepared.name)}", expanded=True):
        pv = _preview(prepared)
        if pv is None:
            return None
        if pv.get("status") != "ok":
            said = pv.get("message")
            st.error(
                m.literal(said)
                if said
                else outcomes.STRUCTURE_REASONS.get(str(pv.get("reason")), "No usable structure.")
            )
            return None
        rows = u.approx_rows(pv["totalRowsApprox"], pv["previewBytes"], len(prepared.raw), pv["truncated"])
        st.caption(f"{len(pv['headers'])} columns · {'about ' if pv['truncated'] else ''}{rows} data rows")
        st.table(u.sample_frame(pv))

        tables = _te_tables()
        mode = st.radio(
            "Load as",
            [u.DYNAMIC, u.TE],
            format_func=u.MODE_LABELS.__getitem__,
            horizontal=True,
            index=[u.DYNAMIC, u.TE].index(u.default_mode(pv, tables)),
            key=f"mode_{key}",
        )
        types, renames, confirmed, target = None, None, False, None
        if mode == u.TE:
            if not tables:
                st.warning("There are no Test and Evaluation tables to load into.")
            else:
                match = pv.get("teTableMatch")
                target = st.selectbox(
                    "Into table", tables, index=tables.index(match) if match in tables else 0, key=f"table_{key}"
                )
            st.caption(
                "The columns of a Test and Evaluation table are fixed, so the file's headers are matched to them "
                "as they are: nothing here can be renamed or retyped."
            )
        else:
            types, renames = _mapping(key, pv)
            confirmed = st.checkbox(u.CONFIRM, key=f"confirm_{key}")
        ok = u.ready(mode, confirmed, target)

        def build() -> dict:  # at the click only: encoding a big file for every re-run would be slow
            return u.build_payload(
                prepared, mode, types=types, renames=renames, headers=pv["headers"], confirmed=confirmed, target=target
            )

        st.caption(outcomes.NO_CANCEL + " (once you click Upload).")
        item = {"name": prepared.name, "build": build, "ready": ok}
        if st.button(f"Upload {m.literal(prepared.name)}", key=f"go_{key}", disabled=not ok):
            _send([item])
    return item


def _mapping(key: str, pv: dict) -> tuple[list[str], list[str]]:
    """A text box and a type box for each column, with the labels a screen reader needs. Returns (types, renames)."""
    st.markdown("**Columns** (leave a name blank to keep it)")
    types, renames = [], []
    for i, (header, column, inferred) in enumerate(zip(pv["headers"], pv["columns"], pv["inferredTypes"])):
        name, rename, kind = st.columns([2, 2, 2])
        name.markdown(m.literal(header))
        if column != header:
            name.caption(f"becomes {m.literal(column)}")
        # A label is Markdown even when hidden, and also the box's aria-label as written: see column_label.
        label = u.column_label(header, i)
        renames.append(
            rename.text_input(
                f"Rename {label}",
                key=f"rename_{key}_{i}",
                label_visibility="collapsed",
                placeholder="keep",
                max_chars=128,
            )
        )
        types.append(
            kind.selectbox(
                f"Type of {label}",
                u.ALLOWED_TYPES,
                index=u.ALLOWED_TYPES.index(inferred),
                format_func=u.TYPE_LABELS.__getitem__,
                key=f"type_{key}_{i}",
                label_visibility="collapsed",
            )
        )
    return types, renames


# ── sending ─────────────────────────────────────────────────────────────────────────────────


def _send(items: list[dict]) -> None:
    """Send each file in turn. The server cannot be asked to stop, so say so, and say what happened to every file."""
    bar = st.progress(0.0) if len(items) > 1 else None
    results = st.session_state.setdefault(RESULTS, [])
    for n, item in enumerate(items, 1):
        with st.spinner(f"{m.literal(item['name'])}: {outcomes.NO_CANCEL}"):
            res = None
            try:
                payload = item["build"]()
                res = auth.call("POST", "/api/csv/upload", json=payload, timeout=u.UPLOAD_TIMEOUT_SECONDS)
                outcome = outcomes.classify(item["name"], res)
            except api_client.ApiError as e:
                outcome = outcomes.classify_error(item["name"], e)
        results.insert(
            0,
            {
                "name": item["name"],
                "outcome": outcome,
                "res": res,
                "mapping": payload.get("headerMapping"),
                "at": datetime.now(timezone.utc).strftime("%H:%M UTC"),
            },
        )
        if bar:
            bar.progress(n / len(items))
    st.cache_data.clear()  # the history, the review picker and the files list now have something new
    st.session_state.pop(PREVIEWS, None)
    st.session_state[GENERATION] = st.session_state.get(GENERATION, 0) + 1  # empty the chooser: no accidental re-send
    st.rerun()


# ── what happened ───────────────────────────────────────────────────────────────────────────


def report() -> None:
    """This session's outcomes, newest first. The server's record, for everyone, is Import history."""
    results = st.session_state.get(RESULTS) or []
    if not results:
        return
    st.divider()
    st.subheader("Upload report")
    done = sum(r["outcome"].kind == "done" for r in results)
    st.caption(
        f"{len(results)} upload{'' if len(results) == 1 else 's'} in this session, {done} imported. "
        "Import history keeps the server's record."
    )
    for i, r in enumerate(results):
        _result(i, r)
    if st.button("Clear this report"):
        st.session_state[RESULTS] = []
        st.rerun()


def _result(i: int, r: dict) -> None:
    outcome, res = r["outcome"], r["res"] or {}
    box = {"success": st.success, "warning": st.warning}.get(outcome.level, st.error)
    box(f"{outcome.message}  \n{r['at']}")
    for note in outcomes.result_notes(res) if outcome.kind == "done" else []:
        st.caption(note)
    if outcome.kind == "done":
        st.caption("Open the Review page to look at the stored rows.")
    errors = res.get("rowErrors") or []
    if errors:
        st.table(h.errors_frame(errors[:SHOWN_ERRORS]))
        if len(errors) > SHOWN_ERRORS:
            st.caption(f"Showing the first {SHOWN_ERRORS} of {len(errors)} row errors: the report has them all.")
    rows = exports.error_rows(r["name"], errors, None, r["mapping"])
    if rows:
        one, two, three, _ = st.columns([1, 1, 1, 3])
        one.download_button(
            "Error report (CSV)",
            exports.to_csv(exports.ERROR_HEADERS, rows),
            exports.report_name("errors", "csv", r["name"]),
            exports.CSV_TYPE,
            key=f"up_csv_{i}",
        )
        two.download_button(
            "Error report (XLSX)",
            exports.to_xlsx("Errors", exports.ERROR_HEADERS, rows),
            exports.report_name("errors", "xlsx", r["name"]),
            exports.XLSX_TYPE,
            key=f"up_xlsx_{i}",
        )
        if res.get("logs"):
            body = json.dumps(
                {
                    "file": r["name"],
                    "status": res.get("status"),
                    "tableName": res.get("tableName"),
                    "generatedAt": datetime.now(timezone.utc).isoformat(),
                    "logs": res.get("logs"),
                    "rowErrors": errors,
                },
                indent=2,
            )
            three.download_button(
                "Processing logs (JSON)",
                body,
                exports.report_name("logs", "json", r["name"]),
                "application/json",
                key=f"up_log_{i}",
            )
