"""WCAG 2.1 A and AA scans of the frontend's main pages, with axe-core in Chromium (#168).

Run locally:   python -m pytest tests/accessibility -v
Needs:         pip install -r requirements-a11y.txt && python -m playwright install chromium
               (cd csv-table-hub-main && npm ci)
In CI:         the ``accessibility`` job of .github/workflows/quality-gate.yml, and only there;
               the integration job runs with ``-m "not accessibility"``.

Each test opens a page in a state worth checking, WAITS FOR CONTENT THAT PROVES THE PAGE
RENDERED (a redirect to the sign-in page or an error screen would otherwise scan clean),
and then scans. Results are judged against known_violations.json; see README.md in this
folder for what that means, and why scans of an unfixed frontend still pass today.
"""
from __future__ import annotations

import pytest

from tests.accessibility import stub_api

CSV = {"name": "people.csv", "mimeType": "text/csv", "buffer": b"id,name\n1,a\n2,b\n"}
NOT_CSV = {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"not a csv"}
TIMEOUT_MS = 15_000


def _shows(page, text: str):
    page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=TIMEOUT_MS)


def test_sign_in_page(open_page, scan):
    """The sign-in page, before anyone is signed in."""
    page = open_page("/auth", signed_in=False)
    _shows(page, "Sign in to CSV Migrator")
    scan(page, "sign_in")


def test_sign_in_page_after_a_failed_attempt(open_page, scan):
    """The sign-in page showing the server's refusal."""
    page = open_page("/auth", signed_in=False)
    page.get_by_label("Tenant").fill("acme")
    page.get_by_label("Username").fill("ada")
    page.get_by_label("Password").fill("not-the-password")
    page.get_by_role("button", name="Sign in").click()
    _shows(page, "Invalid tenant, username or password")
    scan(page, "sign_in_failed")


def test_upload_page_with_nothing_uploaded_yet(open_page, scan):
    """The upload page for a new tenant: no migrated files and no import history."""
    page = open_page("/", responses={"/api/csv/files": []})
    _shows(page, "No files yet")
    scan(page, "upload_page_empty")


def test_upload_page_with_files_and_import_history(open_page, scan):
    """The upload page with a migrated file and one import of each kind (done, failed, duplicate)."""
    page = open_page("/", jobs=stub_api.JOBS)
    _shows(page, "orders.csv")
    _shows(page, "dup.csv")
    scan(page, "upload_page_with_history")


def test_upload_page_failed_upload_attempts(open_page, scan):
    """The upload page's list of every attempt, with a failed, a partly imported and a rejected one."""
    page = open_page("/", responses={"/api/csv/uploads": stub_api.UPLOADS})
    _shows(page, "Upload attempts")
    _shows(page, "orders.csv")
    scan(page, "upload_page_failed_attempts")


def test_upload_page_column_mapping_dialog(open_page, scan):
    """The dialog that opens when a CSV is chosen: column names and the type of each."""
    page = open_page("/")
    page.set_input_files("input[type=file]", files=[CSV])
    _shows(page, "Preview: people.csv")
    scan(page, "upload_mapping_dialog")


def test_upload_page_rejection_toast(open_page, scan):
    """The toast shown when a file that is not a CSV is chosen."""
    page = open_page("/")
    page.set_input_files("input[type=file]", files=[NOT_CSV])
    _shows(page, "Please drop .csv files.")
    scan(page, "upload_page_toast")


def test_audit_log_with_history(open_page, scan):
    """The audit log listing one import of each kind."""
    page = open_page("/audit", jobs=stub_api.JOBS)
    _shows(page, "orders.csv")
    _shows(page, "dup.csv")
    scan(page, "audit_log_with_history")


def test_audit_log_report_menu(open_page, scan):
    """The audit log with its report-download menu open."""
    page = open_page("/audit", jobs=stub_api.JOBS)
    _shows(page, "orders.csv")
    page.get_by_role("button", name="Audit report").click()
    page.get_by_role("menuitem").first.wait_for(state="visible", timeout=TIMEOUT_MS)
    scan(page, "audit_log_report_menu")


def test_review_page(open_page, scan):
    """The review screen for one stored upload, with a row that failed validation."""
    page = open_page("/review/101")
    _shows(page, "Bob")
    scan(page, "review_page")


@pytest.mark.parametrize("path", ["/", "/audit", "/review/101"])
def test_signed_out_visitors_are_sent_to_sign_in(open_page, path):
    """A page that needs a session sends a visitor with none to the sign-in page.

    This guards the other scenarios: a scan of a page that silently redirected would
    be a scan of the sign-in page and pass for the wrong reason.
    """
    page = open_page(path, signed_in=False)
    page.wait_for_url("**/auth", timeout=TIMEOUT_MS)
    _shows(page, "Sign in to CSV Migrator")
