"""The Streamlit review screen (#252), fast and headless: Streamlit's AppTest runs the real screen against a
faked API, so no server, browser or database is needed.

These are the cases the React screen's tests check (csv-table-hub-main/src/__tests__/review-table.test.tsx:
every row with its validation, edits and decision; exclude with a required reason; edit as a new value with a
reason; other roles can view but not change) and the ones its newer fixes added (#187 every attempt listed,
#190 the database's reason for a rejected row), plus what is particular to Streamlit: text from a file must not
be read as Markdown, the cached list of uploads must not leak between sessions, and the row-number box must
survive a change of page. AppTest cannot click a row in the grid; e2e/test_streamlit_review.py does.
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "streamlit_app"
sys.path.insert(0, str(APP_DIR))

import api_client  # noqa: E402
import review_model as m  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# The screen as app.py shows it: only to someone signed in. AppTest cannot switch to st.navigation pages.
HARNESS = """
import sys
sys.path.insert(0, {app_dir!r})
import auth
from views import review
if auth.signed_in():
    review.render()
"""

ROLES = {"rita": "reviewer", "ada": "tenant_admin", "alice": "uploader", "audrey": "auditor"}


def _later() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()


def _row(n, cells, **extra):
    return {"rowNumber": n, "original": list(cells), "current": list(cells), "editedColumns": [],
            "decision": "include", "decisionReason": None, "duplicateOfEarlierVersion": None, "errors": [], **extra}


def _people() -> list[dict]:
    """The React test's three rows: one edited, one invalid, one excluded that the database rejected (#190)."""
    return [
        _row(1, ["1", "a"], current=["10", "a"], editedColumns=[0]),
        _row(2, ["x", "b"], errors=[{"column": "n", "value": "x", "reason": '"x" is not a whole number'}]),
        _row(3, ["3", "c"], decision="exclude", decisionReason="duplicate of row 1",
             errors=[{"column": "(database)", "value": "", "reason": "violates check constraint"}]),
    ]


def _attempt(uid, name, status, total=3, failed=0, **extra):
    return {"id": uid, "file_name": name, "mode": "dynamic", "status": status, "total_rows": total,
            "imported_rows": (total or 0) - failed, "failed_rows": failed, "uploader": "alice",
            "uploaded_at": "2026-11-18T01:00:00+00:00", "failure_reason": None, **extra}


UPLOADS = [  # newest first, as the API lists them; "7" is the one with rows to look at
    _attempt("7", "people.csv", "imported"),
    _attempt("8", "bad.csv", "failed", total=5, failed=5, failure_reason="every row failed"),
    _attempt("9", "half.csv", "partly_imported", total=10, failed=4),
    _attempt("10", "nope.csv", "rejected", total=None, failure_reason="Not a CSV file"),
    _attempt("11", "same.csv", "duplicate"),
]


