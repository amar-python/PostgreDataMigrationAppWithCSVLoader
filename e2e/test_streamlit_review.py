"""The Streamlit review screen (#252) in a real browser, against the real API.

What the headless tests (tests/unit/test_streamlit_review.py) cannot show: a click on the grid (drawn on a
canvas, so clicked by coordinates), the grid and the "Row number" box staying in step, Enter submitting a
form, a real session the server ends, and what a browser makes of text from a file. They also carry over the
four tests of the #154 spike's screen, which this screen replaces.
"""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect
from psycopg2 import sql

from api import db  # noqa: F401  (the stack fixture has opened the pool)
from api.config import settings
from api.db import Conn
from conftest import PASSWORD, shell_sign_in

# 30 rows; every seventh amount is "x", so rows 7, 14, 21 and 28 fail the int8 type.
ROWS = "".join(f"{i},person{i},{'x' if i % 7 == 0 else i * 10}\n" for i in range(1, 31))


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}.csv"


@pytest.fixture(scope="module")
def upload(stack):
    name = _unique("people")
    res = stack.upload("admin", name, "id,name,amount\n" + ROWS, types=["int8", "text", "int8"])
    assert res["status"] == "ok" and res["failedRows"] == 4, res
    return name


def _idle(page) -> None:
    """Streamlit re-runs the script after each action and builds the page as it goes: a click on a control that
    is about to be rebuilt is lost. Wait until the run has finished (its "Running" indicator is gone)."""
    expect(page.locator('[data-testid="stStatusWidget"]')).to_have_count(0)


def _choose_option(page, combobox: str, option: re.Pattern | str) -> None:
    """Open a Streamlit select box and pick an option, trying again if the page rebuilt the box under the click."""
    for attempt in range(3):
        _idle(page)
        page.get_by_role("combobox", name=combobox).click()
        choice = page.get_by_role("option", name=option)
        try:
            choice.wait_for(timeout=4000)
            choice.click()
            return
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise
            page.keyboard.press("Escape")


def _open_review(page, stack, who: str, name: str | None = None) -> None:
    """Sign in, go to the Review page and, if given, choose that upload."""
    shell_sign_in(page, stack, who)
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Review").click()
    page.get_by_role("heading", name="Review", exact=True).wait_for()
    if name:
        _choose_upload(page, name)


def _choose_upload(page, name: str) -> None:
    _choose_option(page, "Upload", re.compile(re.escape(name)))
    expect(page.get_by_role("heading", name=name)).to_be_visible()


def _select_row(page, index: int) -> None:
    """st.dataframe draws on a canvas: click the selection checkbox of the row at `index` (0 is the first).

    Streamlit re-runs the script after every action and redraws the grid, so a click can land before it is
    ready: try again if the row's detail panel does not appear.
    """
    grid = page.locator('[data-testid="stDataFrame"]').first
    heading = page.get_by_role("heading", name=f"Row {index + 1}")
    for attempt in range(3):
        grid.wait_for()
        grid.scroll_into_view_if_needed()  # the page above the grid is tall, so its lower rows can be below the fold
        box = grid.bounding_box()
        page.mouse.click(box["x"] + 15, box["y"] + 35 + 35 * index + 17)
        try:
            heading.wait_for(timeout=5000)
            return
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise


def _row_number_box(page):
    """The live "Row number" box. While a run rebuilds the page, Streamlit keeps the previous run's elements on
    screen, marked data-stale="true", so the old upload's box can sit beside the new one for a moment."""
    live = page.locator('[data-testid="stElementContainer"]:not([data-stale="true"])')
    return live.get_by_role("spinbutton", name="Row number", exact=True)


def _type_row_number(page, n: int) -> None:
    box = _row_number_box(page)
    heading = page.get_by_role("heading", name=f"Row {n}")
    for attempt in range(3):
        _idle(page)
        box.fill(str(n))
        box.press("Enter")
        try:
            heading.wait_for(timeout=5000)
            return
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise


# ── what the old spike's tests checked, on the real screen ─────────────────────────────────────────

