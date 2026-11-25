"""The rules that turn the upload API's answer into words (streamlit_app/outcomes.py).

Ported from the React app's csv-table-hub-main/src/__tests__/job-outcome.test.ts: one case per answer the API gives
(ok, duplicate_file, invalid_structure, error), the failed-rows and type-provenance notes, and what is new here: file
text must not become Markdown, a timeout is not "can't reach the API", and the version and schema notes (M5).
"""
import pytest

from tests.unit import streamlit_harness  # noqa: F401  (puts streamlit_app on the path)
# The imports below need the path the import above sets up, so the import sort must not move them up.
# isort: split

import api_client  # noqa: E402
import outcomes as o  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

OK = {"status": "ok", "fileId": "1", "tableName": "csv_people_v1", "totalRows": 30, "insertedRows": 26,
      "duplicateRowsSkipped": 0, "failedRows": 4, "columns": ["id"], "types": ["int8"], "rowErrors": [], "logs": []}


# ── the four answers (React: classifyUploadResult) ─────────────────────────────────────────

def test_a_clean_import_is_a_success_that_says_how_many_rows_went_in():
    out = o.classify("people.csv", {**OK, "failedRows": 0, "insertedRows": 30})

    assert (out.kind, out.level) == ("done", "success")
    assert out.message == "` people.csv `: 30 of 30 rows imported"


def test_an_import_that_lost_rows_is_a_warning_that_says_how_many():
    out = o.classify("people.csv", OK)

    assert (out.kind, out.level) == ("done", "warning")
    assert out.message == "` people.csv `: 26 of 30 rows imported · 4 failed"


def test_an_overwrite_is_said_first_as_the_react_app_said_it():
    assert o.classify("a.csv", {**OK, "overwritten": True}).message.startswith("` a.csv `: overwrote · 26 of 30")


def test_the_same_bytes_again_is_a_duplicate_and_says_nothing_changed():
    out = o.classify("again.csv", {"status": "duplicate_file", "reason": "content", "existingFileName": "people.csv",
                                   "tableName": "csv_people_v1", "logs": []})

    assert (out.kind, out.level) == ("duplicate", "warning")
    assert out.message == "` again.csv `: already imported as ` people.csv `. Nothing was changed."


def test_a_duplicate_with_no_name_for_the_earlier_import_still_reads_well():
    out = o.classify("a.csv", {"status": "duplicate_file", "reason": "content", "logs": []})

    assert out.message == "` a.csv `: already imported earlier. Nothing was changed."


def test_the_old_same_name_different_contents_duplicate_is_still_worded():
    out = o.classify("a.csv", {"status": "duplicate_file", "reason": "name", "existingFileName": "a.csv", "logs": []})

    assert out.kind == "duplicate" and "different contents" in out.message


@pytest.mark.parametrize("reason, said", [
    ("empty", "The file is empty."),
    ("header_only", "The file has a header row but no data rows."),
    ("no_columns", "The header row has no column names."),
    ("parse_failed", "The file could not be read as CSV."),
    ("something_new", "The file has no usable structure."),
])
def test_a_file_with_no_usable_structure_says_why_in_plain_words(reason, said):
    out = o.classify("a.csv", {"status": "invalid_structure", "reason": reason, "logs": []})

    assert (out.kind, out.level, out.message) == ("error", "error", f"` a.csv `: {said}")


def test_the_apis_own_message_wins_over_the_plain_words():
    out = o.classify("a.csv", {"status": "invalid_structure", "reason": "empty", "message": "Nothing to import", "logs": []})

    assert out.message == "` a.csv `: ` Nothing to import `"


def test_an_error_carries_the_apis_message():
    out = o.classify("a.csv", {"status": "error", "message": "Provided 2 column types but the CSV has 3 columns.", "logs": []})

    assert (out.kind, out.level) == ("error", "error")
    assert out.message == "` a.csv `: ` Provided 2 column types but the CSV has 3 columns. `"


def test_an_error_with_no_message_still_says_it_failed():
    assert o.classify("a.csv", {"status": "error", "logs": []}).message == "` a.csv `: The import failed."


# ── the call itself failed (React: classifyThrownError) ───────────────────────────────────

