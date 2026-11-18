"""The import-history screen (#253): the tenant's uploads from the server, filters, errors and exports."""
from datetime import date

import pytest
import streamlit as st

from tests.unit.streamlit_harness import view
import api_client
from views import allowed_screens
from views.history import query_params

pytestmark = [pytest.mark.unit, pytest.mark.regression]

UP = "/api/csv/uploads"
UPLOADS = [
    {"id": 7, "file_name": "people.csv", "status": "partly_imported", "uploader": "alice", "mode": "append",
     "total_rows": 3, "imported_rows": 2, "failed_rows": 1, "uploaded_at": "2026-11-18T09:00:00", "failure_reason": None},
    {"id": 8, "file_name": "orders.csv", "status": "imported", "uploader": "rita", "mode": "append",
     "total_rows": 5, "imported_rows": 5, "failed_rows": 0, "uploaded_at": "2026-11-18T10:00:00", "failure_reason": None},
]
DETAIL = {"id": 7, "rowErrors": [{"rowNumber": 2, "column": "amount", "value": "x", "reason": "is not a whole number"}]}


@pytest.fixture(autouse=True)
def fresh_cache():
    st.cache_data.clear()


@pytest.fixture
def served(api):
    api.routes[("GET", UP)] = UPLOADS
    api.routes[("GET", f"{UP}/7")] = DETAIL
    return api


def test_query_params_send_only_what_is_set():
    assert query_params("", None, None, None) == {"limit": 500}
    assert query_params("orders", "failed", date(2026, 11, 1), date(2026, 11, 3)) == {
        "limit": 500, "file": "orders", "status": "failed", "from": "2026-11-01T00:00:00", "to": "2026-11-04T00:00:00"}


def test_filters_reach_the_server(served):
    at = view("history", api=served)
    next(w for w in at.text_input if w.label == "File name").input("people")
    next(w for w in at.selectbox if w.label == "Status").select("Failed")
    at.run()
    assert [p for m, path, p in served.params if path == UP][-1] == {"limit": 500, "file": "people", "status": "failed"}


def test_no_imports_match(served):
    served.routes[("GET", UP)] = []
    at = view("history", api=served)
    assert [i.value for i in at.info] == ["No imports match these filters."]


def test_errors_for_a_chosen_upload(served):
    at = view("history", api=served)
    next(w for w in at.selectbox if w.label == "Show errors for").select_index(0)
    at.run()
    assert served.calls_to(f"{UP}/7")
    assert at.table[0].value.iloc[0]["reason"] == "is not a whole number"


def test_no_row_errors_caption(served):
    served.routes[("GET", f"{UP}/7")] = {"id": 7, "rowErrors": []}
    at = view("history", api=served)
    next(w for w in at.selectbox if w.label == "Show errors for").select_index(0)
    at.run()
    assert "No row errors." in [c.value for c in at.caption]


def test_an_api_error_is_shown_not_raised(served):
    served.routes[("GET", UP)] = lambda token, **kw: (_ for _ in ()).throw(api_client.ApiError(500, "boom"))
    at = view("history", api=served)
    assert not at.exception and [e.value for e in at.error] == ["boom"]


def test_exports_are_offered(served):
    at = view("history", api=served)
    next(w for w in at.selectbox if w.label == "Show errors for").select_index(0)
    at.run()
    assert len(at.get("download_button")) == 4


def test_says_the_history_is_shared(served):
    at = view("history", api=served)
    assert any("shared by everyone in your tenant" in c.value for c in at.caption)


def test_allowed_screens_include_history():
    assert allowed_screens("auditor") == ["review", "history"]


def test_history_says_when_the_list_is_cut_at_the_limit(served):
    served.routes[("GET", UP)] = [{**UPLOADS[0], "id": i} for i in range(1, 501)]
    at = view("history", ("acme", "audrey"), served)
    assert any("Showing the newest 500; narrow the filters to see older ones." in c.value for c in at.caption)


def test_history_is_silent_below_the_limit(served):
    at = view("history", ("acme", "audrey"), served)
    assert not any("Showing the newest" in c.value for c in at.caption)
