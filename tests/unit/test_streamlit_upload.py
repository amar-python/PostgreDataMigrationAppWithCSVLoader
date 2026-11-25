"""The Streamlit upload screen (#255), fast and headless: AppTest runs the real screen against a faked API.

AppTest cannot use `st.file_uploader`, so the screen's `show(files)` is run with the bytes a person would have chosen;
the chooser itself, a real file on a real disk and a real import are in e2e/test_streamlit_upload.py. What is checked here is
what the screen does about each answer: the preview, the mapping, who may send, what is sent, what is said back, and
what must not happen (a re-send, a link built from a cell, "can't reach the API" while the server is importing).

The preview and the files are the real server's: the fake calls api.services.csv_parse.build_preview.
"""

import base64

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.unit.streamlit_harness import APP_DIR, ROLES, errors, later, widget

# The imports below need the path the import above sets up, so the import sort must not move them up.
# isort: split

import api_client  # noqa: E402
import upload_model as u  # noqa: E402
from api.services.csv_parse import build_preview  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# The chooser is emptied by an upload (the generation moves on): the harness stops handing the files over, as the
# real chooser would stop returning them. A test that picks files again says which generation it picked them in.
HARNESS = """
import sys
sys.path.insert(0, {app_dir!r})
import streamlit as st
import auth
from views import upload
if auth.signed_in():
    generation = st.session_state.get(upload.GENERATION, 0)
    files = st.session_state.get("test_files", []) if st.session_state.get("test_files_generation", 0) == generation else []
    upload.show(files)
    upload.report()
"""

PEOPLE = b"id,name,amount\n1,ann,10\n2,bob,20\n3,cy,30\n"
OK = {
    "status": "ok",
    "fileId": "1",
    "tableName": "csv_people_v1",
    "totalRows": 3,
    "insertedRows": 3,
    "duplicateRowsSkipped": 0,
    "failedRows": 0,
    "columns": ["id", "name", "amount"],
    "types": ["int8", "text", "int8"],
    "rowErrors": [],
    "logs": [],
    "dataset": "people",
    "version": 1,
    "schemaCheck": None,
    "duplicateRowsAcrossUploads": 0,
    "uploadId": "5",
}


