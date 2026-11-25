"""What an upload's answer means, in words (#255): a port of the React app's `job-outcome.ts`.

The API answers an upload with one of four things (`ok`, `duplicate_file`, `invalid_structure`, `error`), or the
call itself fails (a refusal, a timeout, no API). This turns each into one line for the person, a kind and a level,
as the React toast did. No Streamlit import, so it is easy to test. Anything a person put in a file reaches the
page through `review_model.literal` (see there for why).
"""

from __future__ import annotations

from dataclasses import dataclass

import api_client
import review_model as m

NO_CANCEL = "Sent to the server; it can't be stopped now"  # the React app's own words (#188)

# What the API says when it gives a reason and no message (api/services/csv_parse.py build_preview).
STRUCTURE_REASONS = {
    "empty": "The file is empty.",
    "header_only": "The file has a header row but no data rows.",
    "no_columns": "The header row has no column names.",
    "parse_failed": "The file could not be read as CSV.",
}


@dataclass(frozen=True)
class Outcome:
    kind: str  # "done", "duplicate", "error", or "unknown" (the server may still be working)
    level: str  # "success", "warning" or "error": which kind of box to show it in
    message: str  # one line, starting with the file name; Markdown-safe (file text is in code spans)


def classify(name: str, res: dict) -> Outcome:
    """The API's answer to POST /api/csv/upload, as one line."""
    file = m.literal(name)
    status = res.get("status")
    if status == "ok":
        failed = res.get("failedRows") or 0
        line = (
            f"{file}: {'overwrote · ' if res.get('overwritten') else ''}{res.get('insertedRows', 0)} of "
            f"{res.get('totalRows', 0)} rows imported" + (f" · {failed} failed" if failed else "")
        )
        return Outcome("done", "warning" if failed else "success", line)
    if status == "duplicate_file":
        if res.get("reason") == "name":
            return Outcome(
                "duplicate", "warning", f"{file}: a file with this name is already imported with different contents."
            )
        existing = res.get("existingFileName")
        as_ = f" as {m.literal(existing)}" if existing else " earlier"
        return Outcome("duplicate", "warning", f"{file}: already imported{as_}. Nothing was changed.")
    if status == "invalid_structure":
        said = res.get("message")
        text = (
            m.literal(said)
            if said
            else STRUCTURE_REASONS.get(str(res.get("reason")), "The file has no usable structure.")
        )
        return Outcome("error", "error", f"{file}: {text}")
    return Outcome(
        "error", "error", f"{file}: {m.literal(res['message']) if res.get('message') else 'The import failed.'}"
    )


def classify_error(name: str, err: Exception) -> Outcome:
    """The call itself failed. A timeout is not a failure: the request got there and the server may still be importing."""
    file = m.literal(name)
    if isinstance(err, api_client.TimedOut):
        return Outcome("unknown", "warning", f"{file}: {err}")
    ours = isinstance(err, api_client.Unreachable)  # these say nothing from the file; an API message may
    return Outcome("error", "error", f"{file}: {err if ours else m.literal(err)}")


def result_notes(res: dict) -> list[str]:
    """What else is worth saying about a successful dynamic upload (M5, #109): the dataset's version, how its columns
    compare with the previous version, and rows already seen in an earlier one. Markdown-safe."""
    notes = []
    if res.get("version"):
        notes.append(f"Version {res['version']} of the dataset {m.literal(res.get('dataset') or '')}.")
    check = res.get("schemaCheck")
    if check:
        earlier = check.get("comparedTo") or {}
        prev = f" (version {earlier['version']})" if earlier.get("version") else ""
        if check.get("compatible"):
            added = check.get("added") or []
            notes.append(
                "Columns match the previous version"
                + prev
                + (f", with {len(added)} new: {', '.join(m.literal(c) for c in added)}." if added else ".")
            )
        else:
            parts = []
            if check.get("removed"):
                parts.append("removed " + ", ".join(m.literal(c) for c in check["removed"]))
            if check.get("changed"):
                parts.append(
                    "retyped "
                    + ", ".join(f"{m.literal(c['column'])} ({c['was']} → {c['now']})" for c in check["changed"])
                )
            if check.get("added"):
                parts.append("new " + ", ".join(m.literal(c) for c in check["added"]))
            notes.append("Columns differ from the previous version" + prev + ": " + "; ".join(parts) + ".")
    dupes = res.get("duplicateRowsAcrossUploads")
    if dupes:
        notes.append(f"{dupes} row{'' if dupes == 1 else 's'} already appear in an earlier version of this dataset.")
    skipped = res.get("duplicateRowsSkipped")
    if skipped:
        notes.append(
            f"{skipped} duplicate row{'' if skipped == 1 else 's'} in the file {'was' if skipped == 1 else 'were'} skipped."
        )
    return notes


def failed_rows_note(failed: int | None, total: int | None) -> str | None:
    """'51 of 171 rows failed' for an upload with failures (#123); else None."""
    if not failed:
        return None
    return f"{failed} of {total} rows failed" if total else f"{failed} rows failed"


def types_provenance_note(provenance: str | None) -> str | None:
    """Says so when a dynamic table's column types were never confirmed by a person (#195); None otherwise."""
    return "Column types were not confirmed by a person." if provenance == "inferred_unconfirmed" else None
