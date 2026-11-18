# Streamlit Migration (steps 2–6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish moving the front end from React (`csv-table-hub-main/`) to Streamlit (`streamlit_app/`), with the review, import-history and upload screens, packaging, and then removal of React.

**Architecture:** Each screen is one module in `streamlit_app/views/` with a `render()` function, registered in `app.py` behind `auth.can(action)`. API calls go through `auth.call` → `api_client.request`, which is the only HTTP path. Logic that AppTest can't reach (file uploads, rules, exports) lives in small pure modules (`outcomes.py`, `exports.py`, and the helpers in `views/upload.py`) and is tested directly. The API is not changed.

**Tech Stack:** Python 3.12, `streamlit==1.67.0` (pinned), `requests`, `pandas` (comes with Streamlit), `openpyxl` (new, for XLSX), pytest with `streamlit.testing.v1.AppTest`, and Playwright for the browser tests in `e2e/`.

**Spec:** `DECISIONS/2026-11-16-streamlit-migration-plan.md`, issues #252, #253, #255, #256, #257 and #258, and the #254 spike outcome (`spikes/streamlit_upload/README.md`). Step 1 (#251, the shell) is already on `main`.

## Assumptions (record defaults; the owner can override any of them)

| # | Open question | Assumed here |
|---|---|---|
| 1 | Whole-app or per-screen cutover | Whole app, with React kept for one release as the rollback |
| 2 | OIDC in the UI | No (the React app has none; `streamlit[auth]` is not added) |
| 3 | Where Streamlit runs in Azure | **Open.** The Azure half of #256 is not in this plan |
| 4 | About +116 MB in the offline bundle | Accepted |
| 5 | A screen for the server's audit log; the "App changelog" | No audit-log screen (not needed for parity). The changelog is dropped in favour of release notes |
| 6 | Saved mapping templates | Dropped. Users are told at cutover |
| 7 | The accessibility job (#168) after React goes | Kept and pointed at Streamlit (Task 7) |
| 8 | Where the Streamlit tests run in CI (#258) | Already settled: `requirements-dev.txt` pins Streamlit, so the AppTest tests run with the unit tests |
| 9 | A file that isn't UTF-8 | Refused with a message. React imports it with replacement characters, which silently changes the data |
| 10 | Bulk selection on the history screen | Dropped. Exporting the filtered list does the same job |

## Global Constraints

- `streamlit==1.67.0` exactly, in both `streamlit_app/requirements.txt` and `requirements-dev.txt` (an existing test enforces this).
- Don't use `use_container_width` (an existing test fails on it); use `width="stretch"`.
- `browser.gatherUsageStats = false` stays in `streamlit_app/.streamlit/config.toml`.
- Nothing goes in browser storage. All state lives in `st.session_state`, and ending the session clears it (`auth.end_session`).
- The API is the enforcer. Screens hide controls with `auth.can(action)` using the names in `auth.PERMISSIONS`.
- Every HTTP call goes through `auth.call(...)`, so a 401 always signs the user out with "Your session has ended. Sign in again."
- The API's limit is `MAX_UPLOAD_BYTES`, default `52428800` (50 MiB), measured on the UTF-8 bytes of the content.
- The upload endpoint is `POST /api/csv/upload` (not the staged path).
- The no-cancel wording, exactly: `Sent to the server; it can't be stopped now` (#188).
- Formula guard (#193) on every exported cell: a string matching `^[=+\-@\t\r]` that does not match `^[+-]?\d+(\.\d+)?$` gets a `'` prefix.
- Allowed column types: `int8, numeric, date, timestamptz, boolean, text` (`api/services/csv_parse.py`).
- Tests that need something missing must fail, not skip (repository policy).

## Review Focus

1. **A file that isn't UTF-8** (such as Latin-1 `name\n\xe9t\xe9\n`) is refused with a plain message and nothing is sent. Tested in Task 6 (`test_prepare_refuses_non_utf8`).
2. **A file exactly at the limit, and one byte over.** The first is accepted, the second is refused without an API call, and the message gives the limit in MB. Tested in Task 6 (`test_size_boundary`).
3. **An import that takes longer than the client waits.** The user must not be told "Can't reach the API… Is it running?" while the server is still importing. They get a timed-out message that points to Import history. Tested in Task 6 (`test_timeout_is_not_reported_as_unreachable`).
4. **The session ends during a review save** (a 401 on the PUT). The user is signed out with the notice and sees no traceback. Tested in Task 4 (`test_401_on_save_signs_out`).
5. **Stale counts after an edit.** The cached uploads list must be cleared when a review change is saved, so the excluded and edited counts update at once. Tested in Task 4 (`test_saving_clears_the_uploads_cache`).

---

### Task 1: Shared AppTest harness

Move the fakes out of the shell's test file so each screen's tests can reuse them. This is a pure refactor: the 40 existing tests must still pass.

**Files:**
- Create: `tests/unit/streamlit_harness.py`
- Modify: `tests/unit/test_streamlit_shell.py` (delete the moved code and import it instead)

**Interfaces:**
- Produces:
  - `APP_DIR: Path`, `PASSWORD: str`, `USERS: dict[tuple[str, str], str]`, `later(hours: float = 8) -> str`
  - `class FakeApi`: the existing class, plus `routes: dict[tuple[str, str], object]`. For `(method, path)` in `routes`, it returns the value, or, if the value is callable, calls it with `(token, **kwargs)`. It records every call in `calls`. An unknown route raises `AssertionError`, as now.
  - The `api` pytest fixture (monkeypatches `api_client.request` with a `FakeApi`).
  - `view(name: str, who: tuple[str, str] = ("acme", "alice"), api: FakeApi | None = None) -> AppTest`: the existing `_view`.

- [ ] **Step 1: Move** `FakeApi`, `USERS`, `PASSWORD`, `_later`, `HARNESS`, `_view` and the `api` fixture into `streamlit_harness.py`. Rename `_later` to `later` and `_view` to `view`, and add `routes`.
- [ ] **Step 2: Run** `python -m pytest tests/unit/test_streamlit_shell.py -q`. Expected: 40 passed.
- [ ] **Step 3: Commit** `test: share the Streamlit AppTest harness`.

---

### Task 2: Outcome rules (`outcomes.py`)

Port the rules in `csv-table-hub-main/src/lib/job-outcome.ts` that still apply. Overwrite no longer exists (M5), and Stop/cancel is gone.

**Files:**
- Create: `streamlit_app/outcomes.py`
- Test: `tests/unit/test_streamlit_outcomes.py`

**Interfaces:**
- Produces:
  - `needs_attention(status: str) -> bool`
  - `failed_rows_note(u: dict) -> str | None` (reads `failed_rows` and `total_rows`)
  - `types_provenance_note(u: dict) -> str | None` (reads `types_provenance`)
  - `describe_result(file_name: str, res: dict) -> tuple[str, str]`, returning a level (`"success" | "warning" | "error"`) and a message
  - `STATUS_LABELS: dict[str, str]` = `{"imported": "Imported", "partly_imported": "Partly imported", "failed": "Failed", "rejected": "Rejected", "duplicate": "Duplicate", "staged": "Staged"}`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_streamlit_outcomes.py -q`. Expected: FAIL (`ModuleNotFoundError: outcomes`). The tests add `APP_DIR` to `sys.path` the way the shell tests do.
- [ ] **Step 3: Implement** `streamlit_app/outcomes.py` with the signatures above. It imports nothing from Streamlit.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(streamlit): outcome rules ported from job-outcome.ts`.

---

### Task 3: Exports with the formula guard (`exports.py`)

**Files:**
- Create: `streamlit_app/exports.py`
- Modify: `streamlit_app/requirements.txt` and `requirements-dev.txt` (add `openpyxl==3.1.5` to both)
- Test: `tests/unit/test_streamlit_exports.py`

**Interfaces:**
- Produces:
  - `safe_cell(v: object) -> object`: `None` becomes `""`. A guarded string gets the `'` prefix. Anything else is returned unchanged.
  - `to_csv(headers: list[str], rows: list[dict]) -> bytes`: UTF-8, uses the `csv` module, every cell through `safe_cell`.
  - `to_xlsx(sheet: str, headers: list[str], rows: list[dict]) -> bytes`: openpyxl, sheet name cut to 31 characters, every cell through `safe_cell`.
  - `ERROR_HEADERS = ["file", "row_number", "column", "value", "reason"]`
  - `error_rows(upload: dict, detail: dict) -> list[dict]`: one row per `detail["rowErrors"]` item (`rowNumber`, `column`, `value`, `reason`). If there are none and `upload["failure_reason"]` is set, a single row with `row_number` 0 and that reason.
  - `HISTORY_HEADERS = ["file", "status", "uploaded_at", "uploader", "mode", "total_rows", "imported_rows", "failed_rows", "failure_reason"]`
  - `history_rows(uploads: list[dict]) -> list[dict]` (from `GET /api/csv/uploads` items; `file` is `file_name`)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw,out", [("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"), ("+1+2", "'+1+2"), ("@SUM(A1)", "'@SUM(A1)"),
                                     ("\tx", "'\tx"), ("-5", "-5"), ("+3.2", "+3.2"), ("-1+2", "'-1+2"), ("plain", "plain"), (None, ""), (7, 7)])
def test_safe_cell(raw, out):
    assert safe_cell(raw) == out

def test_csv_is_guarded_and_quoted():
    data = to_csv(["a", "b"], [{"a": "=1+1", "b": 'say "hi", ok'}]).decode()
    assert data.splitlines() == ["a,b", "'=1+1,\"say \"\"hi\"\", ok\""]

def test_xlsx_is_guarded():
    wb = openpyxl.load_workbook(io.BytesIO(to_xlsx("x" * 40, ["a"], [{"a": "=HYPERLINK(1)"}])))
    ws = wb.worksheets[0]
    assert ws.title == "x" * 31 and ws["A2"].value == "'=HYPERLINK(1)"

def test_error_rows_from_detail_and_fallback():
    detail = {"rowErrors": [{"rowNumber": 3, "column": "age", "value": "x", "reason": "not a number"}]}
    assert error_rows({"file_name": "a.csv"}, detail) == [{"file": "a.csv", "row_number": 3, "column": "age", "value": "x", "reason": "not a number"}]
    assert error_rows({"file_name": "a.csv", "failure_reason": "empty file"}, {"rowErrors": []}) == [{"file": "a.csv", "row_number": 0, "column": "", "value": "", "reason": "empty file"}]
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_streamlit_exports.py -q`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `streamlit_app/exports.py`, and add the `openpyxl==3.1.5` pin to both requirements files.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(streamlit): CSV and XLSX exports with the formula guard (#193)`.

---

### Task 4: Review screen (#252)

Productionise `spikes/streamlit_review/app.py`. Two departures from the spike: **forms inline in the row panel, not `st.dialog`**, so AppTest can drive edit, exclude and history; and **a "Row number" input** as the way to pick a row. Grid selection writes into that input through `on_select`.

**Files:**
- Create: `streamlit_app/views/review.py`
- Modify: `streamlit_app/views/__init__.py` (the screen registry), `streamlit_app/app.py` (register pages from it)
- Move: `e2e/test_streamlit_spike.py` → `e2e/test_streamlit_review.py`. In `e2e/conftest.py`, the review stack runs `streamlit_app/app.py`, not the spike.
- Delete: `spikes/streamlit_review/`
- Test: `tests/unit/test_streamlit_review.py`

**Interfaces:**
- Consumes: `auth.call`, `auth.can`, `auth.session`, `outcomes.needs_attention`, `outcomes.failed_rows_note`; the harness from Task 1
- Produces:
  - In `views/__init__.py`: `SCREENS: list[tuple[str, str, str]]` holding `(action, title, url_path)`, with this entry `("read_rows", "Review", "review")`. Tasks 5 and 6 add theirs. Also `allowed_screens(role: str) -> list[str]`, returning url paths in `SCREENS` order. `app.py` builds an `st.Page` for each allowed screen from `views.<url_path>.render`.
  - `views/review.py`: `render() -> None`; `PAGE = 100`; `uploads_list(token: str) -> list[dict]`, decorated `@st.cache_data(ttl=30)`, which calls `GET /api/csv/uploads`
- API used: `GET /api/csv/uploads`, `GET /api/csv/uploads/{id}/rows?offset=&limit=`, `PUT …/rows/{n}/decision` `{"decision", "reason"}`, `PUT …/rows/{n}/cells/{col}` `{"value", "reason"}`, `GET …/rows/{n}/history`

- [ ] **Step 1: Write the failing tests** (`view("review", who, api)`, with `api.routes` holding one upload of 3 rows: row 2 has an error on `amount`, row 3 has a `(database)` error)

```python
def test_rows_show_their_validation_and_database_errors(api)   # row 3 picked: an at.error value contains "(database)" and the API's reason
def test_uploader_sees_read_only_and_no_change_controls(api)    # caption has "read-only for your role"; no "Exclude"/"Save edit" buttons
def test_reviewer_exclude_needs_a_reason(api)                    # submit with empty reason: at.error == ["Give a reason."]; no PUT in api.calls
def test_reviewer_exclude_sends_decision(api)                    # PUT …/rows/2/decision with {"decision": "exclude", "reason": "dup"}
def test_reviewer_edit_sends_new_value_with_reason(api)          # PUT …/rows/2/cells/1 with {"value": "20", "reason": "typo"}
def test_history_lists_entries(api)                              # "History" click → entry actor and reason shown
def test_failed_or_partial_filter_and_rejected_has_no_rows(api)  # filter keeps only needs_attention; a rejected upload shows st.info, no GET …/rows
def test_no_uploads_says_so(api)                                 # at.info == ["No uploads yet."]
def test_401_on_save_signs_out(api)                              # PUT raises Unauthorized → session gone, notice "Your session has ended. Sign in again."
def test_saving_clears_the_uploads_cache(api)                    # after a save, the next run calls GET /api/csv/uploads again
def test_allowed_screens_follow_permissions():
    assert allowed_screens("auditor") == ["review"]               # extended in Tasks 5 and 6
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_streamlit_review.py -q`. Expected: FAIL (no `views.review`).
- [ ] **Step 3: Implement** `views/review.py`, the registry, and the `app.py` registration. The cell tint, paging and captions follow the spike, using `width="stretch"`. A reason must be non-blank. After a successful PUT, call `uploads_list.clear()` and then `st.rerun()`.
- [ ] **Step 4: Run** `python -m pytest tests/unit -q -k streamlit`. Expected: all pass, the shell tests included.
- [ ] **Step 5: Port the browser tests.** Rename the file, point the conftest at the app, and replace the dialog steps with the inline forms. Run it as described in `e2e/README.md`. Expected: 4 passed.
- [ ] **Step 6: Delete** `spikes/streamlit_review/`. Commit `feat(streamlit): review screen (#252)`.

---

### Task 5: Import-history screen (#253)

The history comes from the server, not the browser. **This is a user-visible change:** the history is shared across the tenant.

**Files:**
- Create: `streamlit_app/views/history.py`
- Modify: `streamlit_app/views/__init__.py` (add `("list_files", "Import history", "history")`)
- Test: `tests/unit/test_streamlit_history.py`

**Interfaces:**
- Consumes: `exports.to_csv`, `to_xlsx`, `error_rows`, `history_rows`, `ERROR_HEADERS` and `HISTORY_HEADERS`; `outcomes.STATUS_LABELS` and `failed_rows_note`
- Produces: `render() -> None`; `query_params(file: str, status: str | None, start: date | None, end: date | None) -> dict`
- API used: `GET /api/csv/uploads?limit=500&file=&status=&from=&to=` (the server filters), and `GET /api/csv/uploads/{id}`

- [ ] **Step 1: Write the failing tests**

```python
def test_query_params_send_only_what_is_set():
    assert query_params("", None, None, None) == {"limit": 500}
    assert query_params("orders", "failed", date(2026, 11, 1), date(2026, 11, 3)) == {
        "limit": 500, "file": "orders", "status": "failed", "from": "2026-11-01T00:00:00", "to": "2026-11-04T00:00:00"}  # end date inclusive

def test_filters_reach_the_server(api)            # set file and status widgets → last GET /api/csv/uploads params match
def test_no_imports_match(api)                    # at.info == ["No imports match these filters."]
def test_errors_for_a_chosen_upload(api)          # choose upload → GET /api/csv/uploads/{id}; st.table shows its row errors
def test_exports_are_offered(api)                 # 4 download buttons: history CSV/XLSX, errors CSV/XLSX (at.get("download_button"))
def test_says_the_history_is_shared(api)          # caption contains "shared by everyone in your tenant"
def test_allowed_screens_include_history():
    assert allowed_screens("auditor") == ["review", "history"]
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_streamlit_history.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `views/history.py`. Filters: a file text input, a status selectbox ("Any" plus the `STATUS_LABELS` values), and a date range. Show the list with `st.dataframe(width="stretch")`, and the errors with `st.table`. The download buttons get their bytes from `exports`. Name the files `import-history.csv` / `.xlsx` and `<file>-errors.csv` / `.xlsx`.
- [ ] **Step 4: Run** `python -m pytest tests/unit -q -k streamlit`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(streamlit): import history from the server (#253)`.

---

### Task 6: Upload and preview screen (#255)

Build on `spikes/streamlit_upload/app.py`, with its workarounds applied. The **widget form is the only mapping editor** (no `st.data_editor`). The app enforces the real size limit. Uploads get a longer timeout. AppTest has no file uploader, so the decisions live in pure helpers and the widgets are covered by the browser tests.

**Files:**
- Create: `streamlit_app/views/upload.py`
- Modify: `streamlit_app/api_client.py` (per-call timeout, `TimedOut`); `streamlit_app/.streamlit/config.toml` (`[server] maxUploadSize = 53`, with a comment that the app enforces the real limit); `streamlit_app/views/__init__.py` (add `("upload", "Upload", "upload")` first in the list)
- Move: `e2e/test_streamlit_upload_spike.py` → `e2e/test_streamlit_upload.py`, against the app. Drop the grid-editor cases.
- Delete: `spikes/streamlit_upload/`
- Test: `tests/unit/test_streamlit_upload.py`

**Interfaces:**
- Consumes: `auth.call`, `outcomes.describe_result`
- Produces:
  - `api_client.request(method, path, token=None, timeout: float = TIMEOUT_SECONDS, **kwargs)`. `requests.Timeout` raises `TimedOut(ApiError)` (status 0) with the message `"The server didn't answer within {timeout:.0f} s. It may still be working: check Import history before trying again."`. Other `RequestException`s still raise `Unreachable`.
  - `views/upload.py`: `MAX_UPLOAD_BYTES: int` (from the env, default `52428800`); `UPLOAD_TIMEOUT_SECONDS = 600`; `NO_CANCEL`; `ALLOWED_TYPES`
  - `prepare(name: str, raw: bytes) -> tuple[str | None, str | None]` returns `(text, None)` or `(None, message)`. Non-UTF-8 gives `"{name} isn't UTF-8 text. Save it as \"CSV UTF-8\" and try again."`. Over the limit, measured on `len(text.encode("utf-8"))`, gives `"{name} is larger than the {MAX_UPLOAD_BYTES / 1048576:g} MB the server accepts."`
  - `build_payload(name: str, raw: bytes, text: str, *, mode: str, types: list[str] | None = None, confirmed: bool = False, renames: dict[str, str] | None = None, target: str | None = None) -> dict`. For `mode == "te"`: `{fileName, content, contentBase64, mode: "te", targetTable}`, with no types and no mapping. For `"dynamic"`: adds `types` and `typesConfirmed`, and adds `headerMapping` (`[{"original", "renamed"}]`, blank renames left out) only when non-empty.
  - `render() -> None`
- API used: `POST /api/csv/preview` (cached in `st.session_state` by SHA-256), `GET /api/te/tables`, `POST /api/csv/upload` with `timeout=UPLOAD_TIMEOUT_SECONDS`

- [ ] **Step 1: Write the failing tests**

```python
def test_prepare_refuses_non_utf8():
    assert prepare("a.csv", b"name\n\xe9t\xe9\n") == (None, 'a.csv isn\'t UTF-8 text. Save it as "CSV UTF-8" and try again.')

def test_size_boundary(monkeypatch):
    monkeypatch.setattr(upload, "MAX_UPLOAD_BYTES", 1048576)
    assert prepare("a.csv", b"x" * 1048576)[1] is None
    assert prepare("a.csv", b"x" * 1048577)[1] == "a.csv is larger than the 1 MB the server accepts."
    # the default, 52428800, reads "50 MB"

def test_dynamic_payload_sends_types_only_with_confirmation_and_mapping_only_when_renamed():
    p = build_payload("a.csv", b"a\n1\n", "a\n1\n", mode="dynamic", types=["int8"], confirmed=True, renames={"a": ""})
    assert p["types"] == ["int8"] and p["typesConfirmed"] is True and "headerMapping" not in p
    p = build_payload("a.csv", b"a\n1\n", "a\n1\n", mode="dynamic", types=["int8"], confirmed=True, renames={"a": "age"})
    assert p["headerMapping"] == [{"original": "a", "renamed": "age"}]

def test_te_payload_has_no_mapping_or_types():
    p = build_payload("o.csv", b"x", "x", mode="te", target="organisations")
    assert p["mode"] == "te" and p["targetTable"] == "organisations" and "types" not in p and "headerMapping" not in p
    assert base64.b64decode(p["contentBase64"]) == b"x"

def test_timeout_is_not_reported_as_unreachable(monkeypatch):
    monkeypatch.setattr(requests, "request", Mock(side_effect=requests.Timeout))
    with pytest.raises(api_client.TimedOut, match="check Import history"):
        api_client.request("POST", "/api/csv/upload", timeout=600)

def test_upload_timeout_is_passed_through(monkeypatch)   # requests.request called with timeout=600 for the upload call
def test_uploader_limit_is_above_the_apis():            # config.toml server.maxUploadSize * 1_000_000 > 52428800
def test_role_without_upload_sees_no_upload_screen():
    assert "upload" not in allowed_screens("reviewer") and allowed_screens("uploader")[0] == "upload"
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_streamlit_upload.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the `api_client` change, then `views/upload.py`. The render follows the spike's flow: preview per file, a T&E/dynamic radio preselected from `teTableMatch`, the widget mapping form with the "I have checked the column names and types" box, the `NO_CANCEL` caption and spinner, and "Upload all" for several files. Results use `describe_result` (`st.success`, `st.warning` or `st.error`). When `version` is set, add the caption `Version {version} of dataset {dataset}`. When `schemaCheck` is not compatible, show `st.warning` listing `added`, `removed` and `changed`. Row errors go in `st.table`. The caption under the uploader says `Saved mapping templates aren't available in this version.`
- [ ] **Step 4: Run** `python -m pytest tests/unit -q -k streamlit`. Expected: all pass.
- [ ] **Step 5: Port the browser tests** and run them as in `e2e/README.md`. Expected: all pass, with the cases for size refusal, non-UTF-8 refusal, T&E preselect, version 2 and duplicate included.
- [ ] **Step 6: Delete** `spikes/streamlit_upload/`. Commit `feat(streamlit): upload and preview screen (#255)`.

---

### Task 7: Point the accessibility job at Streamlit (#168)

This must be finished before React is deleted (Task 9).

**Files:**
- Modify: `tests/accessibility/conftest.py` (start `python -m streamlit run app.py --server.port <free> --server.headless true` in `streamlit_app/`, with `API_URL` pointed at `stub_api`, instead of `npm run dev`; `A11Y_BASE_URL` still overrides); `tests/accessibility/stub_api.py` (add any endpoint the Streamlit screens call that it lacks); `tests/accessibility/test_accessibility.py` (scenarios: sign-in, sign-in after a failure, home, upload with nothing chosen, review, import history with entries); `tests/accessibility/known_violations.json` (re-baselined); `.github/workflows/quality-gate.yml` `accessibility` job (drop the Node setup and `npm ci`, install `streamlit_app/requirements.txt`)

- [ ] **Step 1: Rewrite** the scenarios and the fixture. Keep the "a missing prerequisite fails" policy.
- [ ] **Step 2: Run** `python -m pytest tests/accessibility -m accessibility -q` and record the violations it finds in `known_violations.json`. Expected: PASS against the new baseline.
- [ ] **Step 3: Note** in `tests/accessibility/README.md` that `st.dataframe` draws on a canvas axe can't see into. Commit `test(a11y): scan the Streamlit app (#168)`.

---

### Task 8: Offline bundle (#256, on-premises half)

**Gate:** start only once the #60 dry run of the current React bundle has its evidence posted. The Azure half waits for assumption 3.

**Files:**
- Modify: `scripts/offline/build_bundle.sh` (delete the "3/4 frontend" Node build; `pip download -r streamlit_app/requirements.txt` into the same wheel folder with the same flags; copy `streamlit_app/` into the bundle; drop `nodejs` from `PKGS`); `scripts/offline/install.sh` (drop `nodejs`, the frontend copy and the `__OFFLINE_API_BASE__` sed; install the wheels into the existing venv; the `te-frontend` unit becomes `te-streamlit`: `WorkingDirectory=$DEST/streamlit_app`, `Environment=API_URL=http://$API_HOST:8000`, `ExecStart=$DEST/venv/bin/python -m streamlit run app.py --server.port 8080 --server.address 0.0.0.0 --server.headless true`; port 8080 is kept so the URL doesn't change); `scripts/offline/smoke_test.sh` (the frontend check becomes `curl -sf "$FE/_stcore/health"` returning `ok`); `docs/offline-install.md`
- Test: `tests/unit/test_offline_streamlit.py`

- [ ] **Step 1: Write the failing tests:** the bundle and install scripts contain no `nodejs`, `npm` or `__OFFLINE_API_BASE__`; `install.sh` writes `te-streamlit.service` with `--server.port 8080`; the smoke test checks `/_stcore/health`.
- [ ] **Step 2: Run** `python -m pytest tests/unit/test_offline_streamlit.py -q`. Expected: FAIL, then implement, then PASS.
- [ ] **Step 3: Manual (owner):** a clean-VM dry run with #60's evidence (all PASS lines in `install.log`, proof of no outside network **including from Streamlit with telemetry off**, the bundle commit, `lsb_release -d`, the date). Post it on #256.
- [ ] **Step 4: Commit** `build(offline): ship Streamlit instead of the Node frontend (#256)`.

---

### Task 9: Cutover, then delete React (#257)

Two releases.

**Release N:** the docs (`README.md`, `docs/QUICKSTART.md`, `docs/STARTER_GUIDE.md`) point at Streamlit. The release notes tell users three things: the history now comes from the server, saved mapping templates are gone, and non-UTF-8 files are refused. React still builds and runs as the rollback.

**Release N+1:** delete `csv-table-hub-main/`, `e2e/test_react_ui.py`, the Node steps in CI and `container/frontend.Dockerfile`. In `container/docker-compose.yml`, the `frontend` service gets a Streamlit image (python:3.12-slim with `pip install -r streamlit_app/requirements.txt`); otherwise the paused container bundle (#128) has no front end. Also remove the frontend-test rows in `docs/ISSUE_TESTS.md`, and the mentions of React and Lovable in `docs/`.

- [ ] **Step 1 (N):** update the docs and the release notes. Commit `docs: Streamlit is the default front end (#257)`.
- [ ] **Step 2 (N+1):** delete everything listed above. Run `git grep -n -e csv-table-hub-main -e vitest -e "npm "`. Expected: hits only in `DECISIONS/` and other historical records.
- [ ] **Step 3:** run `python -m pytest tests/ -m "not accessibility" -q` and the accessibility job. Expected: both green. Commit `chore: remove the React front end (#257)`.

---

## Not in this plan

- The Azure deployment of Streamlit (waiting on assumption 3).
- OIDC in the UI.
- A screen for the server's audit log.
- A UI for the staged-import workflow.
- WebSockets behind a proxy, several tabs at once, memory near 50 MiB, and screen readers. These are listed as untested in the spec. Check them on the #256 dry-run VM where possible.
