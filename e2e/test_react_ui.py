"""React app in a real browser: #187, #188 and the live #176 leak."""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from conftest import react_sign_in

CSV = b"id,name\n1,a\n2,b\n"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _choose_file(page, name: str, content: bytes = CSV) -> None:
    page.set_input_files('input[type="file"]', {"name": name, "mimeType": "text/csv", "buffer": content})
    page.get_by_role("button", name=re.compile("confirm & import", re.I)).click()


def test_187_a_failed_upload_is_reachable_and_opens_its_row_errors(page, stack):
    name = f"failed_{_tag()}.csv"
    res = stack.upload("admin", name, "n\nx\ny\n", types=["int8"])  # every row fails the type check
    assert res["status"] == "error" and res["uploadId"], res

    react_sign_in(page, stack, "admin")
    row = page.get_by_role("listitem").filter(has_text=name)
    expect(row).to_be_visible()
    expect(row.get_by_text("Failed", exact=True)).to_be_visible()
    row.get_by_role("link", name="Review").click()

    expect(page).to_have_url(re.compile(r"/review/\d+$"))
    expect(page.get_by_text("Invalid").first).to_be_visible()  # the stored rows and their validation errors


def test_187_clean_imports_are_hidden_until_the_filter_is_turned_off(page, stack):
    clean, partial = f"clean_{_tag()}.csv", f"partial_{_tag()}.csv"
    stack.upload("admin", clean, "n\n1\n2\n", types=["int8"])
    stack.upload("admin", partial, "n\n1\nx\n", types=["int8"])

    react_sign_in(page, stack, "admin")
    partial_row = page.get_by_role("listitem").filter(has_text=partial)  # not the migrated-files table below
    expect(partial_row).to_be_visible()
    expect(partial_row.get_by_text("Partly imported")).to_be_visible()
    expect(page.get_by_role("listitem").filter(has_text=clean)).to_have_count(0)
    page.get_by_label("Only failed or partial").uncheck()
    expect(page.get_by_role("listitem").filter(has_text=clean)).to_be_visible()


def test_188_stop_is_not_offered_once_the_request_is_on_the_server(page, stack):
    react_sign_in(page, stack, "admin")
    held = []
    page.route("**/api/csv/upload", lambda route: held.append(route))  # the request stays pending until released

    _choose_file(page, f"slow_{_tag()}.csv")

    expect(page.get_by_text(re.compile("sent to the server", re.I))).to_be_visible()
    expect(page.get_by_role("button", name="Stop")).to_have_count(0)

    held[0].continue_()
    expect(page.get_by_text("Imported", exact=True)).to_be_visible()
    expect(page.get_by_text("Cancelled", exact=True)).to_have_count(0)


@pytest.mark.xfail(strict=True, reason=(
    "#176 is live: upload history is kept under one global localStorage key, so a second tenant on the same "
    "browser sees the first one's file names. Closed as moot (the React screen is being replaced, #212), "
    "but the app still ships. This test turns red when the leak is fixed: then drop the marker."))
def test_176_the_next_tenant_does_not_see_the_previous_tenants_history(page, stack):
    name = f"acme_private_{_tag()}.csv"
    react_sign_in(page, stack, "admin")
    _choose_file(page, name)
    expect(page.get_by_text("Imported", exact=True)).to_be_visible()

    # Control: the history screen does list this tenant's own import, so "not listed" below means something.
    page.goto(f"{stack.web}/audit")
    expect(page.get_by_text(name)).to_be_visible()
    expect(page.get_by_text("1 import · saved locally")).to_be_visible()

    page.goto(stack.web)
    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url(re.compile("/auth"))
    react_sign_in(page, stack, "other")
    page.goto(f"{stack.web}/audit")
    page.get_by_role("heading", name="Import history").wait_for()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)  # a negative check needs the page to have loaded its stored history
    expect(page.get_by_text(name)).to_have_count(0)
    expect(page.get_by_text("0 imports · saved locally")).to_be_visible()
