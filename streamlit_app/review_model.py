"""What the review screen (#252) shows and says, decided without Streamlit so it is easy to test.

Everything here is a plain function of the API's answers. The one rule worth stating: anything a person put
in a file (a file name, a cell value, a reason) reaches the page through `literal()`, because Streamlit reads
text as Markdown and a cell holding `[click](https://example.test)` or `**bold**` must show as written,
not as a link or as formatting in front of a reviewer.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

PAGE_SIZE = 100  # rows a page of the grid shows; the API allows up to 500 (api/services/review.py MAX_PAGE)

# #187 (BR-25): every upload attempt is listed, so a failed or partly failed one can be reached. These are
# the statuses the API gives an attempt (api/routers/csv_routes.py).
ATTEMPT_LABEL = {
    "imported": "Imported",
    "partly_imported": "Partly imported",
    "failed": "Failed",
    "rejected": "Rejected",
    "duplicate": "Duplicate",
}
NEEDS_ATTENTION = frozenset({"failed", "partly_imported", "rejected"})

EDITED_TINT = "background-color: rgba(59,130,246,.18)"
ERROR_TINT = "background-color: rgba(239,68,68,.22)"
EXCLUDED_TEXT = ";color:#9ca3af"  # st.dataframe ignores opacity, so a grey text colour says "excluded"

def literal(text: object) -> str:
    """Text from a file or a person, as an inline code span, which Markdown shows exactly as written.

    Escaping its punctuation is not enough: Streamlit's Markdown turns a bare `https://...`, `www.` or e-mail
    address into a link even when every character of it was escaped (found in a browser, e2e/test_streamlit_review.py),
    but never inside a code span. The fence is one backtick longer than the longest run in the text, so
    nothing in the text can end the span early. Line breaks and tabs become spaces.
    """
    flat = re.sub(r"[\r\n\t]+", " ", str(text))
    fence = "`" * (max((len(run) for run in re.findall(r"`+", flat)), default=0) + 1)
    return f"{fence} {flat} {fence}"  # the padding spaces are not shown, and keep a text that ends in a backtick whole


# ── which uploads ───────────────────────────────────────────────────────────────────────────

def needs_attention(status: str) -> bool:
    return status in NEEDS_ATTENTION


def reviewable(upload: dict) -> bool:
    """A rejected file has no stored rows to review (#187)."""
    return upload["status"] != "rejected"


def attempt_label(upload: dict) -> str:
    """One line per attempt, as the React list words it: how it ended and how many rows."""
    total, failed = upload.get("total_rows"), upload.get("failed_rows")
    rows = f"{failed} of {'?' if total is None else total} rows failed" if failed else f"{total or 0} rows"
    return f"#{upload['id']} {upload['file_name']} · {ATTEMPT_LABEL.get(upload['status'], upload['status'])} · {rows}"


def filter_attempts(uploads: list[dict], only_problems: bool) -> list[dict]:
    return [u for u in uploads if needs_attention(u["status"])] if only_problems else list(uploads)


def page_count(total: int) -> int:
    return max(1, -(-total // PAGE_SIZE))


# ── one page of rows ────────────────────────────────────────────────────────────────────────

def row_status(row: dict) -> str:
    return "Excluded" if row["decision"] == "exclude" else "Invalid" if row["errors"] else "Included"


def status_column(columns: list[str]) -> str:
    """A name for the status column that no column of the file already has (a file may well have one called "Status")."""
    name, n = "Row status", 1
    while name in columns:
        n += 1
        name = f"Row status ({n})"
    return name


def grid_frame(rows: list[dict], columns: list[str], status_name: str) -> pd.DataFrame:
    """The page as a table: the row number as the index, the status first, then every column's current value."""
    frame = pd.DataFrame([r["current"] for r in rows], columns=columns, index=[r["rowNumber"] for r in rows])
    frame.insert(0, status_name, [row_status(r) for r in rows])
    return frame


def tint(rows: list[dict], frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Blue for an edited cell, red for one with an error, grey text for an excluded row."""
    out = pd.DataFrame("", index=frame.index, columns=frame.columns)
    for r in rows:
        n = r["rowNumber"]
        for i in r["editedColumns"]:
            out.loc[n, columns[i]] = EDITED_TINT
        for e in r["errors"]:
            if e["column"] in columns:
                out.loc[n, e["column"]] = ERROR_TINT
        if r["decision"] == "exclude":
            out.loc[n] = out.loc[n] + EXCLUDED_TEXT
    return out


def summary(data: dict) -> str:
    """The line under the file name (the React screen's wording)."""
    rows = f"{data['total']} row{'' if data['total'] == 1 else 's'}"
    return (f"{rows} · {data['excludedRows']} excluded · {data['editedRows']} edited. Changes are saved with "
            "the upload for review. They don't change the imported table.")


# ── one row ─────────────────────────────────────────────────────────────────────────────────

def error_lines(row: dict) -> list[str]:
    """Every reason the row is invalid. One with no column of the file is the database's own (#190, column
    "(database)"), or a cell beyond the header: shown the same way, naming where it came from."""
    return [f"{literal(e['column'])}: {literal(e['reason'])}" for e in row["errors"]]


def decision_line(row: dict) -> str | None:
    if not row["decisionReason"]:
        return None
    return f"Decision: **{row['decision']}**: {literal(row['decisionReason'])}"


def edit_lines(row: dict, columns: list[str]) -> list[str]:
    return [f"{literal(columns[i])}: original {literal(row['original'][i] or '(empty)')}, "
            f"now {literal(row['current'][i] or '(empty)')}" for i in row["editedColumns"]]


def when(at: str) -> str:
    """An API timestamp as 'YYYY-MM-DD HH:MM UTC'. One with no zone is taken as UTC, as the session expiry is."""
    try:
        moment = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return literal(at)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def history_line(entry: dict) -> str:
    if entry["kind"] == "decision":
        what = f"**{'Excluded' if entry['decision'] == 'exclude' else 'Included'}**"
    else:
        what = (f"{literal(entry['column'])}: {literal(entry['oldValue'] or '(empty)')} → "
                f"{literal(entry['newValue'] or '(empty)')}")
    return f"{when(entry['at'])} · {literal(entry.get('actor') or 'unknown')} · {what}  \n{literal(entry['reason'])}"
