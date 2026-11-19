"""The Streamlit import-history screen (#253) in a real browser, against the real API.

What the headless tests (tests/unit/test_streamlit_history.py) cannot show: the history coming from the server and
not the browser (another browser sees it; the browser's storage holds none of it), the filters and the pickers in a
real page, the report files a browser actually saves (opened here the way a spreadsheet program would), and how a
cell from a file is drawn. The file with formula payloads is the one to open in Excel for #244.
"""

from __future__ import annotations

import csv
import io
import re
import uuid

import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect

from conftest import shell_sign_in
from streamlit_helpers import choose_option, click_and_download, idle, open_page

PAYLOADS = ["=1+1", "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1:A2)"]
# 30 rows; every seventh amount is a formula payload, which fails the int8 type: rows 7, 14, 21 and 28.
ROWS = "".join(f"{i},person{i},{PAYLOADS[i // 7 - 1] if i % 7 == 0 else i * 10}\n" for i in range(1, 31))


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}.csv"


@pytest.fixture(scope="module")
def failing(stack):
    """A partly imported upload whose four failed rows hold formula payloads, made by the uploader."""
    name = _unique("payloads")
    res = stack.upload("uploader", name, "id,name,amount\n" + ROWS, types=["int8", "text", "int8"])
    assert res["status"] == "ok" and res["failedRows"] == 4, res
    return name


def _cells(page) -> str:
    return page.locator('[data-testid="stTable"]').first.inner_text()


# ── the history is the tenant's, not the browser's ─────────────────────────────────────────────

def test_an_upload_by_one_person_is_in_the_history_of_another_in_a_fresh_browser(page, stack, failing):
    open_page(page, stack, "reviewer", "Import history", "Import history")

    expect(page.get_by_role("cell", name=failing)).to_be_visible()
    expect(page.get_by_role("cell", name="Partly imported").first).to_be_visible()
    expect(page.get_by_role("cell", name=stack.accounts["uploader"].username).first).to_be_visible()  # who uploaded it


def test_nothing_of_the_history_is_kept_in_the_browser(page, stack, failing):
    open_page(page, stack, "reviewer", "Import history", "Import history")
    expect(page.get_by_role("cell", name=failing)).to_be_visible()

    stored = page.evaluate("() => document.cookie + JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")

    assert failing not in stored and "payloads" not in stored, "the file name was written to the browser's storage"


def test_another_tenants_history_is_empty_and_shows_none_of_this_ones(page, stack, failing):
    open_page(page, stack, "other", "Import history", "Import history")

    expect(page.get_by_text("No imports yet.")).to_be_visible()
    expect(page.get_by_text(failing, exact=False)).to_have_count(0)


# ── filters ────────────────────────────────────────────────────────────────────────────────────

def test_the_file_name_and_status_filters_narrow_the_list(page, stack, failing):
    clean = _unique("clean")
    assert stack.upload("uploader", clean, f"id,name\n1,{clean}\n2,b\n", types=["int8", "text"])["status"] == "ok"  # (identical bytes are a duplicate)
    open_page(page, stack, "reviewer", "Import history", "Import history")
    expect(page.get_by_role("cell", name=clean)).to_be_visible()
    expect(page.get_by_role("cell", name=failing)).to_be_visible()

    choose_option(page, "Status", "Partly imported")
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_role("cell", name=failing)).to_be_visible()
    expect(page.get_by_role("cell", name=clean)).to_have_count(0)

    choose_option(page, "Status", "All statuses")
    page.get_by_label("File name contains").fill(clean[:12].upper())  # case does not matter
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_role("cell", name=clean)).to_be_visible()
    expect(page.get_by_role("cell", name=failing)).to_have_count(0)

    page.get_by_label("File name contains").fill("no such file")
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_text("No imports match the filters.")).to_be_visible()


# ── one import: why rows failed, and the reports ───────────────────────────────────────────────

def _open_import(page, stack, failing, who="reviewer"):
    open_page(page, stack, who, "Import history", "Import history")
    choose_option(page, "Details of an import", re.compile(re.escape(failing)))
    expect(page.get_by_role("heading", name=failing)).to_be_visible()
    idle(page)


def test_choosing_an_import_lists_the_reasons_the_server_kept(page, stack, failing):
    _open_import(page, stack, failing)

    expect(page.get_by_text("Rows that failed")).to_be_visible()
    for payload in PAYLOADS:
        expect(page.get_by_role("cell", name=f'"{payload}" is not a whole number')).to_be_visible()
    page.get_by_text("What the server did, step by step").click()  # the step log is in an expander
    expect(page.get_by_role("cell", name="cast_rows")).to_be_visible()


def test_the_csv_error_report_is_the_four_failed_rows_with_the_payloads_neutralised(page, stack, failing):
    _open_import(page, stack, failing)

    data = click_and_download(page, page.get_by_role("button", name="Error report (CSV)"))

    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    assert rows[0] == ["file", "row_number", "column", "value", "reason", "plain_english", "header_mapping"]
    assert [r[1] for r in rows[1:]] == ["7", "14", "21", "28"]
    assert [r[3] for r in rows[1:]] == ["'" + p for p in PAYLOADS], "each payload starts with a quote, so none runs"
    assert all(r[0] == failing for r in rows[1:])


