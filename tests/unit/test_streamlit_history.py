"""The Streamlit import-history screen (#253), fast and headless: AppTest runs the real screen against a faked API.

The React screen's tests (audit-filters.test.ts, upload-attempts.test.tsx, stored-row-errors.test.tsx,
audit-events.test.ts) check: filters by file name, status and date range (the whole "to" day included); the
stored reasons a failed import shows and the note when none were kept; and the server's audit events with
their filters. Those are here, against the server's own list, plus what the move to the server brings: the
list belongs to the tenant, so it must never be shared between sessions, and file text must not become a link.
"""

import re
from datetime import date, datetime, timedelta, timezone

import pytest
import streamlit as st

from tests.unit.streamlit_harness import errors, screen, widget

# The imports below need the path the import above sets up, so the import sort must not move them up.
# isort: split

import api_client  # noqa: E402
import history_model as h  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

T0 = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)


def _upload(
    n, name="people.csv", status="imported", total=30, failed=0, uploader="alice", mode="dynamic", reason=None, at=None
):
    return {
        "id": str(n),
        "file_name": name,
        "sha256": "ab" * 32,
        "byte_size": 100,
        "uploader": uploader,
        "mode": mode,
        "status": status,
        "total_rows": total,
        "imported_rows": (total or 0) - failed,
        "failed_rows": failed,
        "csv_file_id": None,
        "uploaded_at": (at or T0 - timedelta(hours=n)).isoformat(),
        "failure_reason": reason,
        "state": "imported",
    }


