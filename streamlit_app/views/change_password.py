"""Change your own password (#117). This session stays; the server ends all the others."""

import streamlit as st

import auth


def render() -> None:
    st.title("Change password")
    with st.form("change_password", clear_on_submit=True):
        current = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Change password")
    st.caption(f"At least {auth.MIN_PASSWORD} characters.")
    if not submitted:
        return
    if not current or not new:
        st.error("Enter your current password and a new one.")
    elif len(new) < auth.MIN_PASSWORD:
        st.error(f"The new password must be at least {auth.MIN_PASSWORD} characters")
    elif new != confirm:
        st.error("The new passwords don't match.")
    else:
        error = auth.change_password(current, new)
        if error is None:
            st.success("Password changed. You're still signed in here; any other sessions have been signed out.")
        else:
            st.error(error)
