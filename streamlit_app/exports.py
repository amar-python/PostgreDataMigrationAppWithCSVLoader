"""CSV and XLSX reports for the Streamlit app: an import's error report and the import history (#253, #255).

A port of the React app's `export.ts`, with its formula-injection guard (#193). No Streamlit import, so it is
easy to test. Every cell in a report holds text that came from someone else's file (a cell value, a file
name, a reason), so every text cell goes through `guard()`.

What is not carried over: "Print / save as PDF". The React app opened a print window; a Streamlit page can be
printed from the browser, and the sample verification report (#59) is the PDF that matters.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

# Spreadsheet programs run a cell that starts with one of these as a formula (OWASP "CSV injection"). A plain
# number such as -5 or +3.2 is left alone. Same two rules as csv-table-hub-main/src/lib/export.ts.
FORMULA_START = re.compile(r"^[=+\-@\t\r]")
PLAIN_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")
# Control characters a person cannot see. A program may skip them and then read a formula after them, so
# the guard looks past them; and an XLSX file cannot hold them at all (openpyxl refuses).
INVISIBLE = re.compile(r"^[\x00-\x08\x0b\x0c\x0e-\x1f]+")
XLSX_CELL_LIMIT = 32_767  # the most characters Excel keeps in one cell; a longer text corrupts the file
XLSX_SHEET_LIMIT = 31

ERROR_HEADERS = ["file", "row_number", "column", "value", "reason", "plain_english", "header_mapping"]
HISTORY_HEADERS = ["file", "status", "uploaded_at", "uploader", "mode", "state", "total_rows", "imported_rows",
                   "failed_rows", "reason", "upload_id"]

CSV_TYPE = "text/csv"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def guard(value: object) -> object:
    """A text cell that a spreadsheet would run as a formula gets a leading quote. Anything else is returned as is."""
    if not isinstance(value, str):
        return value
    probe = INVISIBLE.sub("", value)
    if FORMULA_START.match(probe) and not PLAIN_NUMBER.match(probe):
        return "'" + value
    return value


def _cell(value: object) -> object:
    return "" if value is None else guard(value)


# ── files ───────────────────────────────────────────────────────────────────────────────────

def to_csv(headers: list[str], rows: list[dict]) -> bytes:
    """The rows as CSV, UTF-8, a line feed after each line (as the React export does). Quoted only where needed."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_cell(row.get(h)) for h in headers])
    return out.getvalue().encode("utf-8")


def _xlsx_text(text: str) -> str:
    text = ILLEGAL_CHARACTERS_RE.sub("\ufffd", text)
    return text if len(text) <= XLSX_CELL_LIMIT else text[:XLSX_CELL_LIMIT - 1] + "\u2026"


def to_xlsx(sheet: str, headers: list[str], rows: list[dict]) -> bytes:
    """The rows as an XLSX workbook with one sheet. Text is always stored as text, never as a formula."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:XLSX_SHEET_LIMIT]
    ws.append(headers)
    for row in rows:
        values = [_cell(row.get(h)) for h in headers]
        ws.append([_xlsx_text(v) if isinstance(v, str) else v for v in values])
    for line in ws.iter_rows(min_row=2):  # openpyxl would read a text that starts with "=" as a formula: say it is text
        for cell in line:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report_name(kind: str, ext: str, file_name: str | None = None, now: datetime | None = None) -> str:
    """'errors-people-2026-11-18T09-30-00Z.csv', as the React app names them (a safe stem, a UTC time stamp)."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H-%M-%SZ")
    stem = re.sub(r"[^a-z0-9_-]+", "_", re.sub(r"\.csv$", "", file_name or "", flags=re.I), flags=re.I)
    return f"{kind}-{stem}-{stamp}.{ext}" if stem else f"{kind}-{stamp}.{ext}"


# ── what goes in them ───────────────────────────────────────────────────────────────────────

def mapping_summary(mapping: list[dict] | None) -> str:
    """'a→b, c→d' for the renamed columns, '(no renames)' if none was renamed, '' if there was no mapping."""
    if not mapping:
        return ""
    renames = [f"{c['original']}→{c['renamed']}" for c in mapping if c.get("renamed") and c["renamed"] != c["original"]]
    return ", ".join(renames) if renames else "(no renames)"


def error_rows(file_name: str, row_errors: list[dict], message: str | None = None,
               mapping: list[dict] | None = None) -> list[dict]:
    """One report row per row error. An import that failed as a whole, with no row errors, gets one row for its message."""
    summary = mapping_summary(mapping)
    rows = []
    if message and not row_errors:
        rows.append({"file": file_name, "row_number": 0, "column": "", "value": "", "reason": message,
                     "plain_english": message, "header_mapping": summary})
    for e in row_errors:
        rows.append({"file": file_name, "row_number": e.get("rowNumber"), "column": e.get("column") or "",
                     "value": e.get("value") or "", "reason": e["reason"], "plain_english": e["reason"],
                     "header_mapping": summary})
    return rows


def history_rows(uploads: list[dict]) -> list[dict]:
    """The import history as report rows: one per upload attempt, from `GET /api/csv/uploads`."""
    return [{"file": u["file_name"], "status": u["status"], "uploaded_at": u["uploaded_at"],
             "uploader": u.get("uploader") or "", "mode": u.get("mode") or "", "state": u.get("state") or "",
             "total_rows": u.get("total_rows"), "imported_rows": u.get("imported_rows"),
             "failed_rows": u.get("failed_rows"), "reason": u.get("failure_reason") or "", "upload_id": u["id"]}
            for u in uploads]
