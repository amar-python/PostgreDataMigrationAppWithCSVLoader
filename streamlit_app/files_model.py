"""What the imported-files screen (#255) shows, decided without Streamlit: the React page's "Migrated files" list.

Text from a file (a file name, a value in a table) is a stranger's. `st.table` reads a cell as Markdown, so every
text in one goes through `review_model.literal`; the preview of an imported table is a `st.dataframe`, which is drawn
on a canvas and shows a cell exactly as it is.
"""

from __future__ import annotations

import pandas as pd

import outcomes
import review_model as m

PAGE_SIZE = 50  # files a page of the list shows
PREVIEW_ROWS = 50  # rows of an imported table the preview shows (the API allows up to 200)


def page_count(total: int) -> int:
    return max(1, -(-total // PAGE_SIZE))


def files_frame(files: list[dict], first: int = 1) -> pd.DataFrame:
    """A page of the list of imported files, numbered from `first`."""
    return pd.DataFrame([{
        "#": first + i, "File": m.literal(f["file_name"]), "Table": m.literal(f["table_name"]),
        "Columns": str(len(f.get("column_names") or [])), "Rows": str(f["row_count"]),
        "Failed": "" if not f.get("failed_rows") else str(f["failed_rows"]),
        "Uploaded (UTC)": m.when(f["created_at"]),
        "Uploaded by": m.literal(f["uploader"]) if f.get("uploader") else "",
    } for i, f in enumerate(files)], columns=["#", "File", "Table", "Columns", "Rows", "Failed", "Uploaded (UTC)",
                                              "Uploaded by"]).set_index("#")


def file_label(f: dict) -> str:
    """A line for the picker. The table name is in it because a repeated file name is the next version of a dataset
    (M5): two entries would otherwise read the same."""
    return f"{f['file_name']} · {f['table_name']} · {f['row_count']} rows"


def preview_frame(columns: list[str], rows: list[dict]) -> pd.DataFrame:
    """The first rows of an imported table, every value as text so that no column is guessed to be a number."""
    return pd.DataFrame([["" if r.get(c) is None else str(r.get(c)) for c in columns] for r in rows], columns=columns)


def table_notes(f: dict) -> list[str]:
    """What is worth saying under a preview: how much is shown, rows that failed, types nobody confirmed."""
    n = f["row_count"]
    notes = [f"Showing up to {PREVIEW_ROWS} rows. The table has {n} row{'' if n == 1 else 's'} in all."]
    failed = outcomes.failed_rows_note(f.get("failed_rows"), f.get("total_rows"))
    if failed:
        notes.append(f"{failed} validation and weren't imported.")
    provenance = outcomes.types_provenance_note(f.get("types_provenance"))
    if provenance:
        notes.append(provenance)
    return notes