class FakeApi:
    """Stands in for api_client.request: the list of uploads and the review endpoints, with the API's own wording."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.uploads = [dict(u) for u in UPLOADS]
        self.data = {u["id"]: {"columns": ["n", "t"], "types": ["int8", "text"], "rows": _people()} for u in UPLOADS}
        self.history: dict[tuple, list] = {}
        self.dead: set[str] = set()
        self.frozen: set[str] = set()
        self.down = False
        self.expire_on_write = False  # the session is ended by the time a change arrives, though reads still work
        self.lists_by_token: dict[str, list] = {}

    def __call__(self, method, path, token=None, **kwargs):
        self.calls.append((method, path, token, kwargs.get("json"), kwargs.get("params")))
        if self.down:
            raise api_client.Unreachable()
        if token in self.dead or (self.expire_on_write and method == "PUT"):
            raise api_client.Unauthorized(401, "Not signed in")
        if (method, path) == ("GET", "/api/csv/uploads"):
            return self.lists_by_token.get(token, self.uploads)
        found = re.fullmatch(r"/api/csv/uploads/(\d+)/rows(?:/(\d+)/(history|decision|cells/(\d+)))?", path)
        assert found, f"unexpected call {method} {path}"
        uid, n, what = found.group(1), found.group(2), found.group(3)
        if what is None:
            return self._page(uid, **kwargs["params"])
        if what == "history":
            return self.history.get((uid, int(n)), [])
        return self._change(uid, int(n), what, kwargs["json"])

    def _page(self, uid, offset, limit):
        d = self.data[uid]
        rows = d["rows"][offset:offset + limit]
        return {"fileName": next(u["file_name"] for u in self.uploads if u["id"] == uid), "columns": d["columns"],
                "types": d["types"], "total": len(d["rows"]), "offset": offset, "limit": limit,
                "excludedRows": sum(r["decision"] == "exclude" for r in d["rows"]),
                "editedRows": sum(bool(r["editedColumns"]) for r in d["rows"]), "rows": rows}

    def _change(self, uid, n, what, body):
        if uid in self.frozen:
            raise api_client.ApiError(409, "This upload is approved, so its rows can no longer be changed")
        if not body["reason"].strip():
            raise api_client.ApiError(422, "A reason is required")
        row = self.data[uid]["rows"][n - 1]
        at = "2026-11-18T02:30:00+00:00"
        if what == "decision":
            row["decision"], row["decisionReason"] = body["decision"], body["reason"]
            self.history.setdefault((uid, n), []).append(
                {"kind": "decision", "at": at, "actor": "rita", "reason": body["reason"], "decision": body["decision"]})
        else:
            i = int(what.split("/")[1])
            if body["value"] == row["current"][i]:
                raise api_client.ApiError(422, "The new value is the same as the current one")
            self.history.setdefault((uid, n), []).append(
                {"kind": "edit", "at": at, "actor": "rita", "reason": body["reason"],
                 "column": self.data[uid]["columns"][i], "oldValue": row["current"][i], "newValue": body["value"]})
            row["current"][i] = body["value"]
            row["editedColumns"] = sorted({*row["editedColumns"], i})
        return row

    def writes(self):
        return [c for c in self.calls if c[0] == "PUT"]

    def list_calls(self):
        return [c for c in self.calls if c[:2] == ("GET", "/api/csv/uploads")]

    def row_pages(self):
        return [c for c in self.calls if c[0] == "GET" and c[1].endswith("/rows")]


@pytest.fixture(autouse=True)
def clean_cache():
    st.cache_data.clear()  # the list of uploads is cached in the process; a test must not see another's
    yield
    st.cache_data.clear()


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(api_client, "request", fake)
    return fake


def _screen(api, who="rita", token="tok-1") -> AppTest:
    """The review screen with a session already in place."""
    at = AppTest.from_string(HARNESS.format(app_dir=str(APP_DIR)), default_timeout=30)
    at.session_state["session"] = {"token": token, "expiresAt": _later(), "username": who, "tenant": "acme",
                                   "role": ROLES[who]}
    at.run()
    assert not at.exception, at.exception
    return at


def _upload_box(at):
    return next(s for s in at.selectbox if s.label == "Upload")


def _pick_upload(at, uid):
    _upload_box(at).select(uid).run()
    assert not at.exception, at.exception
    return at


def _row_box(at):
    return next(n for n in at.number_input if n.label == "Row number")


def _choose_row(at, n):
    _row_box(at).set_value(n).run()
    assert not at.exception, at.exception
    return at


def _widget(elements, label):
    return next(e for e in elements if e.label == label)


def _review(at, uid="7", row=None):
    _pick_upload(at, uid)
    return _choose_row(at, row) if row else at


def _errors(at):
    return [e.value for e in at.error]


def _refusals(at):
    """The errors that are not the row's own validation problems (those start with the column name, in code)."""
    return [e for e in _errors(at) if not e.startswith("`")]


def _texts(at):
    return [e.value for e in at.markdown] + [e.value for e in at.caption] + [e.value for e in at.info]


# ── which upload: every attempt, #187 ─────────────────────────────────────────────────────────

