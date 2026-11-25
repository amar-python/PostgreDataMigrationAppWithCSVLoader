"""What the upload screen (#255) does with a file and what it sends, decided without Streamlit so it is easy to test.

Findings from the #254 spike that shape it (spikes/streamlit_upload/README.md, removed with this screen):

* The size limits are separate and not equal. The API refuses over `MAX_UPLOAD_BYTES` (50 MiB); Streamlit's own limit
  counts a megabyte as 1,000,000 bytes and no integer makes the two equal. So Streamlit's is set above the API's
  (`.streamlit/config.toml`) and the real limit is checked here, from the same environment variable, with a message in
  the app's own words.
* A file that is not UTF-8 is refused. The React app read it with replacement characters, which silently changes the
  data; the original bytes are still sent (`contentBase64`), so the preserved original is exact either way.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass

import pandas as pd

import review_model as m

# The API's own variable and default (api/config.py), so deployers set one number for both. Read when used.
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PREVIEW_BYTES = 512 * 1024  # how much of a file the preview reads: the server infers types from its first 200 rows
UPLOAD_TIMEOUT_SECONDS = 600  # an import of a big file takes a while; the shell's 30 s is for reads

# api/services/csv_parse.py ALLOWED_TYPES (a test fails if they drift), with the React app's labels.
ALLOWED_TYPES = ("int8", "numeric", "date", "timestamptz", "boolean", "text")
TYPE_LABELS = {
    "int8": "Whole number",
    "numeric": "Number",
    "date": "Date",
    "timestamptz": "Timestamp",
    "boolean": "True/False",
    "text": "Text",
}

DYNAMIC, TE = "dynamic", "te"
MODE_LABELS = {DYNAMIC: "New table from this file", TE: "Test and Evaluation table"}

CONFIRM = "I have checked the column names and types"


class Refused(Exception):
    """A file the screen will not send, with the reason in words fit to show. Nothing is sent. `name` is the
    file's and is shown in a code span (it came from a computer's file system); `reason` is ours."""

    def __init__(self, name: str, reason: str):
        super().__init__(f"{name} {reason}")
        self.name, self.reason = name, reason


@dataclass(frozen=True)
class Prepared:
    name: str
    raw: bytes  # as the person's computer has it: kept by the server as the preserved original
    text: str  # decoded, without a byte-order mark: what is loaded
    digest: str  # a short, stable name for this file's widgets and cached preview


def max_bytes() -> int:
    return int(os.environ.get("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))


def format_bytes(n: int) -> str:
    """'512 B', '1.5 KB', '50.00 MB': the React app's wording."""
    if n < 1024:
        return f"{n} B"
    if n < 1_048_576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1_048_576:.2f} MB"


