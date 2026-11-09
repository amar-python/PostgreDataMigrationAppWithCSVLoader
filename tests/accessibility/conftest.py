"""Playwright + axe-core fixtures for the WCAG scans (#168).

These tests drive a real browser against a running frontend, so they are the
only category with an out-of-process prerequisite. Per the repository's no-skip
policy a missing browser or an unreachable dev server FAILS with remediation
text rather than skipping.

Run them with:

    cd csv-table-hub-main && bun run dev     # or: npm run dev
    python -m pytest tests/accessibility -v

Point them somewhere else with A11Y_BASE_URL (e.g. a preview deployment).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

BASE_URL = os.environ.get("A11Y_BASE_URL", "http://localhost:5173").rstrip("/")

# WCAG 2.1 level AA is the target (docs/STANDARDS_AUDIT.md). axe groups its
# rules by tag; these four cover A and AA for both 2.0 and 2.1. "best-practice"
# is deliberately excluded — it is advice, not the conformance target.
WCAG_21_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

_SERVER_HELP = (
    f"No frontend answered at {BASE_URL}.\n"
    "    cd csv-table-hub-main && bun install && bun run dev\n"
    "Then re-run, or set A11Y_BASE_URL to a running instance."
)

_BROWSER_HELP = (
    "Playwright could not launch Chromium.\n"
    "    python -m playwright install chromium\n"
    "(the CI job does this; see .github/workflows/quality-gate.yml)"
)


@pytest.fixture(scope="session")
def base_url() -> str:
    """The frontend under scan, verified reachable before any test runs."""
    try:
        urllib.request.urlopen(BASE_URL, timeout=15)  # nosec B310 — fixed http(s) literal
    except urllib.error.HTTPError:
        pass  # a 4xx/5xx still means something is listening and serving
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"{type(exc).__name__}: {exc}\n{_SERVER_HELP}", pytrace=False)
    return BASE_URL


@pytest.fixture(scope="session")
def browser(base_url: str):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{type(exc).__name__}: {exc}\n{_BROWSER_HELP}", pytrace=False)
        yield browser
        browser.close()


# The frontend keeps its session in sessionStorage under this key
# (csv-table-hub-main/src/lib/session.ts) and `requireSession` redirects to
# /auth without one. Seeding it lets the scans reach the authenticated pages
# without a backend or a real account.
_SESSION = {"token": "a11y-scan", "expiresAt": "2099-01-01T00:00:00Z",
            "username": "a11y", "tenant": "a11y", "role": "admin"}


def _empty_api(route):
    """Answer every /api/** call with an empty list so pages render their
    empty state instead of an error banner. The scan covers the frontend only."""
    route.fulfill(status=200, content_type="application/json", body="[]")


@pytest.fixture
def page(browser):
    """A fresh page per test, at a desktop viewport. Signed out."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def signed_in_page(browser):
    """As `page`, but with a seeded session and a stubbed API."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_init_script(
        f"sessionStorage.setItem('te.session', {json.dumps(json.dumps(_SESSION))});")
    context.route("**/api/**", _empty_api)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="session")
def axe():
    from axe_playwright_python.sync_playwright import Axe

    return Axe()
