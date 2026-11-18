"""The Streamlit app shell (#251): sign-in, expiry, role gating, sign-out, change password.

Fast and headless: Streamlit's own AppTest runs the real app against a faked API, so no server, browser
or database is needed. What AppTest cannot do (switch to a page registered with st.navigation, or watch a
real browser tab) is covered by e2e/test_streamlit_shell.py.

The things worth failing loudly: a wrong sign-in says what the React app says; an expired or revoked
session ends up signed out with a reason; sign-out leaves nothing for the next tenant (#176); what a role
is shown matches what the API will allow; and the Streamlit version stays pinned with telemetry off.
"""
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone

import pytest
import streamlit as st
from streamlit.proto.TextInput_pb2 import TextInput as TextInputProto
from streamlit.testing.v1 import AppTest

# The harness import sets sys.path for the app, so it must come before the app imports below.
from tests.unit.streamlit_harness import APP_DIR, PASSWORD, ROOT, later, view
import api_client
import auth
from api.auth import PERMISSIONS as API_PERMISSIONS
from views import home

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _open() -> AppTest:
    return AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=30).run()


def _sign_in(at: AppTest, tenant="acme", username="alice", password=PASSWORD) -> AppTest:
    at.text_input[0].input(tenant)
    at.text_input[1].input(username)
    at.text_input[2].input(password)
    at.button[0].click()
    return at.run()


def _signed_in(who=("acme", "alice")) -> AppTest:
    return _sign_in(_open(), *who, PASSWORD)


def _errors(at):
    return [e.value for e in at.error]


# ── sign-in ───────────────────────────────────────────────────────────────────────────────

def test_a_signed_out_visitor_sees_only_the_sign_in_page(api):
    at = _open()

    assert [t.value for t in at.title] == ["Sign in"]
    assert [t.label for t in at.text_input] == ["Tenant", "Username", "Password"]
    assert [t.proto.type for t in at.text_input] == [TextInputProto.DEFAULT, TextInputProto.DEFAULT,
                                                     TextInputProto.PASSWORD], "the password is masked"
    assert not at.exception and not at.sidebar.button, "no sign-out, no session menu"
    assert api.calls == [], "nothing is asked of the API until someone signs in"


@pytest.mark.parametrize("tenant, username, password", [
    ("acme", "alice", "wrong password entirely"),
    ("acme", "nobody", PASSWORD),
    ("nowhere", "alice", PASSWORD),
])
def test_a_wrong_sign_in_says_what_the_react_app_says_and_gives_no_hint_which_part(api, tenant, username, password):
    at = _sign_in(_open(), tenant, username, password)

    assert _errors(at) == ["Invalid tenant, username or password"]
    assert "session" not in at.session_state
    assert [t.value for t in at.title] == ["Sign in"]


def test_signing_in_shows_who_you_are_and_your_role(api):
    at = _signed_in(("acme", "rita"))

    assert not at.exception
    assert [t.value for t in at.title] == ["CSV Table Hub"]
    side = " ".join(m.value for m in at.sidebar.markdown)
    assert "rita" in side and "acme" in side and "reviewer" in side
    assert [b.label for b in at.sidebar.button] == ["Sign out"]
    assert at.session_state["session"]["token"] == "tok-1"


def test_the_tenant_and_username_are_trimmed(api):
    _sign_in(_open(), "  acme ", " alice  ")

    assert api.calls_to("/api/auth/login")[0][3] == {"tenant": "acme", "username": "alice", "password": PASSWORD}


def test_an_unreachable_api_says_so_instead_of_a_wrong_password(api):
    api.down = True
    at = _sign_in(_open())

    assert _errors(at) == [f"Can't reach the API at {api_client.API_URL}. Is it running?"]
    assert "session" not in at.session_state


def test_another_api_error_shows_the_servers_own_message(monkeypatch):
    def refuse(method, path, token=None, **kwargs):
        raise api_client.ApiError(429, "Too many sign-in attempts. Try again later.")

    monkeypatch.setattr(api_client, "request", refuse)
    assert _errors(_sign_in(_open())) == ["Too many sign-in attempts. Try again later."]


# ── expiry and a revoked session ──────────────────────────────────────────────────────────

def test_an_expired_session_is_signed_out_with_a_reason_and_nothing_left_over(api):
    at = _open()
    at.session_state["session"] = {"token": "t", "expiresAt": later(-1), "username": "alice",
                                   "tenant": "acme", "role": "uploader"}
    at.session_state["leftover"] = "something acme's"
    at.run()

    assert [t.value for t in at.title] == ["Sign in"]
    assert [w.value for w in at.warning] == ["Your session has expired. Sign in again."]
    assert "session" not in at.session_state and "leftover" not in at.session_state


def test_the_reason_is_shown_once(api):
    at = _open()
    at.session_state["session"] = {"token": "t", "expiresAt": later(-1), "username": "a", "tenant": "b",
                                   "role": "uploader"}
    at.run()
    assert len(at.warning) == 1

    at.run()  # any later click

    assert len(at.warning) == 0