def test_a_refusal_from_the_api_is_an_error_in_its_words():
    out = o.classify_error("a.csv", api_client.ApiError(413, "File too large"))

    assert (out.kind, out.level) == ("error", "error") and out.message == "` a.csv `: ` File too large `"


def test_an_api_that_is_not_there_says_so():
    out = o.classify_error("a.csv", api_client.Unreachable())

    assert out.kind == "error" and "Can't reach the API" in out.message


def test_no_answer_in_time_is_not_a_failure_because_the_server_may_still_be_importing():
    out = o.classify_error("big.csv", api_client.TimedOut(600))

    assert (out.kind, out.level) == ("unknown", "warning")
    assert "may still be working" in out.message and "Import history" in out.message and "Can't reach" not in out.message


# ── text from a file is shown as written ──────────────────────────────────────────────────

def test_a_file_name_and_an_api_message_that_look_like_links_are_in_code_spans():
    evil = "[click](https://evil.example/x)"

    assert o.classify(f"{evil}.csv", {"status": "error", "message": f"bad {evil}"}).message == \
        f"` {evil}.csv `: ` bad {evil} `"
    assert o.classify_error(f"{evil}.csv", api_client.ApiError(422, f"bad {evil}")).message == \
        f"` {evil}.csv `: ` bad {evil} `"


# ── what else is worth saying (M5) ────────────────────────────────────────────────────────

def test_a_new_version_says_which_dataset_and_how_the_columns_compare():
    notes = o.result_notes({**OK, "dataset": "people", "version": 2, "schemaCheck": {
        "compatible": True, "added": ["email"], "removed": [], "changed": [],
        "comparedTo": {"fileName": "people.csv", "version": 1, "tableName": "csv_people_v1"}},
        "duplicateRowsAcrossUploads": 3})

    assert notes == ["Version 2 of the dataset ` people `.",
                     "Columns match the previous version (version 1), with 1 new: ` email `.",
                     "3 rows already appear in an earlier version of this dataset."]


def test_columns_that_differ_say_what_was_removed_retyped_and_added():
    notes = o.result_notes({"version": 2, "dataset": "d", "schemaCheck": {
        "compatible": False, "added": ["c"], "removed": ["a"], "changed": [{"column": "b", "was": "int8", "now": "text"}],
        "comparedTo": {"version": 1}}})

    assert notes[1] == ("Columns differ from the previous version (version 1): removed ` a `; "
                        "retyped ` b ` (int8 → text); new ` c `.")


def test_a_first_version_with_nothing_to_compare_has_just_the_version():
    assert o.result_notes({**OK, "dataset": "people", "version": 1, "schemaCheck": None}) == [
        "Version 1 of the dataset ` people `."]


def test_rows_skipped_as_duplicates_within_the_file_are_counted():
    assert o.result_notes({"duplicateRowsSkipped": 1}) == ["1 duplicate row in the file was skipped."]
    assert o.result_notes({"duplicateRowsSkipped": 2}) == ["2 duplicate rows in the file were skipped."]
    assert o.result_notes({}) == []


def test_a_column_name_that_looks_like_a_link_is_a_code_span_in_a_note():
    notes = o.result_notes({"schemaCheck": {"compatible": False, "added": [], "removed": ["[a](http://x.test)"],
                                            "changed": []}})

    assert "` [a](http://x.test) `" in notes[0]


# ── the notes under a file in the list (React: failedRowsNote, typesProvenanceNote) ───────

def test_failed_rows_are_named_out_of_the_total():
    assert o.failed_rows_note(51, 171) == "51 of 171 rows failed"
    assert o.failed_rows_note(51, None) == "51 rows failed"


def test_no_failed_rows_or_counts_from_before_the_feature_is_no_note():
    assert o.failed_rows_note(0, 10) is None and o.failed_rows_note(None, 10) is None


def test_types_nobody_confirmed_are_said_so_and_nothing_else_is():
    assert o.types_provenance_note("inferred_unconfirmed") == "Column types were not confirmed by a person."
    assert o.types_provenance_note("user_confirmed") is None and o.types_provenance_note(None) is None


def test_the_no_cancel_wording_is_the_react_apps_own():
    assert o.NO_CANCEL == "Sent to the server; it can't be stopped now"
