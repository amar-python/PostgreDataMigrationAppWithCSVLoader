"""The Streamlit upload screen (#255) in a real browser, against the real API, inside the app shell."""

from __future__ import annotations

import hashlib
import uuid

import requests
from playwright.sync_api import expect

from api.db import Conn
from api.tenancy import schema_for
from conftest import ROOT, shell_sign_in

NO_CANCEL = "Sent to the server; it can't be stopped now"
MIB = 1024 * 1024
ORGS = (ROOT / "docs" / "samples" / "orgs_sample.csv").read_bytes()


def _open(page, stack, who="uploader"):
    shell_sign_in(page, stack, who)
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name="Upload").click()
    page.get_by_role("heading", name="Upload", exact=True).wait_for()


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


# ── the size limit ────────────────────────────────────────────────────────────────────

def test_q1_a_file_over_the_uploaders_own_limit_is_refused_and_has_no_upload_button(page, stack, tmp_path):
    """The uploader's limit (53 MB, config.toml) is above the API's, so it only stops the very large."""
    _open(page, stack)
    over = _sized_csv(tmp_path, _unique("too_big"), 54_000_000)

    page.locator('input[type="file"]').set_input_files(over)

    expect(page.get_by_text("File must be 53.0MB or smaller", exact=False).first).to_be_visible()
    expect(page.get_by_role("button", name="Upload too_big", exact=False)).to_have_count(0)


def test_q1_the_app_enforces_the_apis_real_limit_in_its_own_words(page, stack, tmp_path):
    """Over 50 MiB (52,428,800) but under the uploader's 53 MB: the app refuses it, with no preview call."""
    _open(page, stack)
    over = _sized_csv(tmp_path, _unique("band"), 52_600_000)

    page.locator('input[type="file"]').set_input_files(over)

    expect(page.get_by_text(f"{over.name} is larger than the 50 MB the server accepts.")).to_be_visible()
    expect(page.get_by_role("button", name="Upload band", exact=False)).to_have_count(0)


def test_q1_a_file_that_is_not_utf8_is_refused_with_how_to_fix_it(page, stack):
    name = _unique("latin1")
    _open(page, stack)

    page.locator('input[type="file"]').set_input_files(
        {"name": name, "mimeType": "text/csv", "buffer": "name\nétoile\n".encode("latin-1")})

    expect(page.get_by_text(f'{name} isn\'t UTF-8 text. Save it as "CSV UTF-8" and try again.')).to_be_visible()
    expect(page.get_by_role("button", name=f"Upload {name}")).to_have_count(0)


def test_q1_the_api_refuses_just_over_its_limit_whatever_the_front_end_does(stack):
    """The API's limit is the one that is enforced: 413 "File too large" on text over 50 MiB."""
    headers = {"Authorization": f"Bearer {stack.token('uploader')}"}
    over = "a,b\n" + "x,y\n" * ((50 * MIB) // 4 + 10)

    res = requests.post(f"{stack.api}/api/csv/preview", headers=headers, timeout=120,
                        json={"fileName": "over.csv", "content": over})

    assert res.status_code == 413 and "too large" in res.text.lower(), (res.status_code, res.text[:200])


# ── Q2: renaming headers and choosing types ───────────────────────────────────────────────

def test_q2_ordinary_widgets_rename_and_retype_and_the_api_stores_exactly_that(page, stack):
    name = _unique("widgets")
    body = _people()
    _open(page, stack)
    page.locator('input[type="file"]').set_input_files(_csv(name, body))

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


# ── Q3: no cancel ─────────────────────────────────────────────────────────────────────────

def test_q3_it_says_before_and_during_that_the_import_cannot_be_stopped(page, stack):
    name = _unique("slow")
    _open(page, stack)
    page.locator('input[type="file"]').set_input_files(_csv(name, _people(40000)))
    expect(page.get_by_text(NO_CANCEL + " (once you click Upload)")).to_be_visible()  # before
    page.get_by_text("I have checked the column names and types").click()

    page.get_by_role("button", name=f"Upload {name}").click()

    expect(page.locator('[data-testid="stSpinner"]').get_by_text(NO_CANCEL)).to_be_visible()  # during
    expect(page.get_by_text("40000 of 40000 rows imported")).to_be_visible(timeout=60_000)
    expect(page.get_by_role("button", name="Stop")).to_have_count(0)


# ── Q4: several files at once ─────────────────────────────────────────────────────────────

def test_q4_several_files_are_previewed_and_uploaded_in_turn(page, stack):
    names = [_unique(f"multi{i}") for i in range(3)]
    _open(page, stack)
    page.locator('input[type="file"]').set_input_files([_csv(n, _people(3 + i)) for i, n in enumerate(names)])
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

def test_q5_te_mode_is_suggested_for_a_te_shaped_file_and_hides_the_mapping(page, stack):
    _open(page, stack)
    page.locator('input[type="file"]').set_input_files(
        {"name": _unique("orgs"), "mimeType": "text/csv", "buffer": ORGS})

    expect(page.get_by_role("radio", name="Test and Evaluation table")).to_be_checked()
    expect(page.get_by_text("Into table")).to_be_visible()
    expect(page.get_by_label("Rename id")).to_have_count(0)  # a mapping would be a 422 here
    expect(page.get_by_text("I have checked the column names and types")).to_have_count(0)


# ── Q6: results ───────────────────────────────────────────────────────────────────────────

def test_q6_failed_rows_are_listed_with_their_reasons(page, stack):
    _open(page, stack)
    page.locator('input[type="file"]').set_input_files(
        {"name": _unique("orgs_fail"), "mimeType": "text/csv", "buffer": ORGS})
    page.get_by_role("button", name="Upload orgs_fail", exact=False).click()

    expect(page.get_by_text("6 of 10 rows imported", exact=False)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("4 failed", exact=False)).to_be_visible()
    expect(page.locator('[data-testid="stTable"]')).to_be_visible()  # the row-error table


def test_q6_the_same_file_again_is_refused_and_a_changed_file_is_the_next_version(page, stack):
    name = _unique("versions")
    _open(page, stack)
    upload = lambda: page.get_by_role("button", name=f"Upload {name}")  # noqa: E731

    first = _people(4)
    page.locator('input[type="file"]').set_input_files(_csv(name, first))
    page.get_by_text("I have checked the column names and types").click()
    upload().click()
    expect(page.get_by_text("4 of 4 rows imported")).to_be_visible()
    expect(page.get_by_text("Version 1", exact=False)).to_be_visible()

    # The same bytes again: refused, nothing changed. (Streamlit keeps the file in the uploader: click again.)
    upload().click()
    expect(page.get_by_text("Already imported", exact=False)).to_be_visible()

    # Same name, changed content: the next version. (Remove the first file from the uploader, as a person would.)
    second = _people(5)
    page.get_by_role("button", name=f"Remove {name}").click()
    page.locator('input[type="file"]').set_input_files(_csv(name, second))
    # Wait for the NEW file's group to replace the old one before ticking its box: the two have the same name, so
    # without this the tick can land on the old group, and the new one stays unconfirmed with Upload disabled.
    expect(page.get_by_text(f"{name} · {len(second.encode()):,} bytes")).to_be_visible()
    confirm = page.get_by_text("I have checked the column names and types")
    expect(confirm).to_have_count(1)
    confirm.click()
    upload().click()
    expect(page.get_by_text("Version 2", exact=False)).to_be_visible(timeout=30_000)