def test_every_attempt_is_listed_failed_and_partial_ones_included(api):
    at = _screen(api)

    options = _upload_box(at).options
    assert options == ["#7 people.csv · Imported · 3 rows",
                       "#8 bad.csv · Failed · 5 of 5 rows failed",
                       "#9 half.csv · Partly imported · 4 of 10 rows failed",
                       "#10 nope.csv · Rejected · 0 rows",
                       "#11 same.csv · Duplicate · 3 rows"]


def test_the_failed_or_partial_filter_leaves_the_ones_that_need_attention(api):
    at = _screen(api)

    _widget(at.checkbox, "Only failed or partly failed uploads").check().run()

    assert [o.split(" · ")[1] for o in _upload_box(at).options] == ["Failed", "Partly imported", "Rejected"]


def test_a_filter_with_nothing_left_says_so_and_a_tenant_with_no_uploads_says_that(api):
    api.uploads = [_attempt("7", "people.csv", "imported")]
    at = _screen(api)
    _widget(at.checkbox, "Only failed or partly failed uploads").check().run()
    assert [i.value for i in at.info] == ["No failed or partly failed uploads."]

    api.uploads = []
    st.cache_data.clear()
    assert [i.value for i in _screen(api).info] == ["No uploads yet."]


def test_a_rejected_file_has_no_rows_to_review_and_none_are_asked_for(api):
    at = _pick_upload(_screen(api), "10")

    assert "rejected, so no rows were stored" in at.info[0].value
    assert [c.value for c in at.caption if c.value.startswith("Why")] == ["Why: ` Not a CSV file `"]
    assert not at.dataframe
    assert not [c for c in api.row_pages() if "/uploads/10/" in c[1]], "no rows are asked for a rejected file"


def test_the_chosen_upload_stays_chosen_when_the_list_changes_under_it(api):
    at = _pick_upload(_screen(api), "9")
    assert at.subheader[0].value == "` half.csv `"
    api.uploads = [_attempt("12", "new.csv", "imported"), *api.uploads]
    api.data["12"] = api.data["9"]

    _widget(at.button, "Refresh the list").click().run()

    assert _upload_box(at).value == "9", "a new upload at the top must not move the reviewer to it"


# ── every row, with its validation, edits and decision ─────────────────────────────────────────

def test_the_page_shows_every_row_with_its_status_and_the_count_line(api):
    at = _pick_upload(_screen(api), "7")

    frame = at.dataframe[0].value
    assert list(frame.index) == [1, 2, 3]
    assert list(frame["Row status"]) == ["Included", "Invalid", "Excluded"]
    assert list(frame["n"]) == ["10", "x", "3"], "the current values, so the edit shows"
    assert at.subheader[0].value == "` people.csv `"
    assert at.caption[0].value == ("3 rows · 1 excluded · 1 edited. Changes are saved with the upload for review. "
                                   "They don't change the imported table.")


def test_a_row_shows_why_it_is_invalid_what_was_edited_and_the_decision_and_the_database_reason(api):
    at = _review(_screen(api), row=2)
    assert at.subheader[1].value == "Row 2"
    assert _errors(at) == ['` n `: ` "x" is not a whole number `']

    at = _choose_row(at, 1)
    assert _errors(at) == []
    assert any("` n `: original ` 1 `, now ` 10 `" == c.value for c in at.caption)

    at = _choose_row(at, 3)
    assert _errors(at) == ["` (database) `: ` violates check constraint `"], "#190: the database's reason"
    assert [i.value for i in at.info] == ["Decision: **exclude**: ` duplicate of row 1 `"]


def test_no_row_is_shown_until_one_is_chosen(api):
    at = _pick_upload(_screen(api), "7")

    assert _row_box(at).value is None
    assert not at.tabs and not _errors(at)
    assert any("Select a row in the table, or type its number" in c.value for c in at.caption)


# ── a reviewer excludes a row with a required reason ───────────────────────────────────────────

