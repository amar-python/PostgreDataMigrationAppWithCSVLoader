"""Sign-in, session expiry, sign-out and role gating for the Streamlit app (#251).

The session lives in st.session_state, which Streamlit keeps on the server for one browser tab: nothing
is written to the browser's storage. Ending a session clears ALL of it, and the caches too, so nothing
one tenant did is left for the next person to sign in (the class of bug #176 was).

The API stays the enforcer. Hiding a page a role cannot use is a courtesy, not the control.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NoReturn

import streamlit as st

import api_client

SESSION = "session"
NOTICE = "notice"  # one message for the sign-in page: why you were signed out
MIN_PASSWORD = 12  # api/services/accounts.py MIN_PASSWORD

# A copy of api/auth.py PERMISSIONS, so the app does not import the API's packages. A test fails if the
# two drift apart (tests/unit/test_streamlit_shell.py::test_the_permission_table_matches_the_api).
PERMISSIONS: dict[str, frozenset[str]] = {
    "preview":        frozenset({"uploader", "tenant_admin"}),
    "upload":         frozenset({"uploader", "tenant_admin"}),
    "list_files":     frozenset({"uploader", "reviewer", "tenant_admin", "auditor"}),
    "read_rows":      frozenset({"uploader", "reviewer", "tenant_admin", "auditor"}),
    "list_te":        frozenset({"uploader", "reviewer", "tenant_admin", "auditor"}),
    "delete_file":    frozenset({"tenant_admin"}),
    "read_audit":     frozenset({"tenant_admin", "auditor"}),
    "reset_password": frozenset({"tenant_admin"}),
    "review_rows":    frozenset({"reviewer", "tenant_admin"}),
    "submit_import":  frozenset({"uploader", "tenant_admin"}),
    "approve_import": frozenset({"reviewer", "tenant_admin"}),
    "run_import":     frozenset({"uploader", "reviewer", "tenant_admin"}),
}


def session() -> dict | None:
    return st.session_state.get(SESSION)


def current() -> dict:
    """The signed-in session, for the pages the navigation shows only after sign-in (app.py)."""
    s = session()
    if s is None:
        raise RuntimeError("no signed-in session: this page is only reachable after sign-in")
    return s


def signed_in() -> bool:
    return session() is not None


def can(action: str) -> bool:
    """May the signed-in role do this? Used to decide what to show; the API still checks."""
    s = session()
    return s is not None and s["role"] in PERMISSIONS[action]


def expired(s: dict, now: datetime | None = None) -> bool:
    """Is the session past `expiresAt`? An unreadable value counts as expired: fail closed."""
    try:
        at = datetime.fromisoformat(s["expiresAt"])
    except (KeyError, TypeError, ValueError):
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= at


def end_session(notice: str | None = None) -> None:
    """Forget everything: all session state and the caches. Optionally say why on the sign-in page."""
    st.session_state.clear()
    st.cache_data.clear()
    st.cache_resource.clear()
    if notice:
        st.session_state[NOTICE] = notice


def enforce_session() -> None:
    """Call at the top of every run: an expired session is a signed-out one."""
    s = session()
    if s is not None and expired(s):
        end_session("Your session has expired. Sign in again.")


def take_notice() -> str | None:
    return st.session_state.pop(NOTICE, None)


def sign_in(tenant: str, username: str, password: str) -> str | None:
    """Sign in. Returns None on success, or the message to show. Same wording as the React app."""
    try:
        new = api_client.request("POST", "/api/auth/login",
                                 json={"tenant": tenant, "username": username, "password": password})
    except api_client.Unauthorized:
        return "Invalid tenant, username or password"
    except api_client.ApiError as e:
        return str(e)
    end_session()  # start clean, so nothing of a previous person's state carries over
    st.session_state[SESSION] = new
    return None


def sign_out() -> None:
    """End the session on the server (best effort) and clear all state here."""
    s = session()
    if s is not None:
        try:
            api_client.request("POST", "/api/auth/logout", token=s["token"])
        except api_client.ApiError:
            pass  # the server may be down or the session already gone; either way it is over here
    end_session()


def lost_session() -> NoReturn:
    """The server says this session is over (any 401): forget everything, say why, and start the run again."""
    end_session("Your session has ended. Sign in again.")
    st.rerun()


def call(method: str, path: str, **kwargs):
    """Call the API as the signed-in user. Any 401 means the session is over: sign out and show why."""
    s = session()
    try:
        return api_client.request(method, path, token=s["token"] if s else None, **kwargs)
    except api_client.Unauthorized:
        lost_session()


def change_password(current: str, new: str) -> str | None:
    """Change your own password. Returns None on success, or the message to show."""
    try:
        call("POST", "/api/auth/password", json={"currentPassword": current, "newPassword": new})
    except api_client.ApiError as e:
        return f"The new password must be at least {MIN_PASSWORD} characters" if e.status == 422 else str(e)
    return None