class FakeApi:
    """Stands in for api_client.request: the preview (the server's real one), the T&E tables, and the upload."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.uploads: list[dict] = []
        self.upload_timeouts: list = []
        self.reply = dict(OK)  # what the next upload answers: a dict, an Exception, or a callable of the payload
        self.te_match: str | None = None
        self.te_tables = [
            {"table": "orgs", "exists": True, "rowCount": 0},
            {"table": "people", "exists": True, "rowCount": 0},
            {"table": "unbuilt", "exists": False, "rowCount": 0},
        ]
        self.dead: set[str] = set()
        self.preview_raises: Exception | None = None

    def __call__(self, method, path, token=None, **kwargs):
        self.calls.append((method, path, token, kwargs.get("json")))
        if token in self.dead:
            raise api_client.Unauthorized(401, "Not signed in")
        if (method, path) == ("POST", "/api/csv/preview"):
            if self.preview_raises:
                raise self.preview_raises
            result = build_preview(kwargs["json"]["content"])
            if result["status"] == "ok":
                result["teTableMatch"] = self.te_match
            return result
        if (method, path) == ("GET", "/api/te/tables"):
            return self.te_tables
        assert (method, path) == ("POST", "/api/csv/upload"), (method, path)
        self.uploads.append(kwargs["json"])
        self.upload_timeouts.append(kwargs.get("timeout"))
        reply = self.reply(kwargs["json"]) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    def previews(self):
        return [c for c in self.calls if c[1] == "/api/csv/preview"]


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


def _screen(api, files, who="alice", token="tok-1") -> AppTest:
    at = AppTest.from_string(HARNESS.format(app_dir=str(APP_DIR)), default_timeout=30)
    at.session_state["session"] = {
        "token": token,
        "expiresAt": later(),
        "username": who,
        "tenant": "acme",
        "role": ROLES[who],
    }
    at.session_state["test_files"] = files
    at.run()
    assert not at.exception, at.exception
    return at


def _confirm(at, key=None):
    box = next(c for c in at.checkbox if c.label == u.CONFIRM)
    box.check().run()
    assert not at.exception, at.exception
    return at


def _upload_button(at, name="people.csv"):
    return widget(at.button, f"Upload ` {name} `")


def _texts(at):
    return [e.value for e in at.markdown] + [e.value for e in at.caption]


# ── the preview ─────────────────────────────────────────────────────────────────────────────


def test_a_chosen_file_is_previewed_by_the_server_and_its_columns_are_offered_for_checking(api):
    at = _screen(api, [("people.csv", PEOPLE)])

    assert [c.value for c in at.caption][0] == "3 columns · 3 data rows"
    sample = at.table[0].value
    assert list(sample.columns) == ["` id `", "` name `", "` amount `"] and list(sample["` name `"]) == [
        "` ann `",
        "` bob `",
        "` cy `",
    ]
    assert [t.label for t in at.text_input] == [
        "Rename column 1 (id)",
        "Rename column 2 (name)",
        "Rename column 3 (amount)",
    ]
    assert [s.label for s in at.selectbox] == [
        "Type of column 1 (id)",
        "Type of column 2 (name)",
        "Type of column 3 (amount)",
    ]
    assert [s.value for s in at.selectbox if s.label.startswith("Type")] == ["int8", "text", "int8"], (
        "the server's inference"
    )
    assert api.previews()[0][3] == {"fileName": "people.csv", "content": PEOPLE.decode()}


def test_the_expander_names_the_file_and_its_size(api):
    at = _screen(api, [("people.csv", PEOPLE)])

    assert at.expander[0].label == f"{u.format_bytes(len(PEOPLE))} · ` people.csv `"


def test_the_preview_is_not_asked_for_again_on_every_click(api):
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)
    widget(at.text_input, "Rename column 1 (id)").input("pid").run()

    assert len(api.previews()) == 1, "the whole script re-runs on every action; the preview must be kept"


def test_a_big_file_is_previewed_from_its_start_and_the_row_count_says_about(api, monkeypatch):
    monkeypatch.setattr(u, "PREVIEW_BYTES", 60)
    raw = b"id,name\n" + b"".join(f"{i},name{i}\n".encode() for i in range(1, 101))

    at = _screen(api, [("big.csv", raw)])

    sent = api.previews()[0][3]["content"]
    assert len(sent.encode()) <= 60 and sent.endswith("\n") and len(sent) < len(raw)
    assert [c.value for c in at.caption][0].startswith("2 columns · about ")


def test_a_file_with_no_data_rows_says_so_in_plain_words_and_offers_nothing_to_send(api):
    at = _screen(api, [("empty.csv", b"id,name\n")])

    assert errors(at) == ["The file has a header row but no data rows."]
    assert not [b for b in at.button if b.label.startswith("Upload")]


def test_a_preview_the_api_refuses_says_why_and_the_other_files_still_show(api):
    api.preview_raises = api_client.ApiError(413, "File too large")

    at = _screen(api, [("people.csv", PEOPLE)])

    assert errors(at) == ["` people.csv `: ` File too large `"]


# ── files the screen will not send ──────────────────────────────────────────────────────────


def test_a_file_that_is_not_utf8_is_refused_with_the_reason_and_nothing_is_sent_for_it(api):
    latin = "name\n\xe9t\xe9\n".encode("latin-1")

    at = _screen(api, [("latin.csv", latin), ("people.csv", PEOPLE)])

    assert errors(at)[0].startswith("` latin.csv ` is not UTF-8 text")
    assert len(api.previews()) == 1 and api.previews()[0][3]["fileName"] == "people.csv", "the good file is still shown"
    assert _upload_button(at) is not None


def test_a_file_over_the_limit_is_refused_before_anything_is_sent(api, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "20")

    at = _screen(api, [("people.csv", PEOPLE)])

    assert "over the 20 B limit" in errors(at)[0] and not api.calls


def test_an_empty_file_and_a_wrong_extension_are_refused(api):
    at = _screen(api, [("empty.csv", b""), ("notes.txt", b"a,b\n")])

    assert errors(at) == [
        "` empty.csv ` is empty.",
        "` notes.txt ` is not a .csv file. Only CSV files can be imported.",
    ]
    assert not api.calls


def test_a_file_name_that_looks_like_a_link_is_quoted_in_the_refusal(api):
    at = _screen(api, [("[x](http://evil.test).txt", b"a")])

    assert errors(at)[0].startswith("` [x](http://evil.test).txt ` is not a .csv")


# ── who may send, and when ──────────────────────────────────────────────────────────────────


def test_a_new_table_cannot_be_sent_until_the_columns_and_types_are_confirmed(api):
    at = _screen(api, [("people.csv", PEOPLE)])

    assert _upload_button(at).disabled
    _confirm(at)

    assert not _upload_button(at).disabled
    assert not api.uploads, "nothing is sent by confirming"


def test_the_no_cancel_wording_is_shown_before_the_click(api):
    at = _screen(api, [("people.csv", PEOPLE)])

    assert "Sent to the server; it can't be stopped now (once you click Upload)." in [c.value for c in at.caption]


# ── what is sent ────────────────────────────────────────────────────────────────────────────


def test_the_click_sends_the_file_the_original_bytes_the_confirmed_types_and_only_the_renames(api):
    at = _screen(api, [("people.csv", PEOPLE)])
    widget(at.text_input, "Rename column 2 (name)").input("who")
    widget(at.selectbox, "Type of column 3 (amount)").select("numeric")
    _confirm(at)

    _upload_button(at).click().run()

    assert not at.exception, at.exception
    [sent] = api.uploads
    assert sent == {
        "fileName": "people.csv",
        "content": PEOPLE.decode(),
        "contentBase64": base64.b64encode(PEOPLE).decode(),
        "mode": "dynamic",
        "types": ["int8", "text", "numeric"],
        "typesConfirmed": True,
        "headerMapping": [{"original": "name", "renamed": "who"}],
    }
    assert api.upload_timeouts == [u.UPLOAD_TIMEOUT_SECONDS], "an import is given far longer than a read"


def test_the_payload_is_built_only_at_the_click_because_encoding_a_big_file_on_every_rerun_is_slow(api, monkeypatch):
    built = []
    real = u.build_payload
    monkeypatch.setattr(u, "build_payload", lambda *a, **k: built.append(1) or real(*a, **k))
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)
    widget(at.text_input, "Rename column 1 (id)").input("pid").run()
    assert not built

    _upload_button(at).click().run()

    assert len(built) == 1


# ── what is said back ───────────────────────────────────────────────────────────────────────


def test_a_successful_import_is_reported_and_the_chooser_is_emptied_so_it_cannot_be_sent_twice(api):
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at).click().run()

    assert at.success[0].value.startswith("` people.csv `: 3 of 3 rows imported")
    assert at.session_state["upload_generation"] == 1
    assert not [b for b in at.button if b.label.startswith("Upload `")], "the file is no longer chosen: no second click"
    assert any("Version 1 of the dataset ` people `." == c.value for c in at.caption)
    assert "Open the Review page to look at the stored rows." in [c.value for c in at.caption]
    assert len(api.uploads) == 1


def test_the_same_file_chosen_again_after_an_import_is_previewed_again_because_the_server_has_moved_on(api):
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)
    _upload_button(at).click().run()
    assert len(api.previews()) == 1

    at.session_state["test_files"] = [("people.csv", PEOPLE)]
    at.session_state["test_files_generation"] = 1
    at.run()

    assert not at.exception, at.exception
    assert len(api.previews()) == 2, "a preview kept from before the import would still say the dataset is new"
    assert _upload_button(at)


def test_a_partial_import_is_a_warning_with_its_row_errors_and_the_reports(api):
    api.reply = {
        **OK,
        "insertedRows": 2,
        "failedRows": 1,
        "rowErrors": [{"rowNumber": 3, "column": "amount", "value": "=1+1", "reason": '"=1+1" is not a whole number'}],
        "logs": [{"ts": 1_795_000_000_000, "step": "cast_rows", "level": "warn", "message": "1 row failed"}],
    }
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at).click().run()

    assert at.warning[0].value.startswith("` people.csv `: 2 of 3 rows imported · 1 failed")
    rows = at.table[-1].value
    assert list(rows.index) == [3] and list(rows["Value"]) == ["` =1+1 `"]
    assert [b.label for b in at.get("download_button")] == [
        "Error report (CSV)",
        "Error report (XLSX)",
        "Processing logs (JSON)",
    ]


def test_the_error_report_carries_the_renames_that_were_sent(api, monkeypatch):
    import exports

    built = []
    real = exports.to_csv
    monkeypatch.setattr(exports, "to_csv", lambda headers, rows: built.append(rows) or real(headers, rows))
    api.reply = {**OK, "failedRows": 1, "rowErrors": [{"rowNumber": 1, "reason": "bad"}]}
    at = _screen(api, [("people.csv", PEOPLE)])
    widget(at.text_input, "Rename column 2 (name)").input("who")
    _confirm(at)

    _upload_button(at).click().run()

    assert built and built[-1][0]["header_mapping"] == "name→who" and built[-1][0]["file"] == "people.csv"


def test_the_same_bytes_again_is_reported_as_already_imported_and_nothing_pretends_it_was_loaded(api):
    api.reply = {
        "status": "duplicate_file",
        "reason": "content",
        "existingFileName": "people.csv",
        "tableName": "csv_people_v1",
        "logs": [],
    }
    at = _screen(api, [("again.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at, "again.csv").click().run()

    assert at.warning[0].value.startswith("` again.csv `: already imported as ` people.csv `. Nothing was changed.")
    assert not at.success


def test_a_failed_import_says_why_in_the_apis_words(api):
    api.reply = {"status": "error", "message": "Provided 2 column types but the CSV has 3 columns.", "logs": []}
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at).click().run()

    assert at.error[0].value.startswith("` people.csv `: ` Provided 2 column types but the CSV has 3 columns. `")


def test_an_api_refusal_of_the_whole_call_is_an_error_not_a_crash(api):
    api.reply = api_client.ApiError(422, "typesConfirmed requires the confirmed types to be sent in 'types'")
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at).click().run()

    assert not at.exception and at.error[0].value.startswith("` people.csv `: ` typesConfirmed requires")


def test_no_answer_in_time_is_not_reported_as_unreachable_or_as_a_failure(api):
    """The server may still be importing. Saying "can't reach the API" would invite a second import of the same file."""
    api.reply = api_client.TimedOut(600)
    at = _screen(api, [("big.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at, "big.csv").click().run()

    assert not at.error and "may still be working" in at.warning[0].value and "Import history" in at.warning[0].value
    assert "Can't reach" not in at.warning[0].value


def test_a_session_the_server_ended_during_an_upload_signs_the_person_out_with_a_reason(api):
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)
    api.dead.add("tok-1")

    _upload_button(at).click().run()

    assert "session" not in at.session_state and at.session_state["notice"].startswith("Your session has ended")
    assert not api.uploads


def test_an_import_clears_the_cached_lists_so_the_new_import_shows_everywhere_at_once(api):
    st.cache_data.clear()
    calls = []

    @st.cache_data
    def cached():
        calls.append(1)
        return "list"

    cached()
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)
    _upload_button(at).click().run()
    cached()

    assert len(calls) == 2, "an import must clear Streamlit's caches (the history, the review picker, the files list)"


def test_the_report_can_be_cleared(api):
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)
    _upload_button(at).click().run()
    assert at.success

    widget(at.button, "Clear this report").click().run()

    assert (
        not at.success
        and not at.warning
        and "upload_results" in at.session_state
        and at.session_state["upload_results"] == []
    )


# ── Test and Evaluation mode ────────────────────────────────────────────────────────────────


def test_a_te_shaped_file_starts_as_a_te_load_into_the_matching_table(api):
    api.te_match = "orgs"

    at = _screen(api, [("orgs.csv", b"name\nacme\n")])

    assert at.radio[0].value == u.TE
    assert widget(at.selectbox, "Into table").value == "orgs" and widget(at.selectbox, "Into table").options == [
        "orgs",
        "people",
    ]
    assert not at.checkbox and not at.text_input, "no mapping and no confirmation in T&E mode"
    assert not _upload_button(at, "orgs.csv").disabled


def test_a_te_load_sends_the_target_and_none_of_what_the_api_refuses_there(api):
    api.te_match = "orgs"
    at = _screen(api, [("orgs.csv", b"name\nacme\n")])

    _upload_button(at, "orgs.csv").click().run()

    [sent] = api.uploads
    assert sent["mode"] == "te" and sent["targetTable"] == "orgs"
    assert not {"types", "typesConfirmed", "headerMapping"} & set(sent)


def test_switching_to_a_new_table_brings_the_mapping_back_and_waits_for_the_confirmation(api):
    api.te_match = "orgs"
    at = _screen(api, [("orgs.csv", b"name\nacme\n")])

    at.radio[0].set_value(u.DYNAMIC).run()

    assert [t.label for t in at.text_input] == ["Rename column 1 (name)"] and _upload_button(at, "orgs.csv").disabled


def test_a_file_with_no_te_match_starts_as_a_new_table(api):
    assert _screen(api, [("people.csv", PEOPLE)]).radio[0].value == u.DYNAMIC


def test_a_te_load_with_no_te_tables_says_so_and_cannot_be_sent(api):
    api.te_match = None
    api.te_tables = []
    at = _screen(api, [("people.csv", PEOPLE)])

    at.radio[0].set_value(u.TE).run()

    assert [w.value for w in at.warning] == ["There are no Test and Evaluation tables to load into."]
    assert _upload_button(at).disabled


# ── several files ───────────────────────────────────────────────────────────────────────────


def test_upload_all_waits_for_every_file_to_be_confirmed_then_sends_them_in_turn(api):
    other = b"city,pop\nperth,2\n"
    at = _screen(api, [("people.csv", PEOPLE), ("cities.csv", other)])
    upload_all = widget(at.button, "Upload all")
    assert upload_all.disabled
    [c for c in at.checkbox if c.label == u.CONFIRM][0].check().run()
    assert widget(at.button, "Upload all").disabled, "one of two confirmed is not enough"
    [c for c in at.checkbox if c.label == u.CONFIRM][1].check().run()

    widget(at.button, "Upload all").click().run()

    assert not at.exception, at.exception
    assert [x["fileName"] for x in api.uploads] == ["people.csv", "cities.csv"]
    assert [r.value.split("  \n")[0] for r in at.success] == [
        "` cities.csv `: 3 of 3 rows imported",
        "` people.csv `: 3 of 3 rows imported",
    ], "newest first"


def test_one_file_failing_does_not_stop_the_rest(api):
    api.reply = lambda payload: (
        {"status": "error", "message": "boom", "logs": []} if payload["fileName"] == "bad.csv" else dict(OK)
    )
    at = _screen(api, [("bad.csv", PEOPLE), ("good.csv", b"city,pop\nperth,2\n")])
    for box in [c for c in at.checkbox if c.label == u.CONFIRM]:
        box.check().run()

    widget(at.button, "Upload all").click().run()

    assert [x["fileName"] for x in api.uploads] == ["bad.csv", "good.csv"]
    assert len(at.error) == 1 and len(at.success) == 1


def test_two_copies_of_the_same_bytes_under_two_names_are_two_files_with_their_own_widgets(api):
    """Found by this test: widget keys were made from the content alone, so two copies crashed the page."""
    at = _screen(api, [("orig.csv", PEOPLE), ("copy.csv", PEOPLE)])

    assert len(at.expander) == 2 and len(at.checkbox) == 2 and len(api.previews()) == 1, (
        "one preview, two sets of boxes"
    )
    assert [b.label for b in at.button if b.label.startswith("Upload `")] == [
        "Upload ` orig.csv `",
        "Upload ` copy.csv `",
    ]


def test_the_same_file_chosen_twice_is_shown_once_and_says_so(api):
    at = _screen(api, [("a.csv", PEOPLE), ("a.csv", PEOPLE)])

    assert len(at.expander) == 1 and "` a.csv ` was chosen twice; it is shown once." in [c.value for c in at.caption]


# ── who may use the page ────────────────────────────────────────────────────────────────────


def test_the_page_itself_is_only_for_roles_that_may_upload():
    from api.auth import PERMISSIONS

    assert {r for r, role in ROLES.items() if role in PERMISSIONS["upload"]} == {"alice", "ada"}


def test_a_role_that_may_not_upload_is_told_so_instead_of_being_shown_a_chooser(api):
    at = AppTest.from_string(
        f"""