class FakeApi:
    """Stands in for api_client.request and .download: the list, one import's detail and the audit events, with
    the server's own filtering (the API does the filtering; the screen only asks)."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.uploads = [_upload(i) for i in range(1, 4)]  # newest first: ids 1, 2, 3 by age
        self.details: dict[str, dict] = {}
        self.events: list[dict] = []
        self.classification = "OFFICIAL: Sensitive"
        self.dead: set[str] = set()
        self.down = False
        self.lists_by_token: dict[str, list] = {}
        self.csv = b"id,action\n1,upload\n"

    def _guard(self, token):
        if self.down:
            raise api_client.Unreachable()
        if token in self.dead:
            raise api_client.Unauthorized(401, "Not signed in")

    def __call__(self, method, path, token=None, **kwargs):
        self.calls.append((method, path, token, kwargs.get("params")))
        self._guard(token)
        params = kwargs.get("params") or {}
        if path == "/api/csv/uploads":
            return self._list(self.lists_by_token.get(token, self.uploads), params)
        if path == "/api/audit/events":
            return self._events(params)
        found = re.fullmatch(r"/api/csv/uploads/(\d+)", path)
        assert found, f"unexpected call {method} {path}"
        return self.details.get(found.group(1)) or self._default_detail(found.group(1))

    def download(self, method, path, token=None, **kwargs):
        self.calls.append((method, path, token, kwargs.get("params")))
        self._guard(token)
        assert path == "/api/audit/events", path
        return self.csv, {"X-Total-Count": "1"}

    def _default_detail(self, uid):
        u = next(u for u in self.uploads if u["id"] == uid)
        return {
            "id": uid,
            "fileName": u["file_name"],
            "status": u["status"],
            "totalRows": u["total_rows"],
            "importedRows": u["imported_rows"],
            "failedRows": u["failed_rows"],
            "rowErrors": [],
            "logs": [],
            "uploader": u["uploader"],
            "state": u["state"],
        }

    @staticmethod
    def _when(text):
        return datetime.fromisoformat(text)

    def _list(self, uploads, p):
        out = []
        for u in uploads:
            if "file" in p and p["file"].lower() not in u["file_name"].lower():
                continue
            if "status" in p and u["status"] != p["status"]:
                continue
            if "uploader" in p and u["uploader"] != p["uploader"]:
                continue
            if "from" in p and self._when(u["uploaded_at"]) < self._when(p["from"]):
                continue
            if "to" in p and self._when(u["uploaded_at"]) >= self._when(p["to"]):
                continue
            out.append(u)
        return out[p.get("offset", 0) : p.get("offset", 0) + min(p.get("limit", 100), 500)]

    def _events(self, p):
        rows = [
            e
            for e in self.events
            if ("actor" not in p or e["actor"] == p["actor"])
            and ("action" not in p or e["action"] == p["action"])
            and ("file" not in p or p["file"].lower() in (e["fileName"] or "").lower())
            and ("from" not in p or self._when(e["performedAt"]) >= self._when(p["from"]))
            and ("to" not in p or self._when(e["performedAt"]) < self._when(p["to"]))
        ]
        limit, offset = p.get("limit", 100), p.get("offset", 0)
        return {
            "classification": self.classification,
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "entries": rows[offset : offset + limit],
        }

    def list_calls(self):
        return [c for c in self.calls if c[1] == "/api/csv/uploads"]

    def event_calls(self):
        return [c for c in self.calls if c[1] == "/api/audit/events"]


@pytest.fixture(autouse=True)
def clean_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(api_client, "request", fake)
    monkeypatch.setattr(api_client, "download", fake.download)
    return fake


def _history(api, who="rita", **kw):
    return screen("history", who, **kw)


def _apply(at, **fields):
    """Fill the filter form and press Apply."""
    for label, value in fields.items():
        el = widget(
            at.text_input
            if label in ("File name contains", "Uploaded by", "Actor", "File")
            else at.selectbox
            if label in ("Status", "Action")
            else at.date_input,
            label,
        )
        (
            el.input
            if label in ("File name contains", "Uploaded by", "Actor", "File")
            else el.select
            if label in ("Status", "Action")
            else el.set_value
        )(value)
    widget(at.button, "Apply").click().run()
    assert not at.exception, at.exception
    return at


def _frame(at):
    return at.table[0].value


def _names(at):
    """The file names in the list: each is in a code span (a cell of st.table is Markdown), shown here without it."""
    return [v.strip("` ") for v in _frame(at)["File"]]


def _last_list(api):
    return api.list_calls()[-1][3]


# ── the list ──────────────────────────────────────────────────────────────────────────────


def test_the_list_shows_every_import_newest_first_with_how_each_ended(api):
    api.uploads = [
        _upload(1, "a.csv", "imported", total=3),
        _upload(2, "b.csv", "partly_imported", total=10, failed=4),
        _upload(3, "c.csv", "failed", total=5, failed=5),
        _upload(4, "d.csv", "rejected", total=None),
        _upload(5, "e.csv", "duplicate"),
    ]

    at = _history(api)

    frame = _frame(at)
    assert _names(at) == ["a.csv", "b.csv", "c.csv", "d.csv", "e.csv"]
    assert frame.index.name == "#" and list(frame.index) == [1, 2, 3, 4, 5]
    assert list(frame["Status"]) == ["Imported", "Partly imported", "Failed", "Rejected", "Duplicate"]
    assert list(frame["Failed"]) == ["0", "4", "5", "0", "0"] and list(frame["Rows"])[3] == ""
    assert list(frame["Uploaded (UTC)"])[0] == "2026-11-18 00:00 UTC", "times are UTC, as in the React screen's tooltip"
    assert [c.value for c in at.caption][1] == "Imports 1 to 5, newest first."


def test_a_tenant_with_no_imports_is_told_so(api):
    api.uploads = []

    assert [i.value for i in _history(api).info] == ["No imports yet. Upload a CSV file to see it here."]


# ── filters (React: audit-filters.test.ts) ────────────────────────────────────────────────


def test_the_file_name_filter_is_sent_trimmed_and_matches_ignoring_case(api):
    api.uploads = [_upload(1, "Sales_2026.csv"), _upload(2, "people.csv")]
    at = _history(api)

    _apply(at, **{"File name contains": "  SALES "})

    assert _last_list(api)["file"] == "SALES"
    assert _names(at) == ["Sales_2026.csv"]


def test_the_status_filter_asks_for_that_status_only(api):
    api.uploads = [
        _upload(1, status="imported"),
        _upload(2, status="failed", failed=30),
        _upload(3, status="duplicate"),
    ]
    at = _history(api)

    _apply(at, Status="failed")

    assert _last_list(api)["status"] == "failed" and list(_frame(at)["Status"]) == ["Failed"]


def test_the_uploader_filter(api):
    api.uploads = [_upload(1, uploader="alice"), _upload(2, uploader="rita")]

    at = _apply(_history(api), **{"Uploaded by": "rita"})

    assert _last_list(api)["uploader"] == "rita" and list(_frame(at)["Uploaded by"]) == ["` rita `"]


def test_the_date_range_includes_the_whole_of_the_last_day_and_nothing_after_it(api):
    day = date(2026, 11, 18)
    api.uploads = [
        _upload(1, "late.csv", at=datetime(2026, 11, 18, 23, 59, tzinfo=timezone.utc)),
        _upload(2, "next.csv", at=datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)),
        _upload(3, "early.csv", at=datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)),
        _upload(4, "before.csv", at=datetime(2026, 11, 16, 23, 59, tzinfo=timezone.utc)),
    ]
    at = _history(api)

    _apply(at, From=date(2026, 11, 17), To=day)

    params = _last_list(api)
    assert params["from"] == "2026-11-17T00:00:00+00:00" and params["to"] == "2026-11-19T00:00:00+00:00"
    assert sorted(_names(at)) == ["early.csv", "late.csv"]


def test_filters_that_match_nothing_say_so_and_blank_filters_are_not_sent(api):
    at = _apply(_history(api), **{"File name contains": "no such file"})
    assert [i.value for i in at.info] == ["No imports match the filters."]

    at = _apply(at, **{"File name contains": "   "})
    assert len(_frame(at)) == 3, "blank again: everything is back"
    assert all(c[3].get("file") == "no such file" or "file" not in c[3] for c in api.list_calls()), (
        "a blank filter is never sent"
    )


# ── pages ─────────────────────────────────────────────────────────────────────────────────


def test_the_list_pages_by_twenty_five_and_knows_there_is_a_next_page_without_a_count(api):
    api.uploads = [_upload(i, f"f{i:02}.csv") for i in range(1, 31)]
    at = _history(api)
    assert len(_frame(at)) == 25 and _last_list(api) == {"limit": 26, "offset": 0}
    assert widget(at.button, "Previous page").disabled and not widget(at.button, "Next page").disabled

    widget(at.button, "Next page").click().run()

    assert _last_list(api) == {"limit": 26, "offset": 25}
    assert _names(at) == [f"f{i:02}.csv" for i in range(26, 31)]
    assert widget(at.button, "Next page").disabled and not widget(at.button, "Previous page").disabled
    assert [c.value for c in at.caption][1] == "Imports 26 to 30, newest first."

    widget(at.button, "Previous page").click().run()
    assert len(_frame(at)) == 25


def test_applying_a_filter_goes_back_to_the_first_page(api):
    api.uploads = [_upload(i, f"f{i:02}.csv") for i in range(1, 31)]
    at = _history(api)
    widget(at.button, "Next page").click().run()

    _apply(at, **{"File name contains": "f"})

    assert _last_list(api)["offset"] == 0


# ── one import: why rows failed (React: stored-row-errors.test.tsx) ───────────────────────


def _failed_import(api, errors, failed=None, **extra):
    api.uploads = [
        _upload(1, "bad.csv", "partly_imported", total=300, failed=failed or len(errors), reason="2 rows failed")
    ]
    api.details["1"] = {
        "id": "1",
        "fileName": "bad.csv",
        "status": "partly_imported",
        "totalRows": 300,
        "importedRows": 298,
        "failedRows": failed or len(errors),
        "rowErrors": errors,
        "logs": [
            {
                "ts": 1_795_000_000_123,
                "step": "cast_rows",
                "level": "warn",
                "message": "2 rows failed validation",
                "count": 2,
            }
        ],
        "uploader": "alice",
        "state": "imported",
        **extra,
    }


def _open(at, uid="1"):
    widget(at.selectbox, "Details of an import").select(uid).run()
    assert not at.exception, at.exception
    return at


def test_choosing_an_import_lists_the_reasons_the_server_stored(api):
    _failed_import(
        api,
        [
            {"rowNumber": 7, "column": "amount", "value": "x", "reason": '"x" is not a whole number'},
            {"rowNumber": 14, "column": "amount", "value": "y", "reason": '"y" is not a whole number'},
        ],
    )

    at = _open(_history(api))

    assert at.subheader[0].value == "` bad.csv `"
    assert "Partly imported · 2 of 300 rows failed · uploaded by alice · 2026-11-18 00:00 UTC" in [
        c.value for c in at.caption
    ]
    assert [i.value for i in at.info] == ["Why: ` 2 rows failed `"]
    frame = at.table[1].value
    assert frame.index.name == "Row" and list(frame.columns) == ["Column", "Value", "Reason"]
    assert list(frame.index) == [7, 14] and list(frame["Value"]) == ["` x `", "` y `"]
    assert list(frame["Reason"])[0] == '` "x" is not a whole number `', "the reason is in a code span too"
    assert api.calls[-1][1] == "/api/csv/uploads/1", "the reasons come from the server record"


def test_it_says_so_when_the_server_kept_fewer_reasons_than_rows_failed(api):
    _failed_import(
        api, [{"rowNumber": i, "column": "a", "value": "x", "reason": "bad"} for i in range(1, 201)], failed=351
    )

    at = _open(_history(api))

    assert len(at.table[1].value) == 200
    assert "Showing the first 200 of 351 failed rows: the server keeps the reasons for the first 200 only." in [
        c.value for c in at.caption
    ]


def test_it_says_so_when_no_reasons_were_stored(api):
    _failed_import(api, [], failed=5)

    at = _open(_history(api))

    assert "No failure reasons were stored for this upload." in [c.value for c in at.caption]
    assert not any(w.value == "**Rows that failed**" for w in at.markdown), "no table of reasons"
    assert at.table[1].value.index.name == "Time (UTC)", "the second table is the step log"


def test_the_step_log_is_shown_in_utc_whatever_the_servers_own_zone(api, monkeypatch):
    import time

    monkeypatch.setenv("TZ", "Australia/Sydney")  # ten hours from UTC: local time would show
    if hasattr(time, "tzset"):  # not on Windows, where the zone cannot be changed from inside the process
        time.tzset()
    try:
        _failed_import(api, [{"rowNumber": 1, "reason": "bad"}])
        at = _open(_history(api))
    finally:
        monkeypatch.undo()
        if hasattr(time, "tzset"):
            time.tzset()

    log = at.table[-1].value
    assert list(log["Step"]) == ["cast_rows"] and list(log["Level"]) == ["warn"] and list(log["Count"]) == ["2"]
    assert list(log["Message"]) == ["` 2 rows failed validation `"]
    assert log.index[0] == datetime.fromtimestamp(1_795_000_000.123, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def test_an_import_with_no_step_log_says_so(api):
    api.uploads = [_upload(1)]

    at = _open(_history(api))

    assert any(w.value == "No step log was stored for this upload." for w in at.markdown)


def test_a_rejected_import_offers_its_reason_as_a_report_even_with_no_row_errors(api):
    api.uploads = [_upload(1, "nope.csv", "rejected", total=None, reason="The file has no header row")]
    api.details["1"] = {
        "id": "1",
        "fileName": "nope.csv",
        "status": "rejected",
        "totalRows": None,
        "failedRows": 0,
        "rowErrors": [],
        "logs": [],
        "uploader": "alice",
        "state": "rejected",
    }

    at = _open(_history(api))

    assert [i.value for i in at.info] == ["Why: ` The file has no header row `"]
    assert [b.label for b in at.get("download_button")] == ["Error report (CSV)", "Error report (XLSX)"]


def test_a_clean_import_has_no_error_report(api):
    at = _open(_history(api), "2")

    assert not at.get("download_button") or [b.label for b in at.get("download_button")] == []


def test_the_error_report_downloads_are_named_for_the_file(api):
    _failed_import(api, [{"rowNumber": 7, "column": "amount", "value": "x", "reason": "bad"}])

    at = _open(_history(api))

    names = [b.proto.url for b in at.get("download_button")]
    assert [b.label for b in at.get("download_button")] == ["Error report (CSV)", "Error report (XLSX)"]
    assert len(names) == 2


# ── a report of the whole filtered list ───────────────────────────────────────────────────


def test_a_report_collects_every_matching_import_not_only_the_page(api):
    api.uploads = [_upload(i, f"f{i:04}.csv") for i in range(1, 1201)]
    at = _history(api)
    assert not at.get("download_button")

    widget(at.button, "Prepare a report of all matching imports").click().run()

    assert [b.label for b in at.get("download_button")] == ["Download CSV", "Download XLSX"]
    assert "Report of 1200 imports." in [c.value for c in at.caption]
    report_calls = [c[3] for c in api.list_calls() if c[3]["limit"] > 26]
    assert [(c["limit"], c["offset"]) for c in report_calls] == [(500, 0), (500, 500), (500, 1000)]


def test_a_report_that_hits_the_cap_says_it_was_cut_short(api, monkeypatch):
    monkeypatch.setattr(h, "EXPORT_LIMIT", 40)
    monkeypatch.setattr(h, "EXPORT_PAGE", 25)
    api.uploads = [_upload(i, f"f{i:04}.csv") for i in range(1, 61)]
    at = _history(api)

    widget(at.button, "Prepare a report of all matching imports").click().run()

    assert any(c.value.startswith("Report of 40 imports, cut short at 40") for c in at.caption)


def test_a_report_for_one_set_of_filters_is_not_offered_for_another(api):
    api.uploads = [_upload(i) for i in range(1, 4)]
    at = _history(api)
    widget(at.button, "Prepare a report of all matching imports").click().run()
    assert at.get("download_button")

    _apply(at, **{"File name contains": "people"})

    assert not at.get("download_button"), "a report built for other filters must not be offered"


def test_the_report_asks_for_what_the_filters_ask_for(api):
    api.uploads = [_upload(1, status="failed", failed=30), _upload(2, status="imported")]
    at = _apply(_history(api), Status="failed")

    widget(at.button, "Prepare a report of all matching imports").click().run()

    report = [c[3] for c in api.list_calls() if c[3]["limit"] == 500]
    assert report and all(p["status"] == "failed" for p in report)


# ── the list is cached and never shared ───────────────────────────────────────────────────


def test_the_list_is_fetched_once_for_many_reruns_and_again_on_refresh(api):
    at = _history(api)
    _open(at)
    widget(at.selectbox, "Details of an import").select("2").run()
    assert len(api.list_calls()) == 1

    widget(at.button, "Refresh the list").click().run()

    assert len(api.list_calls()) == 2


def test_one_sessions_list_is_never_shown_to_another(api):
    api.lists_by_token = {"tok-a": [_upload(1, "acme-secret.csv")], "tok-b": [_upload(2, "zed-plans.csv")]}

    a = _history(api, "rita", token="tok-a")
    b = _history(api, "ada", token="tok-b")

    assert _names(a) == ["acme-secret.csv"] and _names(b) == ["zed-plans.csv"]
    assert {c[2] for c in api.list_calls()} == {"tok-a", "tok-b"}


# ── a session the server ended, a server that is down ────────────────────────────────────


def test_a_session_the_server_ended_signs_the_person_out_with_a_reason(api):
    api.dead.add("tok-1")

    at = _history(api)

    assert "session" not in at.session_state and at.session_state["notice"].startswith("Your session has ended")


def test_a_session_that_ends_while_opening_an_import_does_the_same(api):
    at = _history(api)
    api.dead.add("tok-1")

    widget(at.selectbox, "Details of an import").select("1").run()

    assert "session" not in at.session_state


def test_an_api_that_is_down_says_so_instead_of_failing(api):
    api.down = True

    at = _history(api)

    assert "Can't reach the API" in errors(at)[0]


# ── text from a file is shown as written ─────────────────────────────────────────────────


def test_a_file_name_and_a_reason_that_look_like_links_show_as_written(api):
    evil = "[click](https://evil.example/login)"
    api.uploads = [_upload(1, f"{evil}.csv", "failed", failed=30, reason=f"see {evil}")]
    api.details["1"] = {
        "id": "1",
        "fileName": f"{evil}.csv",
        "status": "failed",
        "totalRows": 30,
        "failedRows": 30,
        "rowErrors": [],
        "logs": [],
        "uploader": "alice",
        "state": "rejected",
    }

    at = _open(_history(api))

    assert at.subheader[0].value == f"` {evil}.csv `"
    assert [i.value for i in at.info] == [f"Why: ` see {evil} `"]


# ── the server's audit events ────────────────────────────────────────────────────────────


def _events(n=3):
    return [
        {
            "id": str(i),
            "performedAt": (T0 - timedelta(minutes=i)).isoformat(),
            "actor": "rita" if i % 2 else "ada",
            "action": "upload" if i % 2 else "import",
            "fileId": None,
            "fileName": f"f{i}.csv",
            "tableName": f"t{i}",
            "mode": "dynamic",
            "before": None,
            "after": None,
        }
        for i in range(1, n + 1)
    ]


def _show_events(api, who="ada", n=3):
    api.events = _events(n)
    at = _history(api, who)
    widget(at.radio, "Show").set_value("Server audit events").run()
    assert not at.exception, at.exception
    return at


def test_only_roles_that_may_read_the_audit_log_get_the_events_view(api):
    for who, may in (("alice", False), ("rita", False), ("ada", True), ("audrey", True)):
        at = _history(api, who)
        assert bool(at.radio) is may, who
    assert not api.event_calls(), "nothing is asked of the audit log until it is opened"


def test_the_events_view_lists_the_servers_events_with_the_classification(api):
    at = _show_events(api)

    frame = at.table[0].value
    assert frame.index.name == "When (UTC)" and list(frame.columns) == ["Actor", "Action", "File", "Table"]
    assert list(frame["Action"]) == ["upload", "import", "upload"]
    assert list(frame["File"]) == ["` f1.csv `", "` f2.csv `", "` f3.csv `"]
    assert "3 events · OFFICIAL: Sensitive" in [c.value for c in at.caption]
    assert api.event_calls()[-1][3] == {"limit": 100, "offset": 0}


def test_the_events_filters_are_sent_as_the_react_panel_sent_them(api):
    at = _show_events(api)

    _apply(at, Actor=" rita ", Action="upload", File="f1", From=date(2026, 11, 18), To=date(2026, 11, 18))

    assert api.event_calls()[-1][3] == {
        "limit": 100,
        "offset": 0,
        "actor": "rita",
        "action": "upload",
        "file": "f1",
        "from": "2026-11-18T00:00:00+00:00",
        "to": "2026-11-19T00:00:00+00:00",
    }
    assert list(at.table[0].value["File"]) == ["` f1.csv `"]
    assert "1 event · OFFICIAL: Sensitive" in [c.value for c in at.caption]


def test_the_action_filter_offers_exactly_the_actions_the_api_records(api):
    at = _show_events(api)

    assert widget(at.selectbox, "Action").options == ["All", *h.AUDIT_ACTIONS]


def test_no_matching_events_says_so(api):
    at = _show_events(api)

    _apply(at, Actor="nobody")

    assert [i.value for i in at.info] == ["No events match the filters."]


def test_the_events_page_by_a_hundred_and_the_buttons_know_the_ends(api):
    api.events = _events(150)
    at = _history(api, "ada")
    widget(at.radio, "Show").set_value("Server audit events").run()
    assert widget(at.button, "Previous events").disabled and not widget(at.button, "Next events").disabled

    widget(at.button, "Next events").click().run()

    assert api.event_calls()[-1][3]["offset"] == 100 and len(at.table[0].value) == 50
    assert widget(at.button, "Next events").disabled and not widget(at.button, "Previous events").disabled


def test_the_csv_of_events_is_the_servers_own_with_every_matching_event(api):
    at = _show_events(api)
    _apply(at, Action="import")

    widget(at.button, "Prepare a CSV of all matching events").click().run()

    assert api.event_calls()[-1][3] == {"action": "import", "format": "csv"}, "no paging: the API caps it itself"
    assert [b.label for b in at.get("download_button")] == ["Download CSV"]
    assert any("already neutralised spreadsheet formulas" in c.value for c in at.caption)


def test_events_prepared_for_one_filter_are_not_offered_for_another(api):
    at = _show_events(api)
    widget(at.button, "Prepare a CSV of all matching events").click().run()
    assert at.get("download_button")

    _apply(at, Actor="rita")

    assert not at.get("download_button")


def test_a_session_that_ends_while_reading_events_signs_out(api):
    at = _show_events(api, n=150)  # enough for a next page, so there is a button to press
    api.dead.add("tok-1")

    widget(at.button, "Next events").click().run()

    assert "session" not in at.session_state


# ── what the model asks and says ─────────────────────────────────────────────────────────


def test_day_start_is_midnight_utc():
    assert h.day_start(date(2026, 3, 1)) == "2026-03-01T00:00:00+00:00"


def test_params_leave_out_blank_filters_and_the_to_day_runs_to_the_next_midnight():
    assert h.uploads_params() == {"limit": 26, "offset": 0}
    assert h.uploads_params(
        file=" a ",
        status="failed",
        uploader="",
        date_from=date(2026, 12, 31),
        date_to=date(2026, 12, 31),
        limit=5,
        offset=10,
    ) == {
        "limit": 5,
        "offset": 10,
        "file": "a",
        "status": "failed",
        "from": "2026-12-31T00:00:00+00:00",
        "to": "2027-01-01T00:00:00+00:00",
    }


def test_an_events_download_is_not_paged():
    assert h.events_params(action="import", fmt="csv") == {"action": "import", "format": "csv"}
    assert h.events_params(limit=50, offset=100) == {"limit": 50, "offset": 100}


def test_page_of_keeps_a_page_and_says_whether_more_follow():
    assert h.page_of(list(range(26))) == (list(range(25)), True)
    assert h.page_of(list(range(25))) == (list(range(25)), False)
    assert h.page_of([]) == ([], False)


@pytest.mark.parametrize(
    "have, cap, page, expect_rows, expect_capped, expect_calls",
    [
        (0, 10, 4, 0, False, [(4, 0)]),
        (7, 10, 4, 7, False, [(4, 0), (4, 4)]),
        (10, 10, 4, 10, False, [(4, 0), (4, 4), (3, 8)]),  # exactly the cap: nothing more, so not cut short
        (11, 10, 4, 10, True, [(4, 0), (4, 4), (3, 8)]),  # one more than the cap: cut short
        (50, 10, 4, 10, True, [(4, 0), (4, 4), (3, 8)]),
    ],
)
def test_collect_stops_at_the_cap_and_knows_if_there_was_more(
    have, cap, page, expect_rows, expect_capped, expect_calls
):
    calls = []

    def fetch(limit, offset):
        calls.append((limit, offset))
        return list(range(offset, min(offset + limit, have)))

    rows, capped = h.collect(fetch, cap=cap, page=page)

    assert (len(rows), capped, calls) == (expect_rows, expect_capped, expect_calls)


def test_the_statuses_offered_are_the_ones_the_api_knows():
    from api.routers.csv_routes import _UPLOAD_STATUSES

    assert {s for s, _ in h.STATUSES if s} == set(_UPLOAD_STATUSES)


def test_the_actions_offered_are_the_ones_the_api_records():
    from api.services.audit import VALID_ACTIONS

    assert set(h.AUDIT_ACTIONS) == set(VALID_ACTIONS)


def test_outcome_line_covers_a_clean_a_partial_and_a_rejected_import():
    up = _upload(1)
    assert h.outcome_line(up, {"status": "imported", "totalRows": 1, "failedRows": 0}).startswith("Imported · 1 row · ")
    assert h.outcome_line(up, {"status": "partly_imported", "totalRows": None, "failedRows": 2}).startswith(
        "Partly imported · 2 of ? rows failed"
    )
    assert h.outcome_line(_upload(1, status="rejected", uploader=None), {"status": "rejected"}).startswith(
        "Rejected · "
    )


def test_errors_note_only_when_the_server_kept_fewer_than_failed():
    assert h.errors_note(200, 351) and h.errors_note(200, 200) is None and h.errors_note(5, None) is None