def test_excluding_needs_a_reason_and_sends_the_row_the_decision_and_the_reason(api):
    at = _review(_screen(api), row=2)
    assert [t.label for t in at.tabs] == ["Edit a cell", "Exclude row", "History"]

    _widget(at.button, "Exclude this row").click().run()
    assert _refusals(at) == ["A reason is required"] and not api.writes(), "refused before anything is sent"

    _widget(at.text_input, "Reason to exclude this row (required)").input("bad row")
    _widget(at.button, "Exclude this row").click().run()

    assert not at.exception, at.exception
    assert [(c[0], c[1], c[3]) for c in api.writes()] == [
        ("PUT", "/api/csv/uploads/7/rows/2/decision", {"decision": "exclude", "reason": "bad row"})]
    assert [s.value for s in at.success] == ["Saved: row 2 excluded."]
    assert list(at.dataframe[0].value["Row status"]) == ["Included", "Excluded", "Excluded"]
    assert _widget(at.text_input, "Reason to include this row (required)").value == "", "the form starts empty again"
    assert "Include row" in [t.label for t in at.tabs], "the next decision on this row is to include it"


def test_a_whitespace_only_reason_is_refused_too(api):
    at = _review(_screen(api), row=2)

    _widget(at.text_input, "Reason to exclude this row (required)").input("   ")
    _widget(at.button, "Exclude this row").click().run()

    assert _refusals(at) == ["A reason is required"] and not api.writes()


# ── a reviewer edits a cell as a new value with a reason ───────────────────────────────────────

def test_editing_shows_the_original_and_sends_the_new_value_and_reason_by_column_position(api):
    at = _review(_screen(api), row=2)

    _widget(at.selectbox, "Column").select(0).run()
    assert any(c.value == "Original value: ` x ` · Current value: ` x `" for c in at.caption)
    _widget(at.text_input, "New value").input("2")
    _widget(at.text_input, "Reason for the change (required)").input("typo")
    _widget(at.button, "Save").click().run()

    assert not at.exception, at.exception
    assert [(c[1], c[3]) for c in api.writes()] == [
        ("/api/csv/uploads/7/rows/2/cells/0", {"value": "2", "reason": "typo"})]
    assert [s.value for s in at.success] == ["Saved: row 2, ` n `."]
    assert list(at.dataframe[0].value["n"]) == ["10", "2", "3"]
    assert any(c.value == "` n `: original ` x `, now ` 2 `" for c in at.caption)
    assert at.subheader[1].value == "Row 2", "the same row stays chosen"


def test_an_edit_with_no_reason_is_refused_before_it_is_sent(api):
    at = _review(_screen(api), row=2)

    _widget(at.text_input, "New value").input("2")
    _widget(at.button, "Save").click().run()

    assert _refusals(at) == ["A reason is required"] and not api.writes()


def test_the_apis_own_refusal_is_shown_and_nothing_pretends_it_was_saved(api):
    at = _review(_screen(api), row=2)
    _widget(at.text_input, "New value").input("x")  # the same as now: the API says no
    _widget(at.text_input, "Reason for the change (required)").input("same")
    _widget(at.button, "Save").click().run()
    assert _refusals(at) == ["The new value is the same as the current one"] and not at.success

    api.frozen.add("7")  # approved meanwhile
    _widget(at.text_input, "New value").input("2")
    _widget(at.button, "Save").click().run()
    assert _refusals(at) == ["This upload is approved, so its rows can no longer be changed"] and not at.success


def test_the_history_tab_lists_what_was_changed_by_whom_and_why(api):
    at = _review(_screen(api), row=2)
    assert any(w.value == "No changes yet." for w in at.markdown)

    _widget(at.text_input, "Reason to exclude this row (required)").input("duplicate")
    _widget(at.button, "Exclude this row").click().run()

    history = [w.value for w in at.markdown if "rita" in w.value]
    assert history == ["2026-11-18 02:30 UTC · ` rita ` · **Excluded**  \n` duplicate `"]


