"""The outcome rules the Streamlit screens share (#187, #123, #195): pure functions, no Streamlit, no API."""
import pytest

# The harness import puts streamlit_app on sys.path, so it must come before the app import below.
from tests.unit.streamlit_harness import APP_DIR  # noqa: F401

from outcomes import (  # noqa: E402
    STATUS_LABELS,
    describe_result,
    failed_rows_note,
    needs_attention,
    types_provenance_note,
)

pytestmark = [pytest.mark.unit]


def test_needs_attention():
    assert [s for s in STATUS_LABELS if needs_attention(s)] == ["partly_imported", "failed", "rejected"]


def test_failed_rows_note():
    assert failed_rows_note({"failed_rows": 51, "total_rows": 171}) == "51 of 171 rows failed"
    assert failed_rows_note({"failed_rows": 3, "total_rows": None}) == "3 rows failed"
    assert failed_rows_note({"failed_rows": 0, "total_rows": 9}) is None


def test_types_provenance_note():
    assert types_provenance_note({"types_provenance": "inferred_unconfirmed"}) == "Column types were not confirmed by a person."
    assert types_provenance_note({"types_provenance": "confirmed"}) is None


def test_describe_ok_clean_and_with_failures():
    assert describe_result("a.csv", {"status": "ok", "insertedRows": 10, "totalRows": 10, "failedRows": 0}) == ("success", "a.csv: 10 of 10 rows imported")
    assert describe_result("a.csv", {"status": "ok", "insertedRows": 6, "totalRows": 10, "failedRows": 4}) == ("warning", "a.csv: 6 of 10 rows imported · 4 failed")


def test_describe_duplicate_and_errors():
    assert describe_result("a.csv", {"status": "duplicate_file", "existingFileName": "old.csv"}) == ("warning", "a.csv: already imported as old.csv; nothing was changed.")
    assert describe_result("a.csv", {"status": "invalid_structure", "message": "No header row"}) == ("error", "a.csv: No header row")
    assert describe_result("a.csv", {"status": "error", "message": "Boom"}) == ("error", "a.csv: Boom")


def test_describe_unknown_status_does_not_raise():
    assert describe_result("a.csv", {"status": "weird", "message": "Odd"}) == ("error", "a.csv: Odd")
    assert describe_result("a.csv", {"status": "weird", "reason": "Why"}) == ("error", "a.csv: Why")
    assert describe_result("a.csv", {"status": "weird"}) == ("error", "a.csv: weird")
