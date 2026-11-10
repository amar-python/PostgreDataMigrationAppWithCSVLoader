"""Server-side report helpers (M7, #111; BR-35).

``csv_text`` neutralises spreadsheet formulas the same way the frontend export does
(csv-table-hub-main/src/lib/export.ts): a cell starting with = + - @ tab or CR gets a leading quote,
unless it is a plain number. Report cells hold user-supplied values, so every cell goes through it.
"""

from __future__ import annotations

import csv
import io
import re

_FORMULA_START = re.compile(r"^[=+\-@\t\r]")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


def csv_cell(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if _FORMULA_START.match(s) and not _PLAIN_NUMBER.match(s) else s


def csv_text(headers: list[str], rows: list[list]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows([csv_cell(v) for v in row] for row in rows)
    return out.getvalue()


def like_pattern(text: str) -> str:
    """A contains-match pattern for ILIKE ... ESCAPE '\\': % and _ in the text match themselves."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