# ── other roles can view but not change ────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["alice", "audrey"])
def test_other_roles_can_look_but_not_change(api, who):
    at = _review(_screen(api, who), row=2)

    assert any("Only reviewers and tenant admins can make changes." in c.value for c in at.caption)
    assert not at.tabs and not at.button[1:], "no edit or decision control, only the list's own refresh button"
    assert [b.label for b in at.button] == ["Refresh the list"]
    assert _errors(at) == ['` n `: ` "x" is not a whole number `']
    assert any(c[1].endswith("/2/history") for c in api.calls), "the history can still be read"


def test_a_tenant_admin_can_change_too(api):
    at = _review(_screen(api, "ada"), row=2)

    assert [t.label for t in at.tabs] == ["Edit a cell", "Exclude row", "History"]


# ── a session the server has ended, or a server that is down ───────────────────────────────────

def test_a_session_the_server_ended_during_a_save_signs_the_person_out_with_a_reason(api):
    at = _review(_screen(api), row=2)
    api.expire_on_write = True

    _widget(at.text_input, "Reason to exclude this row (required)").input("bad row")
    _widget(at.button, "Exclude this row").click().run()

    assert "session" not in at.session_state
    assert at.session_state["notice"] == "Your session has ended. Sign in again."
    assert [(c[1], c[2]) for c in api.writes()] == [("/api/csv/uploads/7/rows/2/decision", "tok-1")]


def test_a_session_the_server_ended_before_the_list_loads_does_the_same(api):
    api.dead.add("tok-1")

    at = _screen(api)

    assert "session" not in at.session_state and at.session_state["notice"].startswith("Your session has ended")


def test_an_api_that_is_down_says_so_instead_of_failing(api):
    api.down = True

    at = AppTest.from_string(HARNESS.format(app_dir=str(APP_DIR)), default_timeout=30)
    at.session_state["session"] = {"token": "t", "expiresAt": _later(), "username": "rita", "tenant": "acme",
                                   "role": "reviewer"}
    at.run()

    assert not at.exception and "Can't reach the API" in _errors(at)[0]


# ── the list of uploads is cached, and never shared between sessions ───────────────────────────

def test_the_list_is_fetched_once_for_many_reruns_and_again_on_refresh(api):
    at = _pick_upload(_screen(api), "7")
    _choose_row(at, 2)
    _choose_row(at, 3)
    assert len(api.list_calls()) == 1

    _widget(at.button, "Refresh the list").click().run()

    assert len(api.list_calls()) == 2


def test_one_sessions_list_is_never_shown_to_another(api):
    api.lists_by_token = {"tok-a": [_attempt("1", "acme-secret.csv", "imported")],
                          "tok-b": [_attempt("2", "zed-plans.csv", "imported")]}
    api.uploads += api.lists_by_token["tok-a"] + api.lists_by_token["tok-b"]  # so the fake can serve their rows
    api.data["1"] = api.data["2"] = api.data["7"]

    a = _screen(api, "rita", "tok-a")
    b = _screen(api, "ada", "tok-b")

    assert _upload_box(a).options == ["#1 acme-secret.csv · Imported · 3 rows"]
    assert _upload_box(b).options == ["#2 zed-plans.csv · Imported · 3 rows"]
    assert {c[2] for c in api.list_calls()} == {"tok-a", "tok-b"}, "each session asked for its own"


def test_the_rows_are_never_cached_because_they_change_as_people_review(api):
    at = _review(_screen(api), row=2)
    before = len(api.row_pages())

    _widget(at.text_input, "Reason to exclude this row (required)").input("bad row")
    _widget(at.button, "Exclude this row").click().run()

    assert len(api.row_pages()) > before


# ── text from a file is shown as written ───────────────────────────────────────────────────────

