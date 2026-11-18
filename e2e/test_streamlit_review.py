"""The Streamlit review screen (#252) in a real browser, against the real API, inside the app shell."""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from conftest import shell_sign_in

ROWS = "".join(f"{i},person{i},{'x' if i % 7 == 0 else i * 10}\n" for i in range(1, 31))


@pytest.fixture(scope="module")
def upload(stack):
    name = f"people_{uuid.uuid4().hex[:6]}.csv"
    res = stack.upload("admin", name, "id,name,amount\n" + ROWS, types=["int8", "text", "int8"])
    assert res["status"] == "ok" and res["failedRows"] == 4, res
    return name


def _open_review(page, stack, who: str) -> None:
    shell_sign_in(page, stack, who)
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Review").click()
    page.get_by_role("heading", name="Review", exact=True).wait_for()


def _pick_row(page, number: int) -> None:
    """Pick a row through the "Row number" input (the grid itself is a canvas, so clicks would be coordinates)."""
    box = page.get_by_label("Row number")
    box.fill(str(number))
    box.press("Enter")
    page.get_by_role("heading", name=f"Row {number}").wait_for()


def _form(page, button: str):
    """The inline form holding this submit button (the exclude and edit forms both have a "Reason (required)")."""
    return page.locator('[data-testid="stForm"]').filter(has=page.get_by_role("button", name=button, exact=True))


def _submit(page, button: str, reason: str) -> None:
    form = _form(page, button)
    form.get_by_label("Reason (required)").fill(reason)
    form.get_by_label("Reason (required)").press("Tab")
    form.get_by_role("button", name=button, exact=True).click()


def test_an_uploader_can_look_but_not_change(page, stack, upload):
    _open_review(page, stack, "uploader")
    expect(page.get_by_text(upload, exact=False).first).to_be_visible()
    _pick_row(page, 7)  # row 7: amount "x"
    expect(page.get_by_text(re.compile(r'amount: .*is not a whole number'))).to_be_visible()
    expect(page.get_by_role("button", name="History")).to_be_visible()
    expect(page.get_by_role("button", name="Save edit")).to_have_count(0)
    expect(page.get_by_role("button", name="Exclude", exact=True)).to_have_count(0)
    expect(page.get_by_text("read-only for your role")).to_be_visible()


def test_a_reviewer_edits_with_a_required_reason_and_it_shows_in_the_history(page, stack, upload):
    _open_review(page, stack, "reviewer")
    _pick_row(page, 7)
    form = _form(page, "Save edit")
    page.get_by_role("button", name="Save edit").click()  # no reason yet
    expect(page.get_by_text("Give a reason.")).to_be_visible()
    form.get_by_label("Column").click()
    page.get_by_role("option", name="amount").click()
    form.get_by_label("New value").fill("70")
    _submit(page, "Save edit", "typo in source")
    expect(page.get_by_text(re.compile(r"1 edited"))).to_be_visible()
    _pick_row(page, 7)
    page.get_by_role("button", name="History").click()
    expect(page.get_by_text("typo in source")).to_be_visible()


def test_a_reviewer_excludes_a_row_with_a_reason(page, stack, upload):
    _open_review(page, stack, "reviewer")
    _pick_row(page, 14)  # row 14: amount "x"
    _submit(page, "Exclude", "duplicate")
    # "0 excluded" also matches \d+, so wait for a non-zero count: the exclusion has been applied.
    expect(page.get_by_text(re.compile(r"\b[1-9]\d* excluded"))).to_be_visible()
    _pick_row(page, 14)
    expect(page.get_by_text(re.compile("Decision: exclude"))).to_be_visible()


def test_signing_out_leaves_nothing_for_the_next_tenant(page, stack, upload):
    _open_review(page, stack, "admin")
    expect(page.get_by_text(upload, exact=False).first).to_be_visible()
    page.locator('[data-testid="stSidebar"]').get_by_role("button", name="Sign out").click()

    _open_review(page, stack, "other")  # a different tenant, with no uploads
    expect(page.get_by_text("No uploads yet.")).to_be_visible()
    expect(page.get_by_text(upload, exact=False)).to_have_count(0)