def test_the_xlsx_error_report_holds_the_payloads_as_text_that_no_program_runs(page, stack, failing):
    _open_import(page, stack, failing)

    data = click_and_download(page, page.get_by_role("button", name="Error report (XLSX)"))

    sheet = load_workbook(io.BytesIO(data))["Errors"]
    cells = [sheet[f"D{r}"] for r in range(2, 6)]
    assert [c.value for c in cells] == ["'" + p for p in PAYLOADS]
    assert {c.data_type for c in cells} == {"s"}, "text cells, not formulas"
    assert [sheet[f"B{r}"].value for r in range(2, 6)] == [7, 14, 21, 28]


def test_the_download_is_named_for_the_file(page, stack, failing):
    _open_import(page, stack, failing)

    with page.expect_download() as taken:
        page.get_by_role("button", name="Error report (CSV)").click()

    stem = re.sub(r"\.csv$", "", failing)
    assert re.fullmatch(rf"errors-{re.escape(stem)}-\d{{4}}-\d\d-\d\dT\d\d-\d\d-\d\dZ\.csv", taken.value.suggested_filename)


# ── a report of the whole filtered list ────────────────────────────────────────────────────────

def test_a_report_of_every_matching_import_downloads_as_csv_and_xlsx(page, stack, failing):
    open_page(page, stack, "reviewer", "Import history", "Import history")
    page.get_by_label("File name contains").fill(failing[:12])
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_role("cell", name=failing)).to_be_visible()

    page.get_by_role("button", name="Prepare a report of all matching imports").click()
    expect(page.get_by_text(re.compile(r"Report of \d+ imports?\."))).to_be_visible()
    as_csv = click_and_download(page, page.get_by_role("button", name="Download CSV"))
    as_xlsx = click_and_download(page, page.get_by_role("button", name="Download XLSX"))

    rows = list(csv.reader(io.StringIO(as_csv.decode("utf-8"))))
    assert rows[0][:3] == ["file", "status", "uploaded_at"]
    mine = [r for r in rows[1:] if r[0] == failing]
    assert len(mine) == 1 and mine[0][1] == "partly_imported" and mine[0][3] == stack.accounts["uploader"].username
    assert mine[0][8] == "4", "failed_rows"
    sheet = load_workbook(io.BytesIO(as_xlsx))["History"]
    assert [c.value for c in sheet[1]][:3] == ["file", "status", "uploaded_at"]
    assert any(sheet.cell(row=r, column=1).value == failing for r in range(2, sheet.max_row + 1))


# ── text from a file is shown as written ───────────────────────────────────────────────────────

def test_a_file_name_and_a_cell_that_look_like_links_are_text_not_links(page, stack):
    name = f"**bold**_{uuid.uuid4().hex[:6]}.csv"
    link = "[click here](https://evil.example/login)"
    res = stack.upload("uploader", name, f"id,amount\n1,{link}\n2,5\n", types=["int8", "int8"])
    assert res["status"] == "ok" and res["failedRows"] == 1, res
    open_page(page, stack, "reviewer", "Import history", "Import history")
    choose_option(page, "Details of an import", re.compile(re.escape(name)))
    expect(page.get_by_role("heading", name=name)).to_be_visible()
    idle(page)

    expect(page.get_by_role("cell", name=link, exact=False).first).to_be_visible()
    assert page.locator('a[href*="evil.example"]').count() == 0, "a cell must not become a link"
    assert page.locator('[data-testid="stTable"] strong, [data-testid="stHeading"] strong').count() == 0, \
        "a file name must not become bold"


# ── the server's audit events ──────────────────────────────────────────────────────────────────

def test_roles_that_may_not_read_the_audit_log_are_not_offered_it(page, stack, failing):
    open_page(page, stack, "reviewer", "Import history", "Import history")

    expect(page.get_by_text("Server audit events")).to_have_count(0)


def test_an_admin_sees_the_servers_events_filters_them_and_downloads_the_servers_csv(page, stack, failing):
    open_page(page, stack, "admin", "Import history", "Import history")
    page.get_by_text("Server audit events").click()
    expect(page.get_by_text(re.compile(r"\d+ events? · OFFICIAL"))).to_be_visible()
    expect(page.get_by_role("cell", name="upload", exact=True).first).to_be_visible()
    expect(page.get_by_role("cell", name=failing).first).to_be_visible()

    page.get_by_label("File").fill(failing[:12])
    choose_option(page, "Action", "upload")
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_text(re.compile(r"1 event · OFFICIAL"))).to_be_visible()

    page.get_by_role("button", name="Prepare a CSV of all matching events").click()
    data = click_and_download(page, page.get_by_role("button", name="Download CSV"))

    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    assert "action" in rows[0] and len(rows) == 2 and failing in rows[1]


def test_signing_out_leaves_no_history_for_the_next_person(page, stack, failing):
    open_page(page, stack, "reviewer", "Import history", "Import history")
    expect(page.get_by_role("cell", name=failing)).to_be_visible()
    page.locator('[data-testid="stSidebar"]').get_by_role("button", name="Sign out").click()
    page.get_by_role("heading", name="Sign in").wait_for()

    shell_sign_in(page, stack, "other")
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Import history").click()

    expect(page.get_by_text("No imports yet.")).to_be_visible()
    expect(page.get_by_text(failing, exact=False)).to_have_count(0)
