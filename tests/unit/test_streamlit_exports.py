"""The Streamlit app's reports (streamlit_app/exports.py): CSV and XLSX with the formula-injection guard (#193).

Ported from the React app's csv-table-hub-main/src/__tests__/export.test.ts, case for case where there is one,
and checked by reading the files back the way a spreadsheet program would. The guard is the point: every cell
holds text from someone else's file, so a cell that would run as a formula must not.
"""
import csv
import io
from datetime import datetime, timezone

import pytest
from openpyxl import load_workbook

from tests.unit import streamlit_harness  # noqa: F401  (puts streamlit_app on the path)

import exports as x  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

PAYLOADS = ['=HYPERLINK("http://x","y")', "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1:A2)", "\tcmd", "\r=cmd", "=1+1"]


def _csv_rows(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def _sheet(data: bytes, name: str):
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == [name]
    return wb[name]


def _errors(value, **extra):
    return x.error_rows("d.csv", [{"rowNumber": 1, "column": "c", "value": value, "reason": "bad", **extra}])


# ── the guard ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", PAYLOADS)
def test_a_cell_that_would_run_as_a_formula_gets_a_leading_quote(value):
    assert x.guard(value) == "'" + value


@pytest.mark.parametrize("value", ["-5", "+3.2", "5", "1.5", "-0", "+0.25", "plain text", "a=b", "x-y", "", "email@x.test"])
def test_plain_numbers_and_ordinary_text_are_left_alone(value):
    assert x.guard(value) == value


@pytest.mark.parametrize("value", [5, 2.5, None, True])
def test_a_value_that_is_not_text_is_left_alone(value):
    assert x.guard(value) == value


def test_the_guard_looks_past_characters_nobody_can_see():
    """A program may skip a leading control character and then read a formula: the guard must not be fooled."""
    assert x.guard("\x01=cmd") == "'\x01=cmd"
    assert x.guard("\x1f@SUM(A1)") == "'\x1f@SUM(A1)"
    assert x.guard("\x01-5") == "\x01-5", "a number behind a control character is still a number"


# ── CSV ───────────────────────────────────────────────────────────────────────────────────

def test_the_csv_has_the_header_row_and_a_line_feed_after_every_line():
    data = x.to_csv(x.ERROR_HEADERS, _errors("v"))

    lines = data.decode().split("\n")
    assert lines[0] == "file,row_number,column,value,reason,plain_english,header_mapping"
    assert lines[1] == "d.csv,1,c,v,bad,bad,"
    assert data.endswith(b"\n") and b"\r" not in data


def test_commas_quotes_and_line_breaks_in_a_value_are_quoted():
    data = x.to_csv(x.ERROR_HEADERS, _errors('say "hello", world\nbye'))

    assert '"say ""hello"", world\nbye"' in data.decode()
    assert _csv_rows(data)[1][3] == 'say "hello", world\nbye', "and read back as written"


@pytest.mark.parametrize("value, expected", [
    ('=HYPERLINK("http://x","y")', '\'=HYPERLINK(""http://x"",""y"")'),
    ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
    ("-2+3", "'-2+3"),
    ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
])
def test_a_formula_payload_is_neutralised_in_the_csv(value, expected):
    data = x.to_csv(x.ERROR_HEADERS, _errors(value))

    assert expected in data.decode()
    assert _csv_rows(data)[1][3] == "'" + value
    assert not any(cell.lstrip("\x00-\x08\x0b\x0c\x0e-\x1f").startswith(("=", "+", "-", "@"))
                   for row in _csv_rows(data)[1:] for cell in row if cell not in ("-5",)), "no cell starts as a formula"


def test_signed_numbers_stay_numbers_in_the_csv():
    data = x.to_csv(x.ERROR_HEADERS, x.error_rows("d.csv", [{"rowNumber": 1, "column": "n", "value": "-5", "reason": "+3.2"}]))

    assert ",-5," in data.decode() and ",+3.2," in data.decode()


def test_a_formula_like_file_name_is_guarded_too():
    data = x.to_csv(x.HISTORY_HEADERS, x.history_rows([_upload(file_name="=cmd")]))

    assert _csv_rows(data)[1][0] == "'=cmd"


def test_non_ascii_text_survives_as_utf8():
    data = x.to_csv(x.ERROR_HEADERS, _errors("café – 日本語"))

    assert _csv_rows(data)[1][3] == "café – 日本語"


def test_an_empty_report_is_just_the_header():
    assert x.to_csv(["a", "b"], []) == b"a,b\n"


# ── XLSX ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", PAYLOADS)
def test_a_formula_payload_is_a_text_cell_with_no_formula_in_the_xlsx(value):
    ws = _sheet(x.to_xlsx("Errors", x.ERROR_HEADERS, _errors(value)), "Errors")

    cell = ws["D2"]  # ERROR_HEADERS: file, row_number, column, value, ...
    assert cell.data_type == "s", "a text cell, not a formula"
    # Whether a carriage return survives the XML round trip depends on the parser (lxml or not), so compare modulo \r.
    assert cell.value.replace("\r", "\n") == ("'" + value).replace("\r", "\n")


def test_even_with_the_guard_gone_text_that_starts_with_an_equals_sign_is_stored_as_text(monkeypatch):
    """The second layer. openpyxl reads a string that starts with = as a formula; the cell is told it is text."""
    monkeypatch.setattr(x, "guard", lambda value: value)

    data = x.to_xlsx("S", ["a"], [{"a": "=1+1"}])

    cell = _sheet(data, "S")["A2"]
    assert (cell.data_type, cell.value) == ("s", "=1+1")
    import zipfile
    sheet_xml = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet_xml and "<f " not in sheet_xml, "no formula element in the workbook"


def test_signed_numbers_are_left_alone_in_the_xlsx():
    ws = _sheet(x.to_xlsx("Errors", x.ERROR_HEADERS, x.error_rows(
        "d.csv", [{"rowNumber": 1, "column": "n", "value": "-5", "reason": "+3.2"}])), "Errors")

    assert (ws["D2"].value, ws["E2"].value) == ("-5", "+3.2")
    assert ws["B2"].value == 1, "the row number is a number"


def test_the_headers_are_the_first_row_and_the_sheet_is_named():
    ws = _sheet(x.to_xlsx("Errors", x.ERROR_HEADERS, _errors("v")), "Errors")

    assert [c.value for c in ws[1]] == x.ERROR_HEADERS


def test_a_formula_like_file_name_is_guarded_in_the_history_xlsx():
    ws = _sheet(x.to_xlsx("History", x.HISTORY_HEADERS, x.history_rows([_upload(file_name="=cmd")])), "History")

    assert (ws["A2"].data_type, ws["A2"].value) == ("s", "'=cmd")


def test_a_control_character_in_a_cell_does_not_break_the_workbook():
    """XLSX cannot hold most control characters: openpyxl raises on one. A bad value in someone's file must
    not stop the report that says it is bad."""
    ws = _sheet(x.to_xlsx("Errors", x.ERROR_HEADERS, _errors("a\x01b\x00c")), "Errors")

    assert ws["D2"].value == "a�b�c"


def test_a_control_character_in_front_of_a_formula_is_guarded_and_still_saves():
    ws = _sheet(x.to_xlsx("Errors", x.ERROR_HEADERS, _errors("\x01=cmd")), "Errors")

    assert ws["D2"].value == "'�=cmd" and ws["D2"].data_type == "s"


def test_a_value_longer_than_excel_keeps_is_cut_rather_than_corrupting_the_file():
    ws = _sheet(x.to_xlsx("Errors", x.ERROR_HEADERS, _errors("x" * 40_000)), "Errors")

    assert len(ws["D2"].value) == x.XLSX_CELL_LIMIT and ws["D2"].value.endswith("…")


def test_a_sheet_name_is_cut_to_the_31_characters_excel_allows():
    data = x.to_xlsx("A" * 50, ["a"], [])

    assert load_workbook(io.BytesIO(data)).sheetnames == ["A" * 31]


def test_a_blank_value_is_an_empty_cell_and_a_number_stays_a_number():
    ws = _sheet(x.to_xlsx("S", ["a", "b"], [{"a": None, "b": 7}]), "S")

    assert ws["A2"].value in (None, "") and ws["B2"].value == 7


# ── what goes in a report ─────────────────────────────────────────────────────────────────

def test_mapping_summary_says_what_was_renamed():
    assert x.mapping_summary(None) == "" and x.mapping_summary([]) == ""
    assert x.mapping_summary([{"original": "a", "renamed": ""}, {"original": "b", "renamed": "b"}]) == "(no renames)"
    assert x.mapping_summary([{"original": "a", "renamed": "x"}, {"original": "b", "renamed": ""},
                              {"original": "c", "renamed": "z"}]) == "a→x, c→z"


def test_one_report_row_per_row_error_with_the_file_name_and_mapping():
    rows = x.error_rows("data.csv", [
        {"rowNumber": 3, "column": "age", "value": "x", "reason": "not a whole number"},
        {"rowNumber": 9, "reason": "too few cells"},
    ], mapping=[{"original": "a", "renamed": "b"}])

    assert [r["file"] for r in rows] == ["data.csv", "data.csv"]
    assert rows[0] == {"file": "data.csv", "row_number": 3, "column": "age", "value": "x",
                       "reason": "not a whole number", "plain_english": "not a whole number", "header_mapping": "a→b"}
    assert (rows[1]["column"], rows[1]["value"]) == ("", ""), "a missing column or value is blank, not None"


def test_an_import_that_failed_as_a_whole_gets_one_row_for_its_message():
    rows = x.error_rows("data.csv", [], message="The file has no data rows")

    assert len(rows) == 1 and rows[0]["row_number"] == 0 and rows[0]["reason"] == "The file has no data rows"


def test_row_errors_win_over_the_message_and_no_errors_no_message_is_no_rows():
    assert [r["row_number"] for r in x.error_rows("d.csv", [{"rowNumber": 2, "reason": "r"}], message="m")] == [2]
    assert x.error_rows("d.csv", []) == []


def _upload(**extra):
    return {"id": "7", "file_name": "people.csv", "status": "partly_imported", "uploaded_at": "2026-11-18T01:00:00+00:00",
            "uploader": "alice", "mode": "dynamic", "state": "imported", "total_rows": 30, "imported_rows": 26,
            "failed_rows": 4, "failure_reason": "4 rows failed", **extra}


def test_the_history_report_has_a_row_per_import_with_blanks_for_what_the_server_did_not_say():
    rows = x.history_rows([_upload(), _upload(id="8", uploader=None, failure_reason=None, state=None, total_rows=None)])

    assert rows[0] == {"file": "people.csv", "status": "partly_imported", "uploaded_at": "2026-11-18T01:00:00+00:00",
                       "uploader": "alice", "mode": "dynamic", "state": "imported", "total_rows": 30,
                       "imported_rows": 26, "failed_rows": 4, "reason": "4 rows failed", "upload_id": "7"}
    assert (rows[1]["uploader"], rows[1]["reason"], rows[1]["state"], rows[1]["total_rows"]) == ("", "", "", None)
    assert list(rows[0]) == x.HISTORY_HEADERS


def test_a_report_is_named_with_a_safe_stem_and_a_utc_time_stamp():
    at = datetime(2026, 11, 18, 9, 30, 5, tzinfo=timezone.utc)

    assert x.report_name("errors", "csv", "My people (v2).CSV", now=at) == "errors-My_people_v2_-2026-11-18T09-30-05Z.csv"
    assert x.report_name("history", "xlsx", now=at) == "history-2026-11-18T09-30-05Z.xlsx"
    assert x.report_name("errors", "csv", "", now=at) == "errors-2026-11-18T09-30-05Z.csv"