def test_a_session_that_has_not_expired_stays(api):
    at = _signed_in()
    at.run()
    assert "session" in at.session_state and [t.value for t in at.title] == ["CSV Table Hub"]


@pytest.mark.parametrize("value", ["", None, "not a date", "2026-13-45T00:00:00"])
def test_an_unreadable_expiry_counts_as_expired(value):
    assert auth.expired({"expiresAt": value}) is True
    assert auth.expired({}) is True


def test_expiry_is_read_in_utc_and_the_boundary_is_expired():
    at = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    assert auth.expired({"expiresAt": at.isoformat()}, now=at) is True
    assert auth.expired({"expiresAt": at.isoformat()}, now=at - timedelta(seconds=1)) is False
    assert auth.expired({"expiresAt": "2026-11-18T12:00:00"}, now=at - timedelta(seconds=1)) is False, "naive means UTC"
    assert auth.expired({"expiresAt": "2026-11-18T22:00:00+10:00"}, now=at) is True, "an offset is honoured"


# ── a view's API call that gets a 401 ─────────────────────────────────────────────────────

def _change(at: AppTest, current, new, confirm) -> AppTest:
    at.text_input[0].input(current)
    at.text_input[1].input(new)
    at.text_input[2].input(confirm)
    at.button[0].click()
    return at.run()


def test_a_401_from_any_call_ends_the_session_and_says_why(api):
    at = view("change_password", api=api)
    api.dead.add("tok-v")  # revoked on the server, for instance by a password change elsewhere

    _change(at, PASSWORD, "a brand new passphrase", "a brand new passphrase")

    assert "session" not in at.session_state
    assert at.session_state["notice"] == "Your session has ended. Sign in again."


# ── sign-out ──────────────────────────────────────────────────────────────────────────────

def test_sign_out_revokes_the_session_and_leaves_nothing_behind(api):
    at = _signed_in()
    token = at.session_state["session"]["token"]
    at.session_state["leftover"] = "acme's selected upload"
    at.sidebar.button[0].click().run()

    assert api.calls_to("/api/auth/logout")[0][2] == token and token in api.dead
    assert [t.value for t in at.title] == ["Sign in"]
    assert "session" not in at.session_state and "leftover" not in at.session_state


def test_sign_out_still_clears_everything_when_the_api_is_down(api):
    at = _signed_in()
    api.down = True
    at.session_state["leftover"] = "x"
    at.sidebar.button[0].click().run()

    assert "session" not in at.session_state and "leftover" not in at.session_state
    assert [t.value for t in at.title] == ["Sign in"]


def test_the_caches_are_cleared_too(api, monkeypatch):
    cleared = []
    monkeypatch.setattr(st.cache_data, "clear", lambda *a, **k: cleared.append("data"))
    monkeypatch.setattr(st.cache_resource, "clear", lambda *a, **k: cleared.append("resource"))

    at = _signed_in()
    cleared.clear()
    at.sidebar.button[0].click().run()

    assert "data" in cleared and "resource" in cleared


def test_the_next_person_to_sign_in_gets_a_clean_slate(api):
    at = _signed_in(("acme", "alice"))
    at.session_state["acme_only"] = "an upload id from acme"
    at.sidebar.button[0].click().run()

    _sign_in(at, "zed", "zoe")

    assert at.session_state["session"]["tenant"] == "zed"
    assert "acme_only" not in at.session_state
    assert at.session_state["session"]["token"] != "tok-1"


def test_signing_in_starts_from_a_clean_state_even_if_something_was_left(api):
    at = _open()
    at.session_state["stale"] = "left by an earlier session"

    _sign_in(at)

    assert "stale" not in at.session_state and "session" in at.session_state


# ── roles ─────────────────────────────────────────────────────────────────────────────────

def _listed(at) -> list[str]:
    return [m.value.removeprefix("- ") for m in at.markdown if m.value.startswith("- ")]


@pytest.mark.parametrize("who, role", [
    (("acme", "alice"), "uploader"), (("acme", "rita"), "reviewer"),
    (("acme", "ada"), "tenant_admin"), (("acme", "audrey"), "auditor"),
])
def test_home_lists_exactly_what_the_api_will_allow_that_role(api, who, role):
    at = _signed_in(who)

    expected = [home.LABELS[a] for a in home.LABELS if role in API_PERMISSIONS[a]]
    assert _listed(at) == expected and expected, role


def test_role_differences_are_visible_and_hold_the_other_way_round(api):
    uploader, auditor, reviewer = (_listed(_signed_in(w)) for w in
                                   [("acme", "alice"), ("acme", "audrey"), ("acme", "rita")])

    assert "Upload CSV files" in uploader and "Upload CSV files" not in auditor
    assert "Read the audit log" in auditor and "Read the audit log" not in uploader
    assert "Approve an import" in reviewer and "Approve an import" not in uploader
    assert "Delete an imported file" not in reviewer


