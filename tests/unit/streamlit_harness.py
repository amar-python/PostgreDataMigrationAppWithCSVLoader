"""Shared AppTest harness for the Streamlit screens: a faked API, the users it knows, and a way to render one view.

Import what a test file needs; the `api` fixture is a pytest fixture, so import it by name too.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "streamlit_app"
sys.path.insert(0, str(APP_DIR))

import api_client  # noqa: E402

PASSWORD = "correct horse battery"
USERS = {
    ("acme", "alice"): "uploader",
    ("acme", "rita"): "reviewer",
    ("acme", "ada"): "tenant_admin",
    ("acme", "audrey"): "auditor",
    ("zed", "zoe"): "tenant_admin",
}


def later(hours: float = 8) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class FakeApi:
    """Stands in for api_client.request: the endpoints the shell uses, with the API's own wording.

    `routes` adds endpoints on top of those: a value is returned as it is, or a callable is called with
    (token, **kwargs) and its result returned (it may raise, e.g. api_client.Unauthorized).
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self.down = False
        self.tokens: dict[str, tuple[str, str]] = {}
        self.dead: set[str] = set()
        self.password_error: tuple[int, str] | None = None
        self.routes: dict[tuple[str, str], object] = {}

    def __call__(self, method, path, token=None, **kwargs):
        self.calls.append((method, path, token, kwargs.get("json")))
        if self.down:
            raise api_client.Unreachable()
        if path == "/api/auth/login":
            body = kwargs["json"]
            who = (body["tenant"], body["username"])
            if who not in USERS or body["password"] != PASSWORD:
                raise api_client.Unauthorized(401, "Invalid tenant, username or password")
            tok = f"tok-{len(self.tokens) + 1}"
            self.tokens[tok] = who
            return {"token": tok, "expiresAt": later(), "username": who[1], "tenant": who[0],
                    "role": USERS[who]}
        if token is None or token in self.dead or token not in self.tokens:
            raise api_client.Unauthorized(401, "Not signed in")
        if (method, path) in self.routes:
            value = self.routes[(method, path)]
            return value(token, **kwargs) if callable(value) else value
        if path == "/api/auth/logout":
            self.dead.add(token)
            return {"status": "ok"}
        if path == "/api/auth/password":
            if self.password_error:
                raise api_client.ApiError(*self.password_error)
            if kwargs["json"]["currentPassword"] != PASSWORD:
                raise api_client.ApiError(400, "Current password is incorrect")
            return {"status": "ok"}
        raise AssertionError(f"unexpected call {method} {path}")

    def calls_to(self, path):
        return [c for c in self.calls if c[1] == path]


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(api_client, "request", fake)
    return fake


HARNESS = """
import sys
sys.path.insert(0, {app_dir!r})
import streamlit as st
import auth
from views import {view}
{view}.render()
"""


def view(name: str, who=("acme", "alice"), api: FakeApi | None = None) -> AppTest:
    """Render one view with a session already in place (AppTest cannot switch to st.navigation pages)."""
    at = AppTest.from_string(HARNESS.format(app_dir=str(APP_DIR), view=name), default_timeout=30)
    if api is not None:
        api.tokens["tok-v"] = who
        at.session_state["session"] = {"token": "tok-v", "expiresAt": later(), "username": who[1],
                                       "tenant": who[0], "role": USERS[who]}
    return at.run()
