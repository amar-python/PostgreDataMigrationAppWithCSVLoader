"""The Streamlit review screen from the #154 spike, in a real browser."""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from conftest import streamlit_sign_in

ROWS = "".join(f"{i},person{i},{'x' if i % 7 == 0 else i * 10}\n" for i in range(1, 31))


@pytest.fixture(scope="module")
def upload(stack):
    name = f"people_{uuid.uuid4().hex[:6]}.csv"
    res = stack.upload("admin", name, "id,name,amount\n" + ROWS, types=["int8", "text", "int8"])
    assert res["status"] == "ok" and res["failedRows"] == 4, res
    return name


def _select_row(page, index: int) -> None:
    """st.dataframe draws on a canvas: click the selection checkbox of the row at `index`.

    Streamlit re-runs the script after every action and redraws the grid, so a click can land
    before it is ready: try again if the row's detail panel doesn't appear.
    """
    grid = page.locator('[data-testid="stDataFrame"]').first
    heading = page.get_by_role("heading", name=f"Row {index + 1}")
    for attempt in range(3):
        grid.wait_for()
        box = grid.bounding_box()
        page.mouse.click(box["x"] + 15, box["y"] + 35 + 35 * index + 17)
        try:
            heading.wait_for(timeout=5000)
            return
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise


def test_an_uploader_can_look_but_not_change(page, stack, upload):
    streamlit_sign_in(page, stack, "uploader")
    expect(page.get_by_text(upload, exact=False).first).to_be_visible()
    _select_row(page, 6)  # row 7: amount "x"
    expect(page.get_by_text(re.compile(r'amount: "x" is not a whole number'))).to_be_visible()
    expect(page.get_by_role("button", name="History")).to_be_visible()
    expect(page.get_by_role("button", name="Edit a cell")).to_have_count(0)
    expect(page.get_by_role("button", name="Exclude")).to_have_count(0)
    expect(page.get_by_text("read-only for your role")).to_be_visible()


def test_a_reviewer_edits_with_a_required_reason_and_it_shows_in_the_history(page, stack, upload):
    streamlit_sign_in(page, stack, "reviewer")
    _select_row(page, 6)
    page.get_by_role("button", name="Edit a cell").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("combobox").click()
    page.get_by_role("option", name="amount").click()
    # Choosing a column re-runs the script and rebuilds the field: wait for it, as a person would.
    expect(dialog.get_by_text(re.compile(r"Original:\s*x\b"))).to_be_visible()
    dialog.get_by_label("New value").fill("70")
    dialog.get_by_label("New value").press("Tab")
    save = dialog.get_by_role("button", name="Save")
    expect(save).to_be_disabled()  # no reason yet
    dialog.get_by_label("Reason (required)").fill("typo in source")
    dialog.get_by_label("Reason (required)").press("Tab")
    expect(save).to_be_enabled()
    save.click()

    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_text(re.compile(r"1 edited"))).to_be_visible()
    _select_row(page, 6)
    page.get_by_role("button", name="History").click()
    expect(page.get_by_role("dialog").get_by_text("typo in source")).to_be_visible()


def test_a_reviewer_excludes_a_row_with_a_reason(page, stack, upload):
    streamlit_sign_in(page, stack, "reviewer")
    _select_row(page, 13)  # row 14: amount "x"
    page.get_by_role("button", name="Exclude").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Reason (required)").fill("duplicate")
    dialog.get_by_label("Reason (required)").press("Tab")
    dialog.get_by_role("button", name="Save").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    # "0 excluded" also matches \d+, so wait for a non-zero count: the exclusion has been applied.
    expect(page.get_by_text(re.compile(r"\b[1-9]\d* excluded"))).to_be_visible()
    _select_row(page, 13)
    expect(page.get_by_text(re.compile("Decision: exclude"))).to_be_visible()


def test_signing_out_leaves_nothing_for_the_next_tenant(page, stack, upload):
    streamlit_sign_in(page, stack, "admin")
    expect(page.get_by_text(upload, exact=False).first).to_be_visible()
    page.locator('[data-testid="stSidebar"]').get_by_role("button", name="Sign out").click()

    streamlit_sign_in(page, stack, "other")  # a different tenant, with no uploads
    expect(page.get_by_text("No uploads yet.")).to_be_visible()
    expect(page.get_by_text(upload, exact=False)).to_have_count(0)
