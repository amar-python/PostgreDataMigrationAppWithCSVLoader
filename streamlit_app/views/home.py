"""The first page after signing in: who you are and what your role can do."""

import streamlit as st

import auth

# What each action in api/auth.py PERMISSIONS means to a person. Screens are added by their own issues;
# this list says what the role may do, whether or not its screen exists yet.
LABELS = {
    "preview": "Preview a CSV file before importing it",
    "upload": "Upload CSV files",
    "list_files": "See the list of imported files",
    "read_rows": "Read the rows of an imported file",
    "list_te": "See the Test and Evaluation tables",
    "submit_import": "Submit an import for approval",
    "review_rows": "Review, edit and exclude rows",
    "approve_import": "Approve an import",
    "run_import": "Run an approved import",
    "delete_file": "Delete an imported file",
    "read_audit": "Read the audit log",
    "reset_password": "Reset another user's password",
}


def allowed_labels(role: str) -> list[str]:
    return [LABELS[a] for a in LABELS if role in auth.PERMISSIONS[a]]


def render() -> None:
    s = auth.current()
    st.title("CSV Table Hub")
    st.write(f"Signed in as **{s['username']}** in **{s['tenant']}**, with the role **{s['role']}**.")
    st.subheader("What your role can do")
    for label in allowed_labels(s["role"]):
        st.markdown(f"- {label}")
    st.caption("The server checks every request; this list only says what to expect.")