def test_an_uploader_can_look_but_not_change(page, stack, upload):
    _open_review(page, stack, "uploader", upload)
    expect(page.get_by_text("Only reviewers and tenant admins can make changes.")).to_be_visible()

    _select_row(page, 13)  # row 14: amount "x" (the grid shows about 15 rows; the others are typed by number)

    expect(page.get_by_text('"x" is not a whole number', exact=False)).to_be_visible()
    expect(page.get_by_text("History", exact=True)).to_be_visible()
    expect(page.get_by_role("tab", name="Edit a cell")).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("Exclude|Include|Save"))).to_have_count(0)


def test_a_reviewer_edits_with_a_required_reason_by_pressing_enter_and_it_shows_in_the_history(page, stack, upload):
    _open_review(page, stack, "reviewer", upload)
    _select_row(page, 6)  # row 7: amount "x"
    _choose_option(page, "Column", re.compile(r"^amount"))
    expect(page.get_by_text(re.compile(r"Original value: x\b"))).to_be_visible()
    # Until the run ends, the previous column's "New value" box is still on the page beside the new one.
    _idle(page)
    expect(page.get_by_label("New value")).to_have_count(1)

    page.get_by_label("New value").fill("70")
    reason = page.get_by_label("Reason for the change (required)")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text("A reason is required")).to_be_visible()  # refused before anything is sent
    reason.fill("typo in source")
    reason.press("Enter")  # in a form, Enter saves: no waiting for focus to leave the box

    expect(page.get_by_text("Saved: row 7, amount.")).to_be_visible()
    expect(page.get_by_text(re.compile(r"· 1 edited"))).to_be_visible()
    expect(page.get_by_role("heading", name="Row 7")).to_be_visible()  # the same row stays chosen
    page.get_by_role("tab", name="History").click()
    expect(page.get_by_text("typo in source")).to_be_visible()


def test_a_reviewer_excludes_a_row_chosen_by_its_number_with_a_reason(page, stack, upload):
    _open_review(page, stack, "reviewer", upload)
    _type_row_number(page, 14)  # amount "x"
    page.get_by_role("tab", name="Exclude row").click()

    page.get_by_label("Reason to exclude this row (required)").fill("duplicate")
    page.get_by_role("button", name="Exclude this row").click()

    expect(page.get_by_text("Saved: row 14 excluded.")).to_be_visible()
    # "0 excluded" also matches \d+, so wait for a non-zero count: the exclusion has been applied.
    expect(page.get_by_text(re.compile(r"· [1-9]\d* excluded"))).to_be_visible()
    expect(page.get_by_text("Decision: exclude: duplicate")).to_be_visible()
    expect(page.get_by_role("tab", name="Include row")).to_be_visible()  # the next decision is to include it


def test_signing_out_leaves_nothing_for_the_next_tenant(page, stack, upload):
    _open_review(page, stack, "admin", upload)
    page.locator('[data-testid="stSidebar"]').get_by_role("button", name="Sign out").click()
    page.get_by_role("heading", name="Sign in").wait_for()

    _open_review(page, stack, "other")  # a different tenant, with no uploads

    expect(page.get_by_text("No uploads yet.")).to_be_visible()
    expect(page.get_by_text(upload, exact=False)).to_have_count(0)


# ── new with this screen ────────────────────────────────────────────────────────────────────────────

def test_the_grid_and_the_row_number_box_stay_in_step(page, stack, upload):
    _open_review(page, stack, "reviewer", upload)
    box = _row_number_box(page)
    expect(box).to_have_value("")
    expect(page.get_by_text("Select a row in the table, or type its number")).to_be_visible()

    _select_row(page, 2)
    expect(box).to_have_value("3")  # a click on the grid moves the box

    _type_row_number(page, 5)  # typing a number moves the detail
    expect(page.get_by_role("heading", name="Row 3")).to_have_count(0)

    _select_row(page, 0)  # and the grid still works after typing
    expect(box).to_have_value("1")