def test_a_cell_that_looks_like_a_link_or_bold_text_shows_as_written(api):
    evil = '[click here](https://evil.example/login) **urgent** :warning: $x$ <b>hi</b> user@evil.example'
    api.data["7"]["rows"][1]["errors"] = [{"column": "n", "value": evil, "reason": f'"{evil}" is not a whole number'}]
    api.data["7"]["rows"][1]["original"][1] = evil
    api.data["7"]["rows"][1]["current"][1] = evil
    at = _review(_screen(api), row=2)

    # Every piece of the file's text is inside a code span, which Markdown shows as written. (Escaping its
    # punctuation instead still left the URL a link in a browser: e2e/test_streamlit_review.py.)
    assert _errors(at) == [f'` n `: ` "{evil}" is not a whole number `']
    _widget(at.selectbox, "Column").select(1).run()
    assert any(c.value == f"Original value: ` {evil} ` · Current value: ` {evil} `" for c in at.caption)


def test_a_file_name_and_a_reason_in_the_history_show_as_written(api):
    api.uploads[0]["file_name"] = "[a](https://evil.example)**.csv"
    api.history[("7", 2)] = [{"kind": "decision", "at": "2026-11-18T02:30:00+00:00", "actor": "r[x](y)",
                              "reason": "see https://evil.example now", "decision": "exclude"}]
    at = _review(_screen(api), row=2)

    assert at.subheader[0].value == "` [a](https://evil.example)**.csv `"
    assert [w.value for w in at.markdown if "UTC" in w.value] == [
        "2026-11-18 02:30 UTC · ` r[x](y) ` · **Excluded**  \n` see https://evil.example now `"]


def test_a_file_with_a_column_called_status_does_not_clash_with_the_status_column(api):
    api.data["7"]["columns"] = ["status", "Row status"]

    at = _review(_screen(api))

    assert list(at.dataframe[0].value.columns) == ["Row status (2)", "status", "Row status"]


# ── pages ──────────────────────────────────────────────────────────────────────────────────────

def _big(api, total=250):
    api.data["7"]["rows"] = [_row(i, [str(i), f"p{i}"]) for i in range(1, total + 1)]
    api.uploads[0]["total_rows"] = total


def test_each_page_asks_for_its_own_hundred_rows(api):
    _big(api)
    at = _pick_upload(_screen(api), "7")
    assert [r.value for r in at.number_input if r.label.startswith("Page")] == [1]
    assert api.row_pages()[-1][4] == {"offset": 0, "limit": 100}

    _widget(at.number_input, "Page (of 3)").set_value(3).run()

    assert not at.exception
    assert api.row_pages()[-1][4] == {"offset": 200, "limit": 100}
    assert list(at.dataframe[0].value.index) == list(range(201, 251))


def test_a_row_number_left_over_from_another_page_starts_the_box_empty_not_a_crash(api):
    _big(api)
    at = _review(_screen(api), row=5)
    assert at.subheader[1].value == "Row 5"

    _widget(at.number_input, "Page (of 3)").set_value(2).run()

    assert not at.exception, at.exception
    assert _row_box(at).value is None and _row_box(at).min == 101 and _row_box(at).max == 200


def test_a_row_chosen_on_a_later_page_is_shown_with_its_own_data(api):
    _big(api)
    at = _pick_upload(_screen(api), "7")
    _widget(at.number_input, "Page (of 3)").set_value(2).run()

    _choose_row(at, 150)

    assert at.subheader[1].value == "Row 150"
    _widget(at.text_input, "Reason to exclude this row (required)").input("later")
    _widget(at.button, "Exclude this row").click().run()
    assert api.writes()[-1][1] == "/api/csv/uploads/7/rows/150/decision"


# ── what the model says ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, shown", [
    ("[a](b)", "` [a](b) `"),
    ("**x**_y_", "` **x**_y_ `"),
    ("https://evil.example/x www.evil.example a@evil.example", "` https://evil.example/x www.evil.example a@evil.example `"),
    ("a`b", "`` a`b ``"),
    ("``", "``` `` ```"),
    ("`", "`` ` ``"),
    ("a\r\nb\tc", "` a b c `"),
    ("", "`  `"),
    (None, "` None `"),
    (5, "` 5 `"),
])
def test_literal_puts_text_in_a_code_span_that_nothing_inside_it_can_end(text, shown):
    assert m.literal(text) == shown


