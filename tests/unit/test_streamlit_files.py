"""The Streamlit imported-files screen (#255): the React page's "Migrated files" list, a look inside a table, and why
rows failed. Fast and headless (AppTest, faked API).

The React tests this replaces: stored-row-errors.test.tsx (the reasons stored on the server, or the note that none were),
and failedRowsNote / typesProvenanceNote in job-outcome.test.ts. What is new: the list is the tenant's and is never
shared between sessions, and a stranger's file name or cell must not become a link.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
import streamlit as st

from tests.unit.streamlit_harness import errors, screen, widget

# The imports below need the path the import above sets up, so the import sort must not move them up.
# isort: split

import api_client  # noqa: E402
import files_model as f  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

T0 = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)


def _file(
    n, name="people.csv", rows=30, failed=0, total=None, provenance="user_confirmed", upload_id=None, uploader="alice"
):
    return {
        "id": str(n),
        "file_name": name,
        "table_name": f"csv_t{n}_v1",
        "mode": "dynamic",
        "row_count": rows,
        "column_names": ["id", "name"],
        "created_at": (T0 - timedelta(hours=n)).isoformat(),
        "total_rows": total if total is not None else rows + failed,
        "duplicate_rows_skipped": 0,
        "failed_rows": failed,
        "uploader": uploader,
        "upload_id": upload_id or str(100 + n),
        "types_provenance": provenance,
    }


class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.files = [_file(i) for i in range(1, 4)]
        self.rows: dict[str, list] = {}
        self.details: dict[str, dict] = {}
        self.dead: set[str] = set()
        self.down = False
        self.by_token: dict[str, list] = {}

    def __call__(self, method, path, token=None, **kwargs):
        self.calls.append((method, path, token, kwargs.get("params")))
        if self.down:
            raise api_client.Unreachable()
        if token in self.dead:
            raise api_client.Unauthorized(401, "Not signed in")
        if path == "/api/csv/files":
            return self.by_token.get(token, self.files)
        found = re.fullmatch(r"/api/csv/tables/(\w+)/rows", path)
        if found:
            limit = kwargs["params"]["limit"]
            return {"rows": self.rows.get(found.group(1), [{"id": 1, "name": "ann"}, {"id": 2, "name": None}])[:limit]}
        found = re.fullmatch(r"/api/csv/uploads/(\d+)", path)
        assert found, path
        return self.details.get(found.group(1), {"id": found.group(1), "rowErrors": [], "failedRows": 0})

    def count(self, path):
        return len([c for c in self.calls if c[1] == path])


@pytest.fixture(autouse=True)
def clean_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(api_client, "request", fake)
    return fake


def _files(api, who="rita", **kw):
    return screen("files", who, **kw)


def _names(at):
    return [v.strip("` ") for v in at.table[0].value["File"]]


def _look(at, fid):
    widget(at.selectbox, "Look inside a file").select(fid).run()
    assert not at.exception, at.exception
    return at


# ── the list ──────────────────────────────────────────────────────────────────────────────


def test_the_list_shows_every_imported_file_newest_first(api):
    api.files = [_file(1, "a.csv", rows=3), _file(2, "b.csv", rows=10, failed=4, total=14, uploader=None)]

    at = _files(api)

    frame = at.table[0].value
    assert _names(at) == ["a.csv", "b.csv"] and frame.index.name == "#" and list(frame.index) == [1, 2]
    assert (
        list(frame["Rows"]) == ["3", "10"]
        and list(frame["Failed"]) == ["", "4"]
        and list(frame["Columns"]) == ["2", "2"]
    )
    assert list(frame["Table"]) == ["` csv_t1_v1 `", "` csv_t2_v1 `"]
    assert list(frame["Uploaded by"]) == ["` alice `", ""]
    assert list(frame["Uploaded (UTC)"])[0] == "2026-11-18 00:00 UTC"
    assert "Files 1 to 2 of 2, newest first." in [c.value for c in at.caption]


def test_a_tenant_with_no_files_is_told_where_to_upload(api):
    api.files = []

    assert [i.value for i in _files(api).info] == ["No files yet. Upload a CSV file on the Upload page."]


def test_the_list_pages_by_fifty(api):
    api.files = [_file(i, f"f{i:03}.csv") for i in range(1, 121)]
    at = _files(api)
    assert len(_names(at)) == 50 and _names(at)[0] == "f001.csv" and "Page (of 3)" in [n.label for n in at.number_input]

    widget(at.number_input, "Page (of 3)").set_value(3).run()

    assert _names(at) == [f"f{i:03}.csv" for i in range(101, 121)]
    assert list(at.table[0].value.index)[0] == 101, "numbered through the whole list, not from 1 on each page"
    assert "Files 101 to 120 of 120, newest first." in [c.value for c in at.caption]


# ── the list is cached and never shared ───────────────────────────────────────────────────


def test_the_list_is_fetched_once_for_many_reruns_and_again_on_refresh(api):
    at = _files(api)
    _look(at, "1")
    _look(at, "2")
    assert api.count("/api/csv/files") == 1

    widget(at.button, "Refresh the list").click().run()

    assert api.count("/api/csv/files") == 2


def test_one_sessions_list_is_never_shown_to_another(api):
    api.by_token = {"tok-a": [_file(1, "acme-secret.csv")], "tok-b": [_file(2, "zed-plans.csv")]}

    a, b = _files(api, token="tok-a"), _files(api, "ada", token="tok-b")

    assert _names(a) == ["acme-secret.csv"] and _names(b) == ["zed-plans.csv"]


# ── a look inside (React: PreviewTable) ───────────────────────────────────────────────────


def test_choosing_a_file_previews_its_table_up_to_fifty_rows_with_no_guessing_about_types(api):
    api.files = [_file(1, "people.csv", rows=7)]
    api.rows["csv_t1_v1"] = [{"id": 1, "name": "ann"}, {"id": 2, "name": None}]

    at = _look(_files(api), "1")

    assert at.subheader[0].value == "` people.csv `"
    preview = at.dataframe[0].value
    assert list(preview.columns) == ["id", "name"] and preview.values.tolist() == [["1", "ann"], ["2", ""]]
    assert ("GET", "/api/csv/tables/csv_t1_v1/rows", "tok-1", {"limit": 50}) in api.calls
    assert "Showing up to 50 rows. The table has 7 rows in all." in [c.value for c in at.caption]


def test_a_table_with_no_rows_says_so(api):
    api.rows["csv_t1_v1"] = []

    at = _look(_files(api), "1")

    assert any(w.value == "The table has no rows." for w in at.markdown)


def test_a_one_row_table_says_row_not_rows(api):
    api.files = [_file(1, rows=1)]

    at = _look(_files(api), "1")

    assert "Showing up to 50 rows. The table has 1 row in all." in [c.value for c in at.caption]


def test_rows_that_failed_and_types_nobody_confirmed_are_said_under_the_preview(api):
    api.files = [_file(1, "p.csv", rows=26, failed=4, total=30, provenance="inferred_unconfirmed")]

    at = _look(_files(api), "1")

    captions = [c.value for c in at.caption]
    assert "4 of 30 rows failed validation and weren't imported." in captions
    assert "Column types were not confirmed by a person." in captions


# ── why rows failed (React: stored-row-errors.test.tsx) ───────────────────────────────────


def test_the_reasons_stored_on_the_server_are_listed_with_an_error_report(api):
    api.files = [_file(1, "p.csv", rows=26, failed=4, upload_id="9")]
    api.details["9"] = {
        "id": "9",
        "failedRows": 4,
        "rowErrors": [
            {"rowNumber": 7, "column": "amount", "value": "x", "reason": '"x" is not a whole number'},
            {"rowNumber": 14, "column": "amount", "value": "y", "reason": '"y" is not a whole number'},
        ],
    }

    at = _look(_files(api), "1")

    frame = at.table[1].value
    assert list(frame.index) == [7, 14] and list(frame["Reason"])[0] == '` "x" is not a whole number `'
    assert ("GET", "/api/csv/uploads/9", "tok-1", None) in api.calls, "the reasons come from the server record"
    assert [b.label for b in at.get("download_button")] == ["Error report (CSV)"]


def test_it_says_so_when_no_reasons_were_stored(api):
    api.files = [_file(1, "p.csv", rows=26, failed=4, upload_id="9")]

    at = _look(_files(api), "1")

    assert "No failure reasons were stored for this upload." in [c.value for c in at.caption]
    assert not at.get("download_button")


def test_a_clean_import_asks_the_server_for_no_reasons(api):
    at = _look(_files(api), "1")

    assert not [c for c in api.calls if c[1].startswith("/api/csv/uploads/")]
    assert not at.get("download_button")


def test_the_server_keeping_fewer_reasons_than_rows_failed_is_said(api):
    api.files = [_file(1, "p.csv", rows=0, failed=351, upload_id="9")]
    api.details["9"] = {
        "id": "9",
        "failedRows": 351,
        "rowErrors": [{"rowNumber": i, "reason": "bad"} for i in range(1, 201)],
    }

    at = _look(_files(api), "1")

    assert "Showing the first 200 of 351 failed rows: the server keeps the reasons for the first 200 only." in [
        c.value for c in at.caption
    ]


# ── sessions and failures ─────────────────────────────────────────────────────────────────


def test_a_session_the_server_ended_signs_the_person_out_with_a_reason(api):
    api.dead.add("tok-1")

    at = _files(api)

    assert "session" not in at.session_state and at.session_state["notice"].startswith("Your session has ended")


def test_a_session_that_ends_while_looking_inside_a_file_does_the_same(api):
    at = _files(api)
    api.dead.add("tok-1")

    widget(at.selectbox, "Look inside a file").select("1").run()

    assert "session" not in at.session_state


def test_an_api_that_is_down_says_so_instead_of_failing(api):
    api.down = True

    at = _files(api)

    assert "Can't reach the API" in errors(at)[0]


# ── text from a file is shown as written ─────────────────────────────────────────────────


def test_a_file_name_and_a_cell_that_look_like_links_show_as_written(api):
    evil = "[click](https://evil.example/x)"
    api.files = [_file(1, f"{evil}.csv", rows=1, failed=1, upload_id="9", uploader=evil)]
    api.details["9"] = {
        "id": "9",
        "failedRows": 1,
        "rowErrors": [{"rowNumber": 1, "column": evil, "value": evil, "reason": evil}],
    }
    api.rows["csv_t1_v1"] = [{"id": evil, "name": evil}]

    at = _look(_files(api), "1")

    assert at.table[0].value["File"].iloc[0] == f"` {evil}.csv `"
    assert at.table[0].value["Uploaded by"].iloc[0] == f"` {evil} `"
    assert at.subheader[0].value == f"` {evil}.csv `"
    assert at.table[1].value["Value"].iloc[0] == f"` {evil} `" and at.table[1].value["Column"].iloc[0] == f"` {evil} `"
    assert at.dataframe[0].value.iloc[0, 0] == evil, "a preview is a canvas: shown exactly as it is"


# ── what the model says ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("total, pages", [(0, 1), (1, 1), (50, 1), (51, 2), (120, 3)])
def test_page_count(total, pages):
    assert f.page_count(total) == pages


def test_a_preview_shows_every_value_as_text_and_a_missing_one_as_blank():
    frame = f.preview_frame(["a", "b"], [{"a": 1, "b": 2.5}, {"a": None}, {"a": True, "b": "x"}])

    assert frame.values.tolist() == [["1", "2.5"], ["", ""], ["True", "x"]]


def test_the_notes_under_a_preview_say_what_is_shown_what_failed_and_what_nobody_confirmed():
    plain = f.table_notes({"row_count": 5, "failed_rows": 0})
    both = f.table_notes(
        {"row_count": 5, "failed_rows": 2, "total_rows": 7, "types_provenance": "inferred_unconfirmed"}
    )
    unknown_total = f.table_notes({"row_count": 5, "failed_rows": 2, "total_rows": None})

    assert plain == ["Showing up to 50 rows. The table has 5 rows in all."]
    assert both[1:] == [
        "2 of 7 rows failed validation and weren't imported.",
        "Column types were not confirmed by a person.",
    ]
    assert unknown_total[1] == "2 rows failed validation and weren't imported."


def test_the_picker_tells_two_versions_of_the_same_file_apart():
    v1 = {"file_name": "people.csv", "table_name": "csv_people_v1", "row_count": 30}
    v2 = {"file_name": "people.csv", "table_name": "csv_people_v2", "row_count": 30}

    assert f.file_label(v1) == "people.csv · csv_people_v1 · 30 rows" and f.file_label(v1) != f.file_label(v2)