def test_a_row_chosen_on_one_page_does_not_break_the_next(page, stack):
    name = _unique("long")
    res = stack.upload("admin", name, "id,name\n" + "".join(f"{i},p{i}\n" for i in range(1, 251)),
                       types=["int8", "text"])
    assert res["status"] == "ok", res
    _open_review(page, stack, "admin", name)
    expect(page.get_by_label("Page (of 3)")).to_be_visible()
    _type_row_number(page, 5)

    pager = page.get_by_label("Page (of 3)")
    pager.fill("2")
    pager.press("Enter")

    expect(page.get_by_text("100 to 200", exact=False).or_(page.get_by_placeholder("101 to 200"))).to_be_visible()
    expect(page.get_by_role("heading", name="Row 5")).to_have_count(0)
    expect(page.get_by_text("Something went wrong")).to_have_count(0)
    _type_row_number(page, 150)
    expect(page.get_by_role("heading", name="Row 150")).to_be_visible()


def test_the_list_offers_every_attempt_and_can_be_cut_to_the_failed_and_partial_ones(page, stack, upload):
    clean = _unique("clean")
    assert stack.upload("admin", clean, f"id,name\n1,{clean}\n2,b\n", types=["int8", "text"])["status"] == "ok"  # (identical bytes are a duplicate)
    _open_review(page, stack, "admin")

    # The tenant's other tests upload files too, so the list is long: type to narrow it, as a person would.
    def offered(fragment: str, option: "re.Pattern | str"):
        box = page.get_by_role("combobox", name="Upload")
        box.click()
        box.fill(fragment)
        return page.get_by_role("option", name=option)

    expect(offered(clean[:14], re.compile(re.escape(clean) + " · Imported"))).to_be_visible()
    expect(offered(upload[:14], re.compile(re.escape(upload) + r" · Partly imported · 4 of 30 rows failed"))).to_be_visible()
    page.keyboard.press("Escape")

    page.get_by_text("Only failed or partly failed uploads").click()
    idle_ = page.locator('[data-testid="stStatusWidget"]')
    expect(idle_).to_have_count(0)
    expect(offered(upload[:14], re.compile(re.escape(upload)))).to_be_visible()
    expect(offered(clean[:14], re.compile(re.escape(clean)))).to_have_count(0)


def test_a_cell_that_looks_like_a_link_is_shown_as_text_and_is_not_a_link(page, stack):
    name = _unique("sneaky")
    link = "[click here](https://evil.example/login)"
    res = stack.upload("admin", name, f"id,name,amount\n1,a,{link}\n2,b,5\n", types=["int8", "text", "int8"])
    assert res["status"] == "ok" and res["failedRows"] == 1, res
    _open_review(page, stack, "admin", name)

    _type_row_number(page, 1)

    expect(page.get_by_text(f'"{link}" is not a whole number', exact=False)).to_be_visible()
    assert page.locator('a[href*="evil.example"]').count() == 0, "a cell must not become a link"
    expect(page.get_by_role("link", name="click here")).to_have_count(0)


def test_a_session_the_server_ended_sends_the_next_save_back_to_sign_in(page, stack, upload):
    a = stack.accounts["reviewer"]
    _open_review(page, stack, "reviewer", upload)
    _type_row_number(page, 28)
    page.get_by_role("tab", name="Exclude row").click()

    with Conn() as conn, conn.cursor() as cur:  # as the API does when a password is reset: revoke the user's sessions
        cur.execute(sql.SQL("UPDATE {c}.sessions SET revoked_at = now() WHERE user_id = "
                            "(SELECT id FROM {c}.users WHERE username = %s)").format(
                                c=sql.Identifier(settings.CONTROL_SCHEMA)), (a.username,))
        conn.commit()
    page.get_by_label("Reason to exclude this row (required)").fill("too late")
    page.get_by_role("button", name="Exclude this row").click()

    expect(page.get_by_text("Your session has ended. Sign in again.")).to_be_visible()
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    shell_sign_in(page, stack, "reviewer", PASSWORD)  # the person can sign straight back in
    page.get_by_role("button", name="Sign out").wait_for()
