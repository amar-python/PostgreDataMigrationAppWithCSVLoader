"""Helpers the Streamlit screens' headless tests share: Streamlit's AppTest runs a real screen against a faked API.

AppTest cannot switch to a page registered with st.navigation, so a screen is run by itself, as app.py runs it:
only for someone signed in, so a 401 that ends the session ends the run cleanly instead of failing.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "streamlit_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

ROLES = {"rita": "reviewer", "ada": "tenant_admin", "alice": "uploader", "audrey": "auditor"}

HARNESS = """
import sys
sys.path.insert(0, {app_dir!r})
import auth
from views import {view}
if auth.signed_in():
    {view}.render()
"""


def later(hours: float = 8) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def screen(view: str, who: str = "rita", token: str = "tok-1", tenant: str = "acme", timeout: int = 30) -> AppTest:
    """One screen (the module name in streamlit_app/views) with a session already in place, run once."""
    at = AppTest.from_string(HARNESS.format(app_dir=str(APP_DIR), view=view), default_timeout=timeout)
    at.session_state["session"] = {
        "token": token,
        "expiresAt": later(),
        "username": who,
        "tenant": tenant,
        "role": ROLES[who],
    }
    at.run()
    assert not at.exception, at.exception
    return at


def widget(elements, label: str):
    return next(e for e in elements if e.label == label)


def errors(at) -> list[str]:
    return [e.value for e in at.error]


def rerun(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, at.exception
    return at
