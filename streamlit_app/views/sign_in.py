"""The sign-in page, shown to anyone without a live session."""

import streamlit as st

import auth


def render() -> None:
    st.title("Sign in")
    notice = auth.take_notice()
    if notice:
        st.warning(notice)
    with st.form("sign_in"):
        tenant = st.text_input("Tenant")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        error = auth.sign_in(tenant.strip(), username.strip(), password)
        if error is None:
            st.rerun()
        st.error(error)