import sys
sys.path.insert(0, {str(APP_DIR)!r})
import auth
from views import upload
if auth.signed_in():
    upload.render()
""",
        default_timeout=30,
    )
    at.session_state["session"] = {
        "token": "t",
        "expiresAt": later(),
        "username": "audrey",
        "tenant": "acme",
        "role": "auditor",
    }

    at.run()

    assert not at.exception and [i.value for i in at.info] == ["The role auditor can't upload files."]


# ── text from a file is shown as written ───────────────────────────────────────────────────


def test_headers_cells_and_the_file_name_that_look_like_links_are_code_spans_everywhere(api):
    evil = "[click](https://evil.example/x)"
    raw = f"{evil},b\n{evil},2\n".encode()

    at = _screen(api, [(f"{evil}.csv", raw)])

    assert at.expander[0].label.endswith(f"` {evil}.csv `")
    sample = at.table[0].value
    assert list(sample.columns)[0].startswith("`") and sample.iloc[0, 0] == f"` {evil} `"
    assert any(m.value == f"` {evil} `" for m in at.markdown), "the header, beside its rename box"
    assert _upload_button(at, f"{evil}.csv") is not None


def test_a_row_error_with_a_link_in_it_is_a_code_span(api):
    evil = "[click](https://evil.example/x)"
    api.reply = {
        **OK,
        "failedRows": 1,
        "rowErrors": [{"rowNumber": 1, "column": "a", "value": evil, "reason": f'"{evil}" bad'}],
    }
    at = _screen(api, [("people.csv", PEOPLE)])
    _confirm(at)

    _upload_button(at).click().run()

    assert at.table[-1].value["Value"].iloc[0] == f"` {evil} `"


def test_a_column_called_the_same_after_cleaning_gets_its_own_boxes(api):
    at = _screen(api, [("a.csv", b"My Col,my col\n1,2\n")])

    assert [t.label for t in at.text_input] == ["Rename column 1 (My Col)", "Rename column 2 (my col)"]


def test_the_labels_of_the_boxes_cannot_be_read_as_markdown_because_a_label_is_markdown_even_when_hidden(api):
    evil = "[click](https://evil.example/x)"

    at = _screen(api, [("a.csv", f"{evil},b\n1,2\n".encode())])

    assert [t.label for t in at.text_input][0] == "Rename column 1 (click https evil example x)"
    assert [s.label for s in at.selectbox][0] == "Type of column 1 (click https evil example x)"
