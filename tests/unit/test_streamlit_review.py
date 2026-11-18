"""The review screen (#252): rows with their errors, and a reviewer's exclude, edit and history, against a faked API.

Forms are inline in the row panel (no dialog) so AppTest can drive them. The browser side (the grid's own row
click, a real tab) is e2e/test_streamlit_review.py.
"""
import pytest
import streamlit as st

from tests.unit.streamlit_harness import view
import api_client
from views import allowed_screens, review

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ALICE, RITA, AUDREY = ("acme", "alice"), ("acme", "rita"), ("acme", "audrey")
UP = "/api/csv/uploads"
COLUMNS = ["id", "name", "amount"]


def _row(n, current, errors=(), decision="include", reason=None, edited=()):
    return {"rowNumber": n, "current": current, "original": current, "errors": list(errors),
            "decision": decision, "decisionReason": reason, "editedColumns": list(edited)}


ROWS = {
    "fileName": "people.csv", "total": 3, "excludedRows": 0, "editedRows": 0, "columns": COLUMNS,
    "rows": [_row(1, ["1", "ann", "10"]),
             _row(2, ["2", "bob", "x"], [{"column": "amount", "value": "x", "reason": "is not a whole number"}]),
             _row(3, ["3", "cy", "30"], [{"column": "(database)", "value": "", "reason": "duplicate key value"}])],
}
HISTORY = [{"kind": "decision", "decision": "exclude", "column": None, "oldValue": None, "newValue": None,
            "at": "2026-11-18T09:30:00+00:00", "actor": "rita", "reason": "dup of row 1"}]


@pytest.fixture(autouse=True)
def fresh_cache():
    st.cache_data.clear()  # uploads_list is cached for the whole process, keyed by token


@pytest.fixture
def served(api):
    api.routes[("GET", UP)] = [{"id": 7, "file_name": "people.csv", "status": "imported", "total_rows": 3}]
    api.routes[("GET", f"{UP}/7/rows")] = ROWS
    api.routes[("GET", f"{UP}/7/rows/2/history")] = HISTORY
    api.routes[("PUT", f"{UP}/7/rows/2/decision")] = {"status": "ok"}
    api.routes[("PUT", f"{UP}/7/rows/2/cells/1")] = {"status": "ok"}
    return api


def _pick(at, n):
    next(w for w in at.number_input if w.label == "Row number").set_value(n)
    return at.run()


def _fill(at, label, text, nth=0):
    [w for w in at.text_input if w.label == label][nth].input(text)


def _press(at, label):
    next(b for b in at.button if b.label == label).click()
    return at.run()


def _labels(at):
    return [b.label for b in at.button]


def test_rows_show_their_validation_and_database_errors(served):
    at = _pick(view("review", RITA, served), 3)
    assert any("(database)" in e.value and "duplicate key value" in e.value for e in at.error)
    at = _pick(at, 2)
    assert any("amount" in e.value and "is not a whole number" in e.value for e in at.error)


def test_uploader_sees_read_only_and_no_change_controls(served):
    at = _pick(view("review", ALICE, served), 2)
    assert any("read-only for your role" in c.value for c in at.caption)
    assert "History" in _labels(at)
    assert not {"Exclude", "Include", "Save edit"} & set(_labels(at))


def test_reviewer_exclude_needs_a_reason(served):
    at = _pick(view("review", RITA, served), 1)
    at = _press(at, "Exclude")
    assert at.error.values == ["Give a reason."]
    assert not [c for c in served.calls if c[0] == "PUT"]


def test_reviewer_exclude_sends_decision(served):
    at = _pick(view("review", RITA, served), 2)
    _fill(at, "Reason (required)", "dup", nth=0)
    _press(at, "Exclude")
    puts = [c for c in served.calls if c[0] == "PUT"]
    assert [(c[1], c[3]) for c in puts] == [(f"{UP}/7/rows/2/decision", {"decision": "exclude", "reason": "dup"})]


def test_reviewer_edit_sends_new_value_with_reason(served):
    at = _pick(view("review", RITA, served), 2)
    next(s for s in at.selectbox if s.label == "Column").select_index(1)
    _fill(at, "New value", "20")
    _fill(at, "Reason (required)", "typo", nth=1)
    _press(at, "Save edit")
    puts = [c for c in served.calls if c[0] == "PUT"]
    assert [(c[1], c[3]) for c in puts] == [(f"{UP}/7/rows/2/cells/1", {"value": "20", "reason": "typo"})]


def test_edit_needs_a_reason_too(served):
    at = _pick(view("review", RITA, served), 2)
    _fill(at, "New value", "20")
    at = _press(at, "Save edit")
    assert at.error.values[-1] == "Give a reason."
    assert not [c for c in served.calls if c[0] == "PUT"]


def test_an_api_error_on_save_is_shown(served):
    def refuse(token, **kw):
        raise api_client.ApiError(403, "Role cannot review rows")
    served.routes[("PUT", f"{UP}/7/rows/2/decision")] = refuse
    at = _pick(view("review", RITA, served), 2)
    _fill(at, "Reason (required)", "dup", nth=0)
    at = _press(at, "Exclude")
    assert "Role cannot review rows" in at.error.values


def test_history_lists_entries(served):
    at = _pick(view("review", ALICE, served), 2)
    at = _press(at, "History")
    shown = " ".join(m.value for m in at.markdown)
    assert "rita" in shown and "dup of row 1" in shown
    assert "rita" in " ".join(m.value for m in at.run().markdown)  # still there after another rerun


def test_failed_or_partial_filter_and_rejected_has_no_rows(served):
    served.routes[("GET", UP)] = [
        {"id": 7, "file_name": "people.csv", "status": "imported", "total_rows": 3},
        {"id": 8, "file_name": "half.csv", "status": "partly_imported", "total_rows": 5, "failed_rows": 2},
        {"id": 9, "file_name": "bad.csv", "status": "rejected", "total_rows": 0, "failure_reason": "Header is empty"}]
    at = view("review", RITA, served)
    box = next(s for s in at.selectbox if s.label == "Upload")
    assert len(box.options) == 3
    next(c for c in at.checkbox if c.label == "Only failed or partly imported").check()
    at.run()
    box = next(s for s in at.selectbox if s.label == "Upload")
    assert len(box.options) == 2
    box.select_index(1)
    served.calls.clear()
    at.run()
    assert any("rejected" in i.value and "Header is empty" in i.value for i in at.info)
    assert not [c for c in served.calls if c[1].endswith("/rows")]


def test_no_uploads_says_so(served):
    served.routes[("GET", UP)] = []
    assert view("review", RITA, served).info.values == ["No uploads yet."]


def test_401_on_save_signs_out(served):
    def gone(token, **kw):
        raise api_client.Unauthorized(401, "Not signed in")
    served.routes[("PUT", f"{UP}/7/rows/2/decision")] = gone
    at = _pick(view("review", RITA, served), 2)
    _fill(at, "Reason (required)", "dup", nth=0)
    at = _press(at, "Exclude")
    assert "session" not in at.session_state
    assert at.session_state["notice"] == "Your session has ended. Sign in again."


def test_saving_clears_the_uploads_cache(served):
    at = _pick(view("review", RITA, served), 2)
    before = len(served.calls_to(UP))
    _fill(at, "Reason (required)", "dup", nth=0)
    _press(at, "Exclude")
    assert len(served.calls_to(UP)) > before


def test_allowed_screens_follow_permissions():
    assert allowed_screens("auditor") == ["review"]  # extended in Tasks 5 and 6
    assert review.PAGE == 100
