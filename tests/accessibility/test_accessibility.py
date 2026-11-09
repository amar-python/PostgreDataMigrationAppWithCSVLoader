"""WCAG 2.1 AA scans of the frontend's pages (#168).

Known limitation, stated in #168: these scans fail against the frontend's
current, unfixed accessibility issues (sonner toast contrast, selects without
accessible names, the download menu's missing aria-labels, the upload progress
bar). That is the point of the job — the failures are the backlog, and they are
expected until those fixes land. The job is deliberately NOT in branch
protection yet.

`/` and `/audit` are behind `requireSession`: signed out they redirect to
/auth, so scanning them signed out would just scan the sign-in page three times
and report a false green. The `signed_in_page` fixture seeds a session and stubs
the API, and every scan asserts it landed on the route it asked for.
"""

from __future__ import annotations

import pytest

from .conftest import WCAG_21_AA_TAGS

# (route, human name, needs a session)
PAGES = [
    ("/auth", "sign-in", False),
    ("/", "upload", True),
    ("/audit", "audit log", True),
]
IDS = [p[0] for p in PAGES]


def _open(page, base_url: str, route: str) -> None:
    page.goto(f"{base_url}{route}", wait_until="networkidle")
    # Guard against the false green: a redirect means we scanned a different page.
    assert page.url.rstrip("/") == f"{base_url}{route}".rstrip("/"), (
        f"asked for {route} but landed on {page.url}")


@pytest.fixture(params=PAGES, ids=IDS)
def target(request, page, signed_in_page):
    route, name, needs_session = request.param
    return (signed_in_page if needs_session else page), route, name


def test_page_has_no_wcag_21_aa_violations(axe, target, base_url):
    page, route, name = target
    _open(page, base_url, route)
    results = axe.run(page, options={
        "runOnly": {"type": "tag", "values": WCAG_21_AA_TAGS},
        "resultTypes": ["violations"],
    })
    assert results.violations_count == 0, (
        f"{results.violations_count} WCAG 2.1 AA violation(s) on {name} ({route}):\n"
        f"{results.generate_report()}"
    )


def test_page_has_one_main_landmark(target, base_url):
    """Landmarks are how a screen-reader user skips the page chrome."""
    page, route, name = target
    _open(page, base_url, route)
    count = page.locator("main, [role=main]").count()
    assert count == 1, f"{name} ({route}): found {count} main landmarks, expected 1"


def test_sign_in_form_fields_all_have_labels(axe, page, base_url):
    """A form you cannot label is a form a screen-reader user cannot fill in."""
    _open(page, base_url, "/auth")
    results = axe.run(page, options={
        "runOnly": {"type": "rule", "values": ["label", "form-field-multiple-labels"]},
        "resultTypes": ["violations"],
    })
    assert results.violations_count == 0, results.generate_report()
