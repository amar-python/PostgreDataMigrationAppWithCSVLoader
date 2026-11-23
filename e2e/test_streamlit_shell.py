"""The Streamlit app shell (#251) in a real browser, against the real API.

What the headless tests (tests/unit/test_streamlit_shell.py) cannot show: real navigation between pages,
a real browser tab and its storage, and the real API's answers instead of a fake's. Includes the port of
#176 (e2e/test_react_ui.py): signing out leaves nothing for the next tenant.
"""

from __future__ import annotations

import re
import uuid

from playwright.sync_api import expect
from psycopg2 import sql

from api import db  # noqa: F401  (the stack fixture has opened the pool)
from api.config import settings
from api.db import Conn
from api.services import accounts
from conftest import PASSWORD, shell_sign_in, shell_sign_in_as

NEW_PASSWORD = "a brand new passphrase 42"


def _signed_in_as(page, role: str) -> None:
    page.get_by_role("button", name="Sign out").wait_for()
    expect(page.locator('[data-testid="stSidebar"]').get_by_text(role, exact=True)).to_be_visible()


def _sign_out(page) -> None:
    page.get_by_role("button", name="Sign out").click()
    page.get_by_role("heading", name="Sign in").wait_for()


def test_a_wrong_password_is_refused_in_the_react_apps_words(page, stack):
    a = stack.accounts["admin"]

    shell_sign_in_as(page, stack, a.tenant, a.username, "definitely not the password")

    expect(page.get_by_text("Invalid tenant, username or password")).to_be_visible()
    expect(page.get_by_role("button", name="Sign out")).to_have_count(0)


def test_signing_in_shows_who_where_and_in_what_role_and_says_what_the_role_can_do(page, stack):
    a = stack.accounts["uploader"]
    shell_sign_in(page, stack, "uploader")
    _signed_in_as(page, "uploader")

    side = page.locator('[data-testid="stSidebar"]')
    expect(side.get_by_text(a.username)).to_be_visible()
    expect(side.get_by_text(a.tenant, exact=False)).to_be_visible()
    expect(page.get_by_role("heading", name="CSV Table Hub")).to_be_visible()
    expect(page.get_by_text("Upload CSV files")).to_be_visible()
    expect(page.get_by_text("Read the audit log")).to_have_count(0)  # an uploader may not


def test_a_reviewer_is_shown_review_and_not_upload(page, stack):
    shell_sign_in(page, stack, "reviewer")
    _signed_in_as(page, "reviewer")

    expect(page.get_by_text("Review, edit and exclude rows")).to_be_visible()
    expect(page.get_by_text("Upload CSV files")).to_have_count(0)


def test_176_signing_out_leaves_nothing_for_the_next_tenant(page, stack):
    """Port of #176: the next tenant sees none of the previous one, on the page or in the browser.

    The shell has no data screens yet, so today this shows that the page and the browser's storage hold no
    trace of the first tenant's name or username (with a control that they were there). It becomes a real
    isolation test when the review and history screens (#252, #253) put tenant data on the page; the
    headless tests already pin that sign-out clears every piece of session state.
    """
    first, second = stack.accounts["admin"], stack.accounts["other"]
    shell_sign_in(page, stack, "admin")
    _signed_in_as(page, "tenant_admin")
    # Control: this tenant's own name is on the page, so "not on the page" below means something.
    expect(page.get_by_text(first.tenant, exact=False).first).to_be_visible()
    _sign_out(page)
    page.reload()
    page.get_by_role("heading", name="Sign in").wait_for()
    expect(page.get_by_role("button", name="Sign out")).to_have_count(0)  # a reload does not bring it back

    shell_sign_in(page, stack, "other")
    _signed_in_as(page, "tenant_admin")
    page.wait_for_timeout(1000)  # a negative check needs the page to have finished loading
    body = page.locator("body").inner_text()
    assert second.tenant in body
    assert first.tenant not in body and first.username not in body

    stored = page.evaluate("() => document.cookie + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")
    for secret in (first.tenant, first.username, second.username):
        assert secret not in stored, f"{secret!r} was written to the browser's storage"


def test_changing_your_own_password_works_through_the_real_api_and_the_old_one_stops_working(page, stack):
    a = stack.accounts["admin"]
    username = f"pw_{uuid.uuid4().hex[:8]}"
    with Conn() as conn, conn.cursor() as cur:
        uid = accounts.create_user(cur, username, PASSWORD)
        accounts.add_membership(cur, uid, accounts.tenant_id(cur, a.tenant), "uploader")
        conn.commit()
    try:
        shell_sign_in_as(page, stack, a.tenant, username, PASSWORD)
        _signed_in_as(page, "uploader")

        page.get_by_role("link", name="Change password").click()
        page.get_by_role("heading", name="Change password").wait_for()
        page.get_by_label("Current password").fill(PASSWORD)
        page.get_by_label("New password", exact=True).fill(NEW_PASSWORD)
        page.get_by_label("Confirm new password").fill(NEW_PASSWORD)
        page.get_by_role("button", name="Change password").click()
        expect(page.get_by_text("Password changed. You're still signed in here")).to_be_visible()
        expect(page.get_by_role("button", name="Sign out")).to_be_visible()  # this session stays

        _sign_out(page)
        shell_sign_in_as(page, stack, a.tenant, username, PASSWORD)  # the old password
        expect(page.get_by_text("Invalid tenant, username or password")).to_be_visible()
        shell_sign_in_as(page, stack, a.tenant, username, NEW_PASSWORD)
        _signed_in_as(page, "uploader")
    finally:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE username = %s").format(
                sql.Identifier(settings.CONTROL_SCHEMA)), (username,))
            conn.commit()


def test_a_wrong_current_password_keeps_the_session_and_says_so(page, stack):
    shell_sign_in(page, stack, "admin")
    _signed_in_as(page, "tenant_admin")

    page.get_by_role("link", name="Change password").click()
    page.get_by_role("heading", name="Change password").wait_for()
    page.get_by_label("Current password").fill("not my password at all")
    page.get_by_label("New password", exact=True).fill(NEW_PASSWORD)
    page.get_by_label("Confirm new password").fill(NEW_PASSWORD)
    page.get_by_role("button", name="Change password").click()

    expect(page.get_by_text("Current password is incorrect")).to_be_visible()
    expect(page.get_by_role("button", name="Sign out")).to_be_visible()


def test_a_session_ended_on_the_server_sends_the_next_click_back_to_sign_in(page, stack):
    """A 401 from the real API (here: the session was revoked elsewhere) ends the session with a reason."""
    a = stack.accounts["admin"]
    shell_sign_in(page, stack, "admin")
    _signed_in_as(page, "tenant_admin")
    page.get_by_role("link", name="Change password").click()
    page.get_by_role("heading", name="Change password").wait_for()

    with Conn() as conn, conn.cursor() as cur:  # as the API does when a password is reset: revoke the user's sessions
        cur.execute(sql.SQL("UPDATE {c}.sessions SET revoked_at = now() WHERE user_id = "
                            "(SELECT id FROM {c}.users WHERE username = %s)").format(
                                c=sql.Identifier(settings.CONTROL_SCHEMA)), (a.username,))
        conn.commit()

    page.get_by_label("Current password").fill(PASSWORD)
    page.get_by_label("New password", exact=True).fill(NEW_PASSWORD)
    page.get_by_label("Confirm new password").fill(NEW_PASSWORD)
    page.get_by_role("button", name="Change password").click()

    expect(page.get_by_text(re.compile("Your session has ended. Sign in again."))).to_be_visible()
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