def test_can_follows_the_role_and_is_false_when_signed_out(api):
    script = """
import sys
sys.path.insert(0, {app_dir!r})
import streamlit as st
import auth
st.session_state["_can"] = {{a: auth.can(a) for a in auth.PERMISSIONS}}
""".format(app_dir=str(APP_DIR))

    out = AppTest.from_string(script).run()
    assert not any(out.session_state["_can"].values()), "signed out: nothing is allowed"

    at = AppTest.from_string(script)
    at.session_state["session"] = {"token": "t", "expiresAt": later(), "role": "auditor"}
    can = at.run().session_state["_can"]
    assert can["read_audit"] and can["list_files"]
    assert not can["upload"] and not can["review_rows"] and not can["delete_file"]


def test_the_permission_table_matches_the_api():
    assert auth.PERMISSIONS == API_PERMISSIONS, "streamlit_app/auth.py has drifted from api/auth.py"


def test_every_permission_has_a_plain_label():
    assert set(home.LABELS) == set(auth.PERMISSIONS)


# ── change password ───────────────────────────────────────────────────────────────────────

def test_change_password_success_keeps_this_session_and_says_so(api):
    at = view("change_password", api=api)

    _change(at, PASSWORD, "a brand new passphrase", "a brand new passphrase")

    assert [s.value for s in at.success] == [
        "Password changed. You're still signed in here; any other sessions have been signed out."]
    assert "session" in at.session_state
    assert api.calls_to("/api/auth/password")[0][3] == {"currentPassword": PASSWORD,
                                                        "newPassword": "a brand new passphrase"}
    # The browser empties the fields after the submit; AppTest does not emulate that, so check the form is set to.
    form = next(c for c in at.main.children.values() if c.type == "form")
    assert form.proto.form.clear_on_submit is True, "the passwords are not left in the form"


def test_a_wrong_current_password_shows_the_servers_message_and_keeps_the_session(api):
    at = view("change_password", api=api)

    _change(at, "not my password", "a brand new passphrase", "a brand new passphrase")

    assert _errors(at) == ["Current password is incorrect"]
    assert "session" in at.session_state


def test_a_short_new_password_is_refused_before_the_api_is_asked(api):
    at = view("change_password", api=api)

    _change(at, PASSWORD, "too short", "too short")

    assert _errors(at) == ["The new password must be at least 12 characters"]
    assert api.calls_to("/api/auth/password") == []


def test_passwords_that_do_not_match_are_refused_before_the_api_is_asked(api):
    at = view("change_password", api=api)

    _change(at, PASSWORD, "a brand new passphrase", "a different passphrase")

    assert _errors(at) == ["The new passwords don't match."]
    assert api.calls_to("/api/auth/password") == []


def test_empty_fields_are_refused(api):
    at = view("change_password", api=api)

    _change(at, "", "", "")

    assert _errors(at) == ["Enter your current password and a new one."]
    assert api.calls_to("/api/auth/password") == []


def test_a_422_from_the_api_is_explained_in_the_same_words(api):
    at = view("change_password", api=api)
    api.password_error = (422, "String should have at least 12 characters")

    _change(at, PASSWORD, "a brand new passphrase", "a brand new passphrase")

    assert _errors(at) == ["The new password must be at least 12 characters"]


# ── configuration ─────────────────────────────────────────────────────────────────────────

def test_usage_statistics_are_off():
    """Streamlit sends them by default; this app is for on-premises and air-gapped installs."""
    config = tomllib.loads((APP_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["browser"]["gatherUsageStats"] is False


def test_streamlit_is_pinned_to_the_version_the_tests_run_against():
    pinned = [ln.strip() for ln in (APP_DIR / "requirements.txt").read_text().splitlines()
              if ln.strip().startswith("streamlit")]
    assert pinned == [f"streamlit=={st.__version__}"], "bump the pin and the tests together"
    dev = (ROOT / "requirements-dev.txt").read_text()
    assert f"streamlit=={st.__version__}" in dev, "CI installs it for these tests"


def test_no_argument_that_streamlit_has_deprecated_is_used():
    """The #154 spike's use_container_width is past its removal date in 1.67; use width="stretch"."""
    offenders = [p.name for p in APP_DIR.rglob("*.py") if "use_container_width" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_the_api_address_comes_from_the_environment():
    code = f"import sys; sys.path.insert(0, {str(APP_DIR)!r}); import api_client; print(api_client.API_URL)"

    def run(api_url):
        env = {k: v for k, v in os.environ.items() if k != "API_URL"}
        if api_url is not None:
            env["API_URL"] = api_url
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                              check=True).stdout.strip()

    assert run("http://api.internal:9000/") == "http://api.internal:9000", "no trailing slash"
    assert run(None) == "http://localhost:8000", "the default is the local API"
