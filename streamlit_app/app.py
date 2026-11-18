"""CSV Table Hub, Streamlit front end. Step 1 of the migration (#212): the shell, #251.

Run from this folder, so Streamlit finds .streamlit/config.toml:

    cd streamlit_app && python -m streamlit run app.py

API_URL (default http://localhost:8000) says where the API is.
"""

import importlib

import streamlit as st

import auth
import views
from views import change_password, home, sign_in

st.set_page_config(page_title="CSV Table Hub", layout="wide")

auth.enforce_session()  # an expired session is a signed-out one

if not auth.signed_in():
    page = st.navigation([st.Page(sign_in.render, title="Sign in", url_path="sign-in")], position="hidden")
else:
    s = auth.session()
    titles = {path: title for _action, title, path in views.SCREENS}
    pages = [
        st.Page(home.render, title="Home", url_path="home", default=True),
        *[st.Page(importlib.import_module(f"views.{path}").render, title=titles[path], url_path=path)
          for path in views.allowed_screens(s["role"])],  # screens are added in views/__init__.py
        st.Page(change_password.render, title="Change password", url_path="change-password"),
    ]
    page = st.navigation(pages)
    with st.sidebar:
        st.markdown(f"**{s['username']}** · {s['tenant']}  \n`{s['role']}`")
        if st.button("Sign out"):
            auth.sign_out()
            st.rerun()

page.run()