@pytest.mark.parametrize("text", ["plain", "a`b", "``", "`", "```x```", "x`", "`x", "a ` b `` c ``` d", "  spaced  "])
def test_a_literal_is_one_code_span_holding_exactly_the_text(text):
    """The CommonMark rule for a code span: a fence of N backticks ends at the next run of exactly N, so the
    fence must be longer than any run inside, and a single space of padding at each end is not shown."""
    import re
    span = m.literal(text)
    fence = re.match(r"`+", span).group()
    inner = span[len(fence):-len(fence)]
    assert span.endswith(fence) and not span.endswith("`" * (len(fence) + 1))
    assert all(len(run) != len(fence) for run in re.findall(r"`+", inner)), "nothing inside can close the span early"
    assert inner[1:-1] == text, "what is shown is what was in the file"


def test_needs_attention_is_failed_partial_and_rejected_only():
    assert all(m.needs_attention(s) for s in ("failed", "partly_imported", "rejected"))
    assert not any(m.needs_attention(s) for s in ("imported", "duplicate"))


def test_attempt_wording_matches_the_react_list():
    assert m.attempt_label(_attempt("1", "a.csv", "imported", total=3)) == "#1 a.csv · Imported · 3 rows"
    assert m.attempt_label(_attempt("1", "a.csv", "partly_imported", total=10, failed=2)).endswith(
        "Partly imported · 2 of 10 rows failed")
    assert m.attempt_label(_attempt("1", "a.csv", "failed", total=None, failed=2)).endswith("2 of ? rows failed")
    assert m.attempt_label(_attempt("1", "a.csv", "mystery", total=0)).endswith("mystery · 0 rows")
    assert m.reviewable(_attempt("1", "a", "failed")) and not m.reviewable(_attempt("1", "a", "rejected"))


@pytest.mark.parametrize("total, pages", [(0, 1), (1, 1), (100, 1), (101, 2), (250, 3), (1000, 10)])
def test_page_count(total, pages):
    assert m.page_count(total) == pages


def test_status_column_avoids_every_name_the_file_has():
    assert m.status_column(["a"]) == "Row status"
    assert m.status_column(["Row status"]) == "Row status (2)"
    assert m.status_column(["Row status", "Row status (2)"]) == "Row status (3)"


def test_tint_marks_edited_cells_blue_error_cells_red_and_excluded_rows_grey():
    rows = _people()
    columns = ["n", "t"]
    frame = m.grid_frame(rows, columns, "Row status")

    out = m.tint(rows, frame, columns)

    assert out.loc[1, "n"] == m.EDITED_TINT and out.loc[1, "t"] == ""
    assert out.loc[2, "n"] == m.ERROR_TINT
    assert out.loc[3, "t"] == m.EXCLUDED_TEXT, "an excluded row is grey"
    assert out.loc[3, "n"] == m.EXCLUDED_TEXT, "the database's reason has no column, so it tints none"


def test_the_error_that_belongs_to_no_column_is_named_so_a_cell_beyond_the_header_too():
    row = _row(1, ["a"], errors=[{"column": "(beyond header)", "value": "z", "reason": "1 cell beyond the header"}])
    assert m.error_lines(row) == ["` (beyond header) `: ` 1 cell beyond the header `"]


def test_when_gives_utc_takes_a_zoneless_time_as_utc_and_survives_rubbish():
    assert m.when("2026-11-18T12:30:45+10:00") == "2026-11-18 02:30 UTC"
    assert m.when("2026-11-18T02:30:45") == "2026-11-18 02:30 UTC"
    assert m.when("not a time") == "` not a time `"
    assert m.when(None) == "` None `"


def test_a_history_edit_line_shows_both_values_and_an_unknown_actor():
    line = m.history_line({"kind": "edit", "at": "2026-11-18T02:30:00+00:00", "actor": None, "reason": "typo",
                           "column": "n", "oldValue": "x", "newValue": "2"})
    assert line == "2026-11-18 02:30 UTC · ` unknown ` · ` n `: ` x ` → ` 2 `  \n` typo `"
