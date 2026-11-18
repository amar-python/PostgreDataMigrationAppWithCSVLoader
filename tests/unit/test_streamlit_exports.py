"""CSV and XLSX exports for the Streamlit screens, with the CSV formula-injection guard (#193). Pure functions."""
import io

import openpyxl
import pytest

# The harness import puts streamlit_app on sys.path, so it must come before the app import below.
from tests.unit.streamlit_harness import APP_DIR  # noqa: F401

from exports import (  # noqa: E402
    ERROR_HEADERS,
    HISTORY_HEADERS,
    error_rows,
    history_rows,
    safe_cell,
    to_csv,
    to_xlsx,
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("raw,out", [("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"), ("+1+2", "'+1+2"), ("@SUM(A1)", "'@SUM(A1)"),
                                     ("\tx", "'\tx"), ("-5", "-5"), ("+3.2", "+3.2"), ("-1+2", "'-1+2"), ("plain", "plain"), (None, ""), (7, 7)])
def test_safe_cell(raw, out):
    assert safe_cell(raw) == out


def test_safe_cell_does_not_treat_trailing_newline_as_plain_number():
    # "-5\n" must not slip through as a plain number: the number pattern is a full match.
    assert safe_cell("-5\n") == "'-5\n"


def test_csv_is_guarded_and_quoted():
    data = to_csv(["a", "b"], [{"a": "=1+1", "b": 'say "hi", ok'}]).decode()
    assert data.splitlines() == ["a,b", "'=1+1,\"say \"\"hi\"\", ok\""]


def test_csv_missing_keys_become_empty_cells():
    assert to_csv(["a", "b"], [{"a": 1}]).decode() == "a,b\n1,\n"


def test_xlsx_is_guarded():
    wb = openpyxl.load_workbook(io.BytesIO(to_xlsx("x" * 40, ["a"], [{"a": "=HYPERLINK(1)"}])))
    ws = wb.worksheets[0]
    assert ws.title == "x" * 31 and ws["A2"].value == "'=HYPERLINK(1)"


def test_error_rows_from_detail_and_fallback():
    detail = {"rowErrors": [{"rowNumber": 3, "column": "age", "value": "x", "reason": "not a number"}]}
    assert error_rows({"file_name": "a.csv"}, detail) == [{"file": "a.csv", "row_number": 3, "column": "age", "value": "x", "reason": "not a number"}]
    assert error_rows({"file_name": "a.csv", "failure_reason": "empty file"}, {"rowErrors": []}) == [{"file": "a.csv", "row_number": 0, "column": "", "value": "", "reason": "empty file"}]


def test_error_headers_match_error_row_keys():
    assert ERROR_HEADERS == ["file", "row_number", "column", "value", "reason"]


def test_history_rows_map_upload_items_and_fill_missing_keys():
    uploads = [{"file_name": "a.csv", "status": "imported", "uploaded_at": "2026-11-01T10:00:00Z", "uploader": "alice",
                "mode": "append", "total_rows": 10, "imported_rows": 9, "failed_rows": 1, "failure_reason": None},
               {"file_name": "=bad.csv", "status": "failed"}]
    assert history_rows(uploads) == [
        {"file": "a.csv", "status": "imported", "uploaded_at": "2026-11-01T10:00:00Z", "uploader": "alice", "mode": "append",
         "total_rows": 10, "imported_rows": 9, "failed_rows": 1, "failure_reason": None},
        {"file": "=bad.csv", "status": "failed", "uploaded_at": None, "uploader": None, "mode": None,
         "total_rows": None, "imported_rows": None, "failed_rows": None, "failure_reason": None},
    ]
    assert HISTORY_HEADERS == ["file", "status", "uploaded_at", "uploader", "mode", "total_rows", "imported_rows", "failed_rows", "failure_reason"]


def test_xlsx_drops_control_characters():
    wb = openpyxl.load_workbook(io.BytesIO(to_xlsx("x", ["a"], [{"a": "a\x01b"}])))
    assert wb.active["A2"].value == "ab"


def test_xlsx_strips_control_characters_before_the_formula_guard():
    wb = openpyxl.load_workbook(io.BytesIO(to_xlsx("x", ["a"], [{"a": "\x01=cmd"}])))
    assert wb.active["A2"].value == "'=cmd"
