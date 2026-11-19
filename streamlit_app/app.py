"""CSV Table Hub, Streamlit front end. Step 1 of the migration (#212): the shell, #251.

Run from this folder, so Streamlit finds .streamlit/config.toml:

    cd streamlit_app && python -m streamlit run app.py

API_URL (default http://localhost:8000) says where the API is.
"""

import streamlit as st

import auth
from views import change_password, files, history, home, review, sign_in, upload

st.set_page_config(page_title="CSV Table Hub", layout="wide")

auth.enforce_session()  # an expired session is a signed-out one

if not auth.signed_in():
    page = st.navigation([st.Page(sign_in.render, title="Sign in", url_path="sign-in")], position="hidden")
else:
    # Later screens are added here, each behind auth.can("<action>"), by their own issues.
    pages = [st.Page(home.render, title="Home", url_path="home", default=True)]
    if auth.can("upload"):
        pages.append(st.Page(upload.render, title="Upload", url_path="upload"))  # #255
    if auth.can("list_files"):
        pages.append(st.Page(files.render, title="Imported files", url_path="files"))  # #255
    if auth.can("list_files") and auth.can("read_rows"):
        pages.append(st.Page(review.render, title="Review", url_path="review"))  # #252
    if auth.can("list_files"):
        pages.append(st.Page(history.render, title="Import history", url_path="history"))  # #253
    pages.append(st.Page(change_password.render, title="Change password", url_path="change-password"))
    page = st.navigation(pages)
    s = auth.session()
    with st.sidebar:
        st.markdown(f"**{s['username']}** · {s['tenant']}  \n`{s['role']}`")
        if st.button("Sign out"):
            auth.sign_out()
            st.rerun()

page.run()
