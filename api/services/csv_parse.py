"""CSV parsing, header sanitisation, type inference and value casting.

Python port of the frontend's csv.functions.ts / csv-preview.ts logic so that
server behaviour matches what the UI previews. Kept dependency-free (no pandas)
— the files are parsed with the same quoted-field state machine as the TS code.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

ALLOWED_TYPES = ["int8", "numeric", "date", "timestamptz", "boolean", "text"]

_RESERVED = {"_id", "_row_hash", "_created_at"}

_INT_RE = re.compile(r"^-?\d+$")
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOOL_TRUE = {"true", "t", "yes", "y", "1"}
_BOOL_FALSE = {"false", "f", "no", "n", "0"}
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def parse_csv(text: str) -> list[list[str]]:
    """Parse CSV handling quoted fields, escaped quotes and embedded newlines."""
    rows: list[list[str]] = []
    field = ""
    row: list[str] = []
    in_quotes = False
    src = text[1:] if text.startswith("﻿") else text
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and src[i + 1] == '"':
                    field += '"'
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            field += ch
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            i += 1
            continue
        if ch == ",":
            row.append(field)
            field = ""
            i += 1
            continue
        if ch == "\r":
            i += 1
            continue
        if ch == "\n":
            row.append(field)
            rows.append(row)
            row = []
            field = ""
            i += 1
            continue
        field += ch
        i += 1
    if field or row:
        row.append(field)
        rows.append(row)
    while rows and all(c == "" for c in rows[-1]):
        rows.pop()
    return rows


def sanitize_columns(headers: list[str]) -> list[str]:
    """Lowercase, strip invalid chars, dedupe — mirrors sanitizeColumns() in TS."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for idx, h in enumerate(headers):
        base = (h or f"column_{idx + 1}").lower().strip()
        base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_")
        if not base:
            base = f"column_{idx + 1}"
        if base[0].isdigit():
            base = f"col_{base}"
        if base in _RESERVED:
            base = f"{base}_col"
        if len(base) > 55:
            base = base[:55]
        count = seen.get(base, 0)
        name = base if count == 0 else f"{base}_{count + 1}"
        seen[base] = count + 1
        out.append(name)
    return out


def valid_identifier(name: str) -> bool:
    return bool(_IDENT_RE.match(name))


def infer_type(values: list[str]) -> str:
    """Pick the narrowest type that fits all non-empty sampled values."""
    non_empty = [v.strip() for v in values if v is not None and v.strip() != ""]
    if not non_empty:
        return "text"

    def all_match(pred) -> bool:
        return all(pred(v) for v in non_empty)

    if all_match(lambda v: bool(_INT_RE.match(v))):
        return "int8"
    if all_match(lambda v: bool(_NUM_RE.match(v))):
        return "numeric"
    if all_match(lambda v: v.lower() in _BOOL_TRUE or v.lower() in _BOOL_FALSE):
        return "boolean"
    if all_match(lambda v: bool(_DATE_RE.match(v)) and _valid_date(v)):
        return "date"
    if all_match(_valid_timestamp):
        return "timestamptz"
    return "text"


def _valid_date(v: str) -> bool:
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_timestamp(v: str) -> bool:
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def cast_value(raw: str, col_type: str) -> tuple[bool, Optional[object], Optional[str]]:
    """Returns (ok, value, error_reason). Mirrors castValue() in TS."""
    v = (raw or "").strip()
    if v == "":
        return True, None, None
    if col_type == "int8":
        if not _INT_RE.match(v):
            return False, None, f'"{raw}" is not a whole number'
        return True, int(v), None
    if col_type == "numeric":
        if not _NUM_RE.match(v):
            return False, None, f'"{raw}" is not a number'
        return True, v, None
    if col_type == "boolean":
        low = v.lower()
        if low in _BOOL_TRUE:
            return True, True, None
        if low in _BOOL_FALSE:
            return True, False, None
        return False, None, f'"{raw}" is not true/false'
    if col_type == "date":
        if not _DATE_RE.match(v) or not _valid_date(v):
            return False, None, f'"{raw}" is not a YYYY-MM-DD date'
        return True, v, None
    if col_type == "timestamptz":
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return False, None, f'"{raw}" is not a valid timestamp'
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return True, d.isoformat(), None
    return True, raw, None


def build_preview(text: str, sample_rows: int = 10, infer_rows: int = 200) -> dict:
    """Preview payload: headers, sanitised columns, inferred types, sample rows."""
    rows = parse_csv(text)
    if not rows:
        return {"status": "invalid_structure", "reason": "empty"}
    if len(rows) == 1:
        return {"status": "invalid_structure", "reason": "header_only"}
    if all((c or "").strip() == "" for c in rows[0]):
        return {"status": "invalid_structure", "reason": "no_columns"}

    headers = rows[0]
    columns = sanitize_columns(headers)
    data = rows[1:]
    ncols = len(columns)

    inferred = []
    for c in range(ncols):
        sample = [r[c] if c < len(r) else "" for r in data[:infer_rows]]
        inferred.append(infer_type(sample))

    return {
        "status": "ok",
        "headers": headers,
        "columns": columns,
        "inferredTypes": inferred,
        "sampleRows": [r[:ncols] + [""] * (ncols - len(r)) for r in data[:sample_rows]],
        "totalRowsApprox": len(data),
    }
