"""CSV and XLSX exports ported from csv-table-hub-main/src/lib/export.ts. Pure functions: no Streamlit, no API.

Cells that start with a formula character get a `'` prefix (OWASP "CSV injection"), except plain numbers like -5 or +3.2.
"""
import csv
import io
import re

import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

FORMULA_START = re.compile(r"[=+\-@\t\r]")
PLAIN_NUMBER = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")

ERROR_HEADERS = ["file", "row_number", "column", "value", "reason"]
HISTORY_HEADERS = ["file", "status", "uploaded_at", "uploader", "mode", "total_rows", "imported_rows", "failed_rows", "failure_reason"]
# History headers whose API key differs from the header name; the rest match.
_HISTORY_SOURCE = {"file": "file_name"}


def safe_cell(v: object) -> object:
    if v is None:
        return ""
    if isinstance(v, str) and FORMULA_START.match(v) and not PLAIN_NUMBER.fullmatch(v):
        return "'" + v
    return v


def to_csv(headers: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for r in rows:
        writer.writerow([safe_cell(r.get(h)) for h in headers])
    return buf.getvalue().encode("utf-8")


def _xlsx_cell(v: object) -> object:
    """Strip control characters BEFORE the formula guard: "\\x01=cmd" must become "'=cmd", not a live "=cmd"."""
    if isinstance(v, str):
        v = ILLEGAL_CHARACTERS_RE.sub("", v)
    return safe_cell(v)


def to_xlsx(sheet: str, headers: list[str], rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    ws.append(headers)
    for r in rows:
        ws.append([_xlsx_cell(r.get(h)) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def error_rows(upload: dict, detail: dict) -> list[dict]:
    rows = [
        {"file": upload.get("file_name"), "row_number": e.get("rowNumber"), "column": e.get("column"),
         "value": e.get("value"), "reason": e.get("reason")}
        for e in detail.get("rowErrors") or []
    ]
    if not rows and upload.get("failure_reason"):
        rows = [{"file": upload.get("file_name"), "row_number": 0, "column": "", "value": "", "reason": upload["failure_reason"]}]
    return rows


def history_rows(uploads: list[dict]) -> list[dict]:
    return [{h: u.get(_HISTORY_SOURCE.get(h, h)) for h in HISTORY_HEADERS} for u in uploads]