def prepare(name: str, raw: bytes, limit: int | None = None) -> Prepared:
    """Check a chosen file before anything is sent. Raises Refused with the reason, or returns what to send."""
    limit = max_bytes() if limit is None else limit
    if not name.lower().endswith(".csv"):
        raise Refused(name, "is not a .csv file. Only CSV files can be imported.")
    if not raw:
        raise Refused(name, "is empty.")
    size = len(raw) - (3 if raw.startswith(b"\xef\xbb\xbf") else 0)  # what the API counts: the text, as UTF-8
    if size > limit:
        raise Refused(
            name, f"is {format_bytes(size)}, over the {format_bytes(limit)} limit. Split it into smaller files."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise Refused(
            name,
            f"is not UTF-8 text: the byte at position {e.start} cannot be read. Save the file as "
            "UTF-8 and choose it again.",
        ) from None
    return Prepared(name, raw, text, hashlib.sha256(raw).hexdigest()[:12])


def preview_text(prepared: Prepared, limit: int | None = None) -> tuple[str, bool]:
    """The part of the file the preview reads, cut at a line end, and whether the file was cut."""
    limit = PREVIEW_BYTES if limit is None else limit
    body = prepared.raw[3:] if prepared.raw.startswith(b"\xef\xbb\xbf") else prepared.raw
    if len(body) <= limit:
        return prepared.text, False
    cut = body[:limit]
    end = cut.rfind(b"\n")
    cut = cut[: end + 1] if end > 0 else cut
    return cut.decode("utf-8", errors="ignore"), True


def approx_rows(rows_in_preview: int, preview_bytes: int, file_bytes: int, truncated: bool) -> int:
    """About how many data rows the whole file has, from the rows in the part that was read."""
    if not truncated or preview_bytes <= 0:
        return rows_in_preview
    return round(rows_in_preview * file_bytes / preview_bytes)


def default_mode(preview: dict, te_tables: list[str]) -> str:
    """A file shaped like a Test and Evaluation table starts as one (the server's `teTableMatch`)."""
    return TE if preview.get("teTableMatch") in te_tables else DYNAMIC


def header_mapping(headers: list[str], renames: list[str]) -> list[dict]:
    """The renames the person typed, against the file's own header row. A blank keeps the name."""
    return [{"original": h, "renamed": r.strip()} for h, r in zip(headers, renames) if r and r.strip()]


def ready(mode: str, confirmed: bool, target: str | None) -> bool:
    """May this file be sent? A new table needs the types confirmed (#195, #242); a T&E load needs a target."""
    return bool(target) if mode == TE else bool(confirmed)


def build_payload(
    prepared: Prepared,
    mode: str,
    *,
    types: list[str] | None = None,
    renames: list[str] | None = None,
    headers: list[str] | None = None,
    confirmed: bool = False,
    target: str | None = None,
) -> dict:
    """The body of POST /api/csv/upload. A T&E load sends no types, no renames and no confirmation: the API refuses
    a header mapping or `typesConfirmed` there (422), because a T&E table has fixed columns."""
    body: dict[str, object] = {
        "fileName": prepared.name,
        "content": prepared.text,
        "contentBase64": base64.b64encode(prepared.raw).decode("ascii"),
        "mode": mode,
    }
    if mode == TE:
        body["targetTable"] = target
        return body
    body["types"] = list(types or [])
    body["typesConfirmed"] = bool(confirmed)
    mapping = header_mapping(headers or [], renames or [])
    if mapping:
        body["headerMapping"] = mapping
    return body


def key_for(prepared: Prepared) -> str:
    """A widget key stem for one chosen file: its name and its content. Two copies of the same bytes under two
    names are two files (and two sets of widgets); the same name and bytes twice is one (see `chosen_once`)."""
    return hashlib.sha256(prepared.name.encode("utf-8") + b"\0" + prepared.digest.encode()).hexdigest()[:12]


def chosen_once(files: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """The chosen files with a repeat of the same name and bytes dropped, and the names that were dropped."""
    seen, kept, dropped = set(), [], []
    for name, raw in files:
        ident = (name, hashlib.sha256(raw).digest())
        if ident in seen:
            dropped.append(name)
            continue
        seen.add(ident)
        kept.append((name, raw))
    return kept, dropped


def sample_frame(preview: dict) -> pd.DataFrame:
    """The server's sample rows as a table to show. `st.table` reads a cell, and a column heading, as Markdown, and
    this is a stranger's file: every text goes in a code span."""
    frame = pd.DataFrame(
        [[m.literal(c) if c else "" for c in row] for row in preview["sampleRows"]],
        columns=[m.literal(c) for c in preview["columns"]],
    )
    frame.index = range(1, len(frame) + 1)
    return frame


def column_label(header: str, i: int) -> str:
    """'column 2 (full_name)': a name for a column's boxes that cannot be read as Markdown.

    A widget's label is Markdown even when it is hidden, and Streamlit also uses it as the box's aria-label as it is
    written: a code span would be read out as "backtick name backtick", and a header that looks like a link would be a link
    in the page (found in a browser). So the header is cut down to letters, digits, spaces, underscores and hyphens, and
    cannot form a link (that takes ://, www. or @), whatever the file holds.
    """
    safe = re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", header)).strip()[:40]
    return f"column {i + 1} ({safe})" if safe else f"column {i + 1}"
