"""The #254 spike (spikes/streamlit_upload/) in a real browser, against the real API.

One test per question in the issue. These are findings as much as tests: where something strained, the
test records how, and README.md in the spike folder summarises. Throwaway, like the spike.
"""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import uuid

import pytest
import requests
from playwright.sync_api import expect

from api.db import Conn
from api.tenancy import schema_for
from conftest import PASSWORD, ROOT, _wait_for

SPIKE_PORT = 8503
NO_CANCEL = "Sent to the server; it can't be stopped now"
MIB = 1024 * 1024
ORGS = (ROOT / "docs" / "samples" / "orgs_sample.csv").read_bytes()


@pytest.fixture(scope="module")
def spike(stack):
    url = f"http://127.0.0.1:{SPIKE_PORT}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
         "--server.port", str(SPIKE_PORT)],
        cwd=ROOT / "spikes" / "streamlit_upload", env={**os.environ, "API_URL": stack.api},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        _wait_for(f"{url}/_stcore/health", "the upload spike")
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            os.killpg(proc.pid, signal.SIGKILL)


def _open(page, stack, spike, who="uploader"):
    a = stack.accounts[who]
    page.goto(spike)
    page.get_by_label("Tenant").fill(a.tenant)
    page.get_by_label("Username").fill(a.username)
    page.get_by_role("textbox", name="Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("heading", name="Upload and preview (spike)").wait_for()


def _csv(name: str, body: str) -> dict:
    return {"name": name, "mimeType": "text/csv", "buffer": body.encode()}


def _unique(stem: str) -> str:
    return f"{stem}_{uuid.uuid4().hex[:6]}.csv"


def _people(n: int = 6, salt: str | None = None) -> str:
    salt = salt or uuid.uuid4().hex[:6]
    return "id,name,amount\n" + "".join(f"{i},person{i}_{salt},{i * 10}\n" for i in range(1, n + 1))


def _sized_csv(tmp_path, name: str, size: int):
    """A valid CSV of exactly `size` bytes, as a file on disk (Playwright refuses buffers over 50 MB)."""
    head = b"a,b\n"
    line = b"x,y\n"
    body = head + line * ((size - len(head)) // len(line))
    body += b"z" * (size - len(body))  # pad the last cell so the size is exact
    path = tmp_path / name
    path.write_bytes(body)
    assert path.stat().st_size == size
    return path


def _column_types(stack, table: str) -> dict[str, str]:
    """What the database itself says the columns are (not what the API says it did)."""
    with Conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s", (schema_for(stack.accounts["uploader"].tenant), table))
        return dict(cur.fetchall())


def _files_of(stack, who="uploader") -> list[dict]:
    res = requests.get(f"{stack.api}/api/csv/files", timeout=30,
                       headers={"Authorization": f"Bearer {stack.token(who)}"})
    res.raise_for_status()
    return res.json()


# ── Q1: the size limit ────────────────────────────────────────────────────────────────────

def test_q1_streamlit_counts_megabytes_in_millions_so_maxuploadsize_50_is_not_the_apis_50_mib(
        page, stack, spike, tmp_path):
    """FINDING. The API's limit is 50 MiB (52,428,800 bytes) of text. `server.maxUploadSize = 50` is not that:
    Streamlit counts 50 MB as 50,000,000 bytes, so there is a 2.4 MB band the API would take and the
    uploader refuses. The two limits are separate settings and cannot be made equal with one integer."""
    _open(page, stack, spike)
    under = _sized_csv(tmp_path, _unique("under_50mb"), 49_900_000)
    inside_the_band = _sized_csv(tmp_path, _unique("band"), 51_000_000)  # over 50 MB, under 50 MiB
    assert 50_000_000 < 51_000_000 < 50 * MIB

    page.locator('input[type="file"]').set_input_files(under)
    expect(page.get_by_text(under.name, exact=False).first).to_be_visible()
    expect(page.get_by_text("File must be", exact=False)).to_have_count(0)

    page.locator('input[type="file"]').set_input_files(inside_the_band)
    expect(page.get_by_text("File must be 50.0MB or smaller", exact=False).first).to_be_visible()


def test_q1_a_file_over_the_uploaders_limit_is_refused_with_a_clear_message_and_no_upload_button(
        page, stack, spike, tmp_path):
    _open(page, stack, spike)
    over = _sized_csv(tmp_path, _unique("too_big"), 53_000_000)

    page.locator('input[type="file"]').set_input_files(over)

    expect(page.get_by_text("File must be 50.0MB or smaller", exact=False).first).to_be_visible()
    expect(page.get_by_role("button", name="Upload too_big", exact=False)).to_have_count(0)


def test_q1_the_api_refuses_just_over_its_limit_whatever_the_front_end_does(stack):
    """The API's limit is the one that is enforced: 413 "File too large" on text over 50 MiB."""
    headers = {"Authorization": f"Bearer {stack.token('uploader')}"}
    over = "a,b\n" + "x,y\n" * ((50 * MIB) // 4 + 10)

    res = requests.post(f"{stack.api}/api/csv/preview", headers=headers, timeout=120,
                        json={"fileName": "over.csv", "content": over})

    assert res.status_code == 413 and "too large" in res.text.lower(), (res.status_code, res.text[:200])


# ── Q2: renaming headers and choosing types ───────────────────────────────────────────────

def test_q2_ordinary_widgets_rename_and_retype_and_the_api_stores_exactly_that(page, stack, spike):
    name = _unique("widgets")
    body = _people()
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files(_csv(name, body))
    page.get_by_text("Use ordinary widgets instead of the grid editor").click()

    page.get_by_label("Rename name").fill("full_name")
    page.get_by_label("Type of amount").click()
    page.get_by_role("option", name="text", exact=True).click()
    upload = page.get_by_role("button", name=f"Upload {name}")
    expect(upload).to_be_disabled()  # not until the types are confirmed (#195)
    page.get_by_text("I have checked the column names and types").click()
    expect(upload).to_be_enabled()
    upload.click()

    expect(page.get_by_text("6 of 6 rows imported")).to_be_visible()
    row = next(f for f in _files_of(stack) if f["file_name"] == name)
    assert row["column_names"] == ["id", "full_name", "amount"], row
    assert _column_types(stack, row["table_name"])["amount"] == "text"
    # #185: the stored original is the bytes the person chose, so its hash matches their copy.
    uploads = requests.get(f"{stack.api}/api/csv/uploads", timeout=30,
                           headers={"Authorization": f"Bearer {stack.token('uploader')}"}).json()
    assert next(u for u in uploads if u["file_name"] == name)["sha256"] == hashlib.sha256(body.encode()).hexdigest()


def test_q2_the_grid_editor_can_be_driven_in_a_browser_but_only_by_clicking_coordinates(page, stack, spike):
    """st.data_editor draws its cells on a canvas, so a test cannot find a cell by role or label."""
    name = _unique("grid")
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files(_csv(name, _people()))
    grid = page.locator('[data-testid="stDataFrame"]').nth(1)  # the first is the sample rows
    grid.wait_for()
    box = grid.bounding_box()
    col_w = box["width"] / 3

    # Row 2 (name), the "Rename to" column: double-click, type, Enter.
    page.mouse.dblclick(box["x"] + col_w * 1.5, box["y"] + 35 + 35 * 1 + 17)
    page.wait_for_timeout(500)  # the cell editor opens after the double-click; typing too soon is lost
    page.keyboard.type("full_name", delay=40)
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    page.get_by_text("I have checked the column names and types").click()
    page.get_by_role("button", name=f"Upload {name}").click()

    expect(page.get_by_text("6 of 6 rows imported")).to_be_visible()
    row = next(f for f in _files_of(stack) if f["file_name"] == name)
    assert row["column_names"] == ["id", "full_name", "amount"], row


def test_q2_the_grids_type_dropdown_can_be_driven_too_by_coordinates(page, stack, spike):
    name = _unique("gridtype")
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files(_csv(name, _people()))
    grid = page.locator('[data-testid="stDataFrame"]').nth(1)
    grid.wait_for()
    box = grid.bounding_box()
    col_w = box["width"] / 3

    # Row 3 (amount), the "Type" column: double-click opens the dropdown; choose "text".
    page.mouse.dblclick(box["x"] + col_w * 2.5, box["y"] + 35 + 35 * 2 + 17)
    page.wait_for_timeout(500)
    page.get_by_role("option", name="text", exact=True).click()
    page.wait_for_timeout(800)
    page.get_by_text("I have checked the column names and types").click()
    page.get_by_role("button", name=f"Upload {name}").click()

    expect(page.get_by_text("6 of 6 rows imported")).to_be_visible(timeout=20_000)
    table = next(f for f in _files_of(stack) if f["file_name"] == name)["table_name"]
    assert _column_types(stack, table)["amount"] == "text", "the grid's choice reached the table"


# ── Q3: no cancel ─────────────────────────────────────────────────────────────────────────

def test_q3_it_says_before_and_during_that_the_import_cannot_be_stopped(page, stack, spike):
    name = _unique("slow")
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files(_csv(name, _people(40000)))
    page.get_by_text("Use ordinary widgets instead of the grid editor").click()
    expect(page.get_by_text(NO_CANCEL + " (once you click Upload)")).to_be_visible()  # before
    page.get_by_text("I have checked the column names and types").click()

    page.get_by_role("button", name=f"Upload {name}").click()

    expect(page.locator('[data-testid="stSpinner"]').get_by_text(NO_CANCEL)).to_be_visible()  # during
    expect(page.get_by_text("40000 of 40000 rows imported")).to_be_visible(timeout=60_000)
    expect(page.get_by_role("button", name="Stop")).to_have_count(0)


# ── Q4: several files at once ─────────────────────────────────────────────────────────────

def test_q4_several_files_are_previewed_and_uploaded_in_turn(page, stack, spike):
    names = [_unique(f"multi{i}") for i in range(3)]
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files([_csv(n, _people(3 + i)) for i, n in enumerate(names)])
    page.get_by_text("Use ordinary widgets instead of the grid editor").click()
    for n in names:
        expect(page.get_by_text(n, exact=False).first).to_be_visible()
    checks = page.get_by_text("I have checked the column names and types")
    expect(checks).to_have_count(3)
    for i in range(3):
        checks.nth(i).click()

    page.get_by_role("button", name="Upload all").click()

    for i in range(3):
        expect(page.get_by_text(f"{3 + i} of {3 + i} rows imported")).to_be_visible(timeout=30_000)
    assert {n for n in names} <= {f["file_name"] for f in _files_of(stack)}


# ── Q5: T&E mode ──────────────────────────────────────────────────────────────────────────

def test_q5_te_mode_is_suggested_for_a_te_shaped_file_and_hides_the_mapping(page, stack, spike):
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files(
        {"name": _unique("orgs"), "mimeType": "text/csv", "buffer": ORGS})

    expect(page.get_by_role("radio", name="Test and Evaluation table")).to_be_checked()
    expect(page.get_by_text("Into table")).to_be_visible()
    expect(page.get_by_text("Rename to (blank keeps it)")).to_have_count(0)  # a mapping would be a 422 here
    expect(page.get_by_text("I have checked the column names and types")).to_have_count(0)


# ── Q6: results ───────────────────────────────────────────────────────────────────────────

def test_q6_failed_rows_are_listed_with_their_reasons(page, stack, spike):
    _open(page, stack, spike)
    page.locator('input[type="file"]').set_input_files(
        {"name": _unique("orgs_fail"), "mimeType": "text/csv", "buffer": ORGS})
    page.get_by_role("button", name="Upload orgs_fail", exact=False).click()

    expect(page.get_by_text("6 of 10 rows imported", exact=False)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("4 failed", exact=False)).to_be_visible()
    expect(page.locator('[data-testid="stDataFrame"]').last).to_be_visible()  # the row-error table


def test_q6_the_same_file_again_is_refused_and_a_changed_file_is_the_next_version(page, stack, spike):
    name = _unique("versions")
    _open(page, stack, spike)
    upload = lambda: page.get_by_role("button", name=f"Upload {name}")  # noqa: E731

    first = _people(4)
    page.locator('input[type="file"]').set_input_files(_csv(name, first))
    page.get_by_text("Use ordinary widgets instead of the grid editor").click()
    page.get_by_text("I have checked the column names and types").click()
    upload().click()
    expect(page.get_by_text("4 of 4 rows imported")).to_be_visible()
    expect(page.get_by_text("Version 1", exact=False)).to_be_visible()

    # The same bytes again: refused, nothing changed. (Streamlit keeps the file in the uploader: click again.)
    upload().click()
    expect(page.get_by_text("Already imported", exact=False)).to_be_visible()

    # Same name, changed content: the next version. (Remove the first file from the uploader, as a person would.)
    page.get_by_role("button", name=f"Remove {name}").click()
    page.locator('input[type="file"]').set_input_files(_csv(name, _people(5)))
    page.get_by_text("I have checked the column names and types").click()
    upload().click()
    expect(page.get_by_text("Version 2", exact=False)).to_be_visible(timeout=30_000)
