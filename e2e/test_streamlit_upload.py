"""The Streamlit upload and imported-files screens (#255) in a real browser, against the real API.

These carry over the 11 browser tests of the #254 spike (one per question in that issue) and add what only a real page
shows: a real file chosen from a real disk, the size limits at their edges, what the database itself holds afterwards, a
spinner while the server works, the chooser emptying after an upload, the new import appearing in the history at once
(the history is cached), and how a browser draws a cell from a stranger's file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid

import requests
from openpyxl import load_workbook
from playwright.sync_api import expect

from api.db import Conn
from api.tenancy import schema_for
from conftest import ROOT
from streamlit_helpers import choose_option, click_and_download, idle, open_page

NO_CANCEL = "Sent to the server; it can't be stopped now"
CONFIRM = "I have checked the column names and types"
MIB = 1024 * 1024
ORGS = (ROOT / "docs" / "samples" / "orgs_sample.csv").read_bytes()


def _csv(name: str, body: str | bytes) -> dict:
    return {"name": name, "mimeType": "text/csv", "buffer": body if isinstance(body, bytes) else body.encode()}


def _unique(stem: str) -> str:
    return f"{stem}_{uuid.uuid4().hex[:6]}.csv"


def _people(n: int = 6, salt: str | None = None) -> str:
    """Different bytes every time: the API calls identical bytes a duplicate whatever the file is named."""
    salt = salt or uuid.uuid4().hex[:6]
    return "id,name,amount\n" + "".join(f"{i},person{i}_{salt},{i * 10}\n" for i in range(1, n + 1))


def _sized_csv(tmp_path, name: str, size: int):
    """A valid CSV of exactly `size` bytes, as a file on disk (Playwright refuses buffers over 50 MB)."""
    head, line = b"a,b\n", b"x,y\n"
    body = head + line * ((size - len(head)) // len(line))
    body += b"z" * (size - len(body))
    path = tmp_path / name
    path.write_bytes(body)
    assert path.stat().st_size == size
    return path


def _api(stack, path: str, who="uploader"):
    res = requests.get(f"{stack.api}{path}", timeout=30, headers={"Authorization": f"Bearer {stack.token(who)}"})
    res.raise_for_status()
    return res.json()


def _file_row(stack, name: str) -> dict | None:
    return next((f for f in _api(stack, "/api/csv/files") if f["file_name"] == name), None)


def _column_types(stack, table: str) -> dict[str, str]:
    """What the database itself says the columns are (not what the API says it did)."""
    with Conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s", (schema_for(stack.accounts["uploader"].tenant), table))
        return dict(cur.fetchall())


def _open(page, stack, who="uploader"):
    open_page(page, stack, who, "Upload", "Upload")


def _choose(page, *files):
    page.locator('input[type="file"]').set_input_files(list(files))
    idle(page)


def _confirm_and_upload(page, name: str):
    page.get_by_text(CONFIRM).click()
    page.get_by_role("button", name=f"Upload {name}").click()


# ── the size limit (spike Q1) ──────────────────────────────────────────────────────────────

def test_a_file_in_the_band_streamlit_would_have_refused_but_the_api_takes_is_previewed(page, stack, tmp_path):
    """The #254 finding: Streamlit counts a megabyte as 1,000,000 bytes, so with its limit at 50 a file of 51,000,000 bytes
    was refused though the API takes up to 50 MiB (52,428,800). Streamlit's limit is now 53 and the app checks the API's."""
    _open(page, stack)
    band = _sized_csv(tmp_path, _unique("band"), 51_000_000)
    assert 50_000_000 < 51_000_000 < 50 * MIB

    _choose(page, band)

    expect(page.get_by_role("button", name=re.compile(r"^Upload ")).first).to_be_visible(timeout=30_000)
    expect(page.get_by_text("File must be", exact=False)).to_have_count(0)
    expect(page.get_by_text("about", exact=False).first).to_be_visible()  # a big file is previewed from its start


def test_a_file_over_the_apis_limit_is_refused_by_the_app_in_its_own_words_before_anything_is_sent(page, stack, tmp_path):
    _open(page, stack)
    over = _sized_csv(tmp_path, _unique("too_big"), 52_900_000)  # over the API's 52,428,800, under Streamlit's 53,000,000

    _choose(page, over)

    expect(page.get_by_text("over the 50.00 MB limit", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^Upload "))).to_have_count(0)
    assert _file_row(stack, over.name) is None


def test_a_file_over_streamlits_own_limit_is_refused_too(page, stack, tmp_path):
    _open(page, stack)
    huge = _sized_csv(tmp_path, _unique("huge"), 54_000_000)

    _choose(page, huge)

    expect(page.get_by_text("File must be 53.0MB or smaller", exact=False).first).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^Upload "))).to_have_count(0)


def test_the_api_refuses_just_over_its_limit_whatever_the_front_end_does(stack):
    headers = {"Authorization": f"Bearer {stack.token('uploader')}"}
    over = "a,b\n" + "x,y\n" * ((50 * MIB) // 4 + 10)

    res = requests.post(f"{stack.api}/api/csv/preview", headers=headers, timeout=120,
                        json={"fileName": "over.csv", "content": over})

    assert res.status_code == 413 and "too large" in res.text.lower(), (res.status_code, res.text[:200])


# ── renaming headers and choosing types (Q2) ───────────────────────────────────────────────

def test_renaming_and_retyping_with_ordinary_widgets_is_stored_exactly_as_chosen(page, stack):
    name, body = _unique("widgets"), _people()
    _open(page, stack)
    _choose(page, _csv(name, body))

    page.get_by_label("Rename column 2").fill("full_name")
    choose_option(page, "Type of column 3", "Text")
    upload = page.get_by_role("button", name=f"Upload {name}")
    expect(upload).to_be_disabled()  # not until the types are confirmed (#195)
    page.get_by_text(CONFIRM).click()
    expect(upload).to_be_enabled()
    upload.click()

    expect(page.get_by_text("6 of 6 rows imported")).to_be_visible()
    row = _file_row(stack, name)
    assert row["column_names"] == ["id", "full_name", "amount"], row
    assert _column_types(stack, row["table_name"])["amount"] == "text"
    # #185: the stored original is the bytes the person chose, so its hash matches their copy.
    stored = next(u for u in _api(stack, "/api/csv/uploads") if u["file_name"] == name)
    assert stored["sha256"] == hashlib.sha256(body.encode()).hexdigest()


def test_a_rename_that_collides_is_refused_by_the_api_and_said_in_its_words_with_nothing_imported(page, stack):
    name = _unique("collide")
    _open(page, stack)
    _choose(page, _csv(name, _people()))

    page.get_by_label("Rename column 2").fill("id")  # a column that already exists
    _confirm_and_upload(page, name)

    expect(page.get_by_role("alert").or_(page.locator('[data-testid="stAlert"]')).first).to_be_visible(timeout=20_000)
    expect(page.get_by_text("rows imported")).to_have_count(0)
    assert _file_row(stack, name) is None


# ── no cancel (Q3) ─────────────────────────────────────────────────────────────────────────

def test_it_says_before_and_during_that_the_import_cannot_be_stopped_and_there_is_no_stop_button(page, stack):
    name = _unique("slow")
    _open(page, stack)
    _choose(page, _csv(name, _people(40000)))
    expect(page.get_by_text(NO_CANCEL + " (once you click Upload)")).to_be_visible()  # before
    page.get_by_text(CONFIRM).click()

    page.get_by_role("button", name=f"Upload {name}").click()

    expect(page.locator('[data-testid="stSpinner"]').get_by_text(NO_CANCEL)).to_be_visible()  # during
    expect(page.get_by_text("40000 of 40000 rows imported")).to_be_visible(timeout=60_000)
    expect(page.get_by_role("button", name="Stop")).to_have_count(0)


# ── several files (Q4) ─────────────────────────────────────────────────────────────────────

def test_several_files_are_previewed_and_uploaded_in_turn(page, stack):
    names = [_unique(f"multi{i}") for i in range(3)]
    _open(page, stack)
    _choose(page, *[_csv(n, _people(3 + i)) for i, n in enumerate(names)])
    for n in names:
        expect(page.get_by_text(n, exact=False).first).to_be_visible()
    checks = page.get_by_text(CONFIRM)
    expect(checks).to_have_count(3)
    upload_all = page.get_by_role("button", name="Upload all")
    expect(upload_all).to_be_disabled()
    for i in range(3):
        checks.nth(i).click()
    expect(upload_all).to_be_enabled()

    upload_all.click()

    for i in range(3):
        expect(page.get_by_text(f"{3 + i} of {3 + i} rows imported")).to_be_visible(timeout=30_000)
    assert set(names) <= {f["file_name"] for f in _api(stack, "/api/csv/files")}


def test_two_copies_of_the_same_bytes_are_two_files_and_the_page_does_not_crash(page, stack):
    body = _people()
    a, b = _unique("orig"), _unique("copy")
    _open(page, stack)

    _choose(page, _csv(a, body), _csv(b, body))

    expect(page.get_by_role("button", name=f"Upload {a}")).to_be_visible()
    expect(page.get_by_role("button", name=f"Upload {b}")).to_be_visible()
    expect(page.get_by_text("Something went wrong")).to_have_count(0)
    expect(page.get_by_text("DuplicateElementKey")).to_have_count(0)


# ── Test and Evaluation mode (Q5) ──────────────────────────────────────────────────────────

def test_te_mode_is_suggested_for_a_te_shaped_file_and_hides_the_mapping(page, stack):
    _open(page, stack)

    _choose(page, _csv(_unique("orgs"), ORGS))

    expect(page.get_by_role("radio", name="Test and Evaluation table")).to_be_checked()
    expect(page.get_by_text("Into table")).to_be_visible()
    expect(page.get_by_label("Rename column 1")).to_have_count(0)
    expect(page.get_by_text(CONFIRM)).to_have_count(0)  # a mapping or a confirmation would be a 422 here


# ── results (Q6) ───────────────────────────────────────────────────────────────────────────

def test_failed_rows_are_listed_with_their_reasons_and_can_be_downloaded_as_reports(page, stack):
    name = _unique("orgs_fail")
    _open(page, stack)
    _choose(page, _csv(name, ORGS))
    page.get_by_role("button", name=f"Upload {name}").click()

    # #289: a T&E file with a failing row is rejected as a whole. The page says so and names how many rows
    # failed; the failed rows are still listed with their reasons and downloadable, below.
    expect(page.get_by_text("4 of the 10 rows could not be imported", exact=False)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("nothing was saved", exact=False)).to_be_visible()
    expect(page.get_by_role("table").first).to_be_visible()  # the row errors, as a real table
    data = click_and_download(page, page.get_by_role("button", name="Error report (CSV)"))
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    assert rows[0][:5] == ["file", "row_number", "column", "value", "reason"] and len(rows) == 5, rows
    assert {r[0] for r in rows[1:]} == {name}
    sheet = load_workbook(io.BytesIO(click_and_download(page, page.get_by_role("button", name="Error report (XLSX)"))))
    assert sheet["Errors"].max_row == 5


def test_the_chooser_is_emptied_after_an_upload_so_the_file_cannot_be_sent_twice(page, stack):
    name = _unique("once")
    _open(page, stack)
    _choose(page, _csv(name, _people(4)))
    _confirm_and_upload(page, name)
    expect(page.get_by_text("4 of 4 rows imported")).to_be_visible()

    expect(page.get_by_role("button", name=f"Upload {name}")).to_have_count(0)
    expect(page.locator('[data-testid="stFileUploaderFile"]')).to_have_count(0)


def test_the_same_file_again_is_reported_as_already_imported_and_a_changed_one_is_the_next_version(page, stack):
    name = _unique("versions")
    first = _people(4)
    _open(page, stack)
    _choose(page, _csv(name, first))
    _confirm_and_upload(page, name)
    expect(page.get_by_text("4 of 4 rows imported")).to_be_visible()
    expect(page.get_by_text("Version 1 of the dataset", exact=False)).to_be_visible()

    _choose(page, _csv(name, first))  # the same bytes again
    _confirm_and_upload(page, name)
    expect(page.get_by_text("already imported", exact=False)).to_be_visible()
    expect(page.get_by_text("Nothing was changed.")).to_be_visible()

    _choose(page, _csv(name, _people(5)))  # same name, changed content
    _confirm_and_upload(page, name)
    expect(page.get_by_text("Version 2 of the dataset", exact=False)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("Columns match the previous version", exact=False)).to_be_visible()
    assert sum(f["file_name"] == name for f in _api(stack, "/api/csv/files")) == 2


# ── files the screen will not send, or sends differently ───────────────────────────────────

def test_a_file_that_is_not_utf8_is_refused_with_the_reason_and_nothing_is_imported(page, stack):
    name = _unique("latin")
    _open(page, stack)

    _choose(page, _csv(name, "name\n\xe9t\xe9\n".encode("latin-1")))

    expect(page.get_by_text("is not UTF-8 text", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name=f"Upload {name}")).to_have_count(0)
    assert _file_row(stack, name) is None


def test_a_file_with_a_byte_order_mark_loads_with_clean_headers_and_keeps_its_original_bytes(page, stack):
    name = _unique("bom")
    raw = b"\xef\xbb\xbf" + _people(3).encode()
    _open(page, stack)
    _choose(page, _csv(name, raw))

    _confirm_and_upload(page, name)

    expect(page.get_by_text("3 of 3 rows imported")).to_be_visible()
    assert _file_row(stack, name)["column_names"][0] == "id", "not \\ufeffid"
    stored = next(u for u in _api(stack, "/api/csv/uploads") if u["file_name"] == name)
    assert stored["sha256"] == hashlib.sha256(raw).hexdigest(), "the preserved original is the file, byte for byte"


# ── what other screens see, at once ────────────────────────────────────────────────────────

def test_a_new_import_is_in_the_history_and_the_files_list_at_once_even_though_both_are_cached(page, stack):
    name = _unique("fresh")
    open_page(page, stack, "uploader", "Import history", "Import history")  # fetches (and caches) the history
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Imported files").click()
    page.get_by_role("heading", name="Imported files", exact=True).wait_for()  # and the list of files
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Upload").click()
    page.get_by_role("heading", name="Upload", exact=True).wait_for()
    _choose(page, _csv(name, _people(3)))
    _confirm_and_upload(page, name)
    expect(page.get_by_text("3 of 3 rows imported")).to_be_visible()

    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Import history").click()
    expect(page.get_by_role("cell", name=name)).to_be_visible()
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Imported files").click()
    expect(page.get_by_role("cell", name=name)).to_be_visible()


def test_the_imported_files_page_previews_the_table_and_says_why_rows_failed(page, stack):
    name = _unique("lookinside")
    _open(page, stack)
    _choose(page, _csv(name, "id,name,amount\n1,ann,10\n2,bob,x\n3,cy,30\n"))
    choose_option(page, "Type of column 3", "Whole number")  # the preview saw an "x" and guessed text: the person knows better
    page.get_by_text(CONFIRM).click()
    page.get_by_role("button", name=f"Upload {name}").click()
    expect(page.get_by_text("2 of 3 rows imported")).to_be_visible()

    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Imported files").click()
    page.get_by_role("heading", name="Imported files", exact=True).wait_for()
    choose_option(page, "Look inside a file", re.compile(re.escape(name)))

    expect(page.get_by_role("heading", name=name)).to_be_visible()
    expect(page.get_by_text("The table has 2 rows in all.", exact=False)).to_be_visible()
    expect(page.get_by_text("1 of 3 rows failed validation", exact=False)).to_be_visible()
    expect(page.get_by_text("Rows that failed")).to_be_visible()
    expect(page.get_by_role("cell", name='"x" is not a whole number', exact=False)).to_be_visible()


# ── text from a file is shown as written ───────────────────────────────────────────────────

def test_a_file_name_a_header_and_a_cell_that_look_like_links_are_text_not_links(page, stack):
    link = "[click here](https://evil.example/login)"
    name = f"**bold**_{uuid.uuid4().hex[:6]}.csv"
    _open(page, stack)

    _choose(page, _csv(name, f"id,{link}\n1,{link}\n2,5\n"))

    expect(page.get_by_text("click here](https://evil.example/login)", exact=False).first).to_be_visible()
    assert page.locator('a[href*="evil.example"]').count() == 0, "a header or a cell must not become a link"
    assert page.locator("strong", has_text=re.compile(r"^bold$")).count() == 0, "a file name must not become bold"
    page.get_by_text(CONFIRM).click()
    page.get_by_role("button", name=re.compile(r"^Upload ")).click()
    expect(page.get_by_text("rows imported", exact=False)).to_be_visible(timeout=20_000)
    assert page.locator('a[href*="evil.example"]').count() == 0


# ── who sees the page ──────────────────────────────────────────────────────────────────────

def test_a_role_that_may_not_upload_is_not_offered_the_page_but_may_see_the_files(page, stack):
    open_page(page, stack, "reviewer", "Imported files", "Imported files")

    expect(page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Upload")).to_have_count(0)
    expect(page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Imported files")).to_be_visible()


def test_signing_out_leaves_no_upload_report_for_the_next_person(page, stack):
    name = _unique("private")
    _open(page, stack)
    _choose(page, _csv(name, _people(3)))
    _confirm_and_upload(page, name)
    expect(page.get_by_text("3 of 3 rows imported")).to_be_visible()
    page.locator('[data-testid="stSidebar"]').get_by_role("button", name="Sign out").click()
    page.get_by_role("heading", name="Sign in").wait_for()

    _open(page, stack, "admin")

    expect(page.get_by_text("Upload report")).to_have_count(0)
    expect(page.get_by_text(name, exact=False)).to_have_count(0)
