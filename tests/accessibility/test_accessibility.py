"""Accessibility tests — WCAG 2.1 A/AA checks on the React frontend using
Playwright (real Chromium) and axe-core, plus keyboard and semantics checks
axe cannot make on its own.

The backend is mocked (see conftest.py), so pages render with realistic data:
12 migrated files (two pages of the table), the 12 T&E tables, and a seeded
import history.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.accessibility

WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
# name -> (path, text that is visible once the page has rendered)
PAGES = {
    "home": ("/", "Migrated files"),
    "import history": ("/audit", "Import history"),
    "auth": ("/auth", "Authentication disabled"),
    "not found": ("/no-such-page", "Page not found"),
}
CSV = b"name,org_type,country\nACME,prime,AU\nBETA,academic,AU\n"


def _axe(page, context=None):
    from axe_playwright_python.sync_playwright import Axe

    options = {"runOnly": {"type": "tag", "values": WCAG_TAGS}}
    return Axe().run(page, context=context, options=options)


def _assert_no_violations(results, where: str):
    violations = results.response["violations"]
    if violations:
        lines = [f"{len(violations)} WCAG violation(s) on {where}:"]
        for v in violations:
            lines.append(f"  [{v['impact']}] {v['id']}: {v['help']} ({v['helpUrl']})")
            for node in v["nodes"][:3]:
                lines.append(f"      {node['html'][:160]}")
        pytest.fail("\n".join(lines), pytrace=False)


def _open(page, name):
    path, ready_text = PAGES[name]
    page.goto(path, wait_until="networkidle")
    page.get_by_text(ready_text).first.wait_for()


def _open_preview_dialog(page):
    _open(page, "home")
    page.locator('input[type="file"]').set_input_files(
        {"name": "orgs.csv", "mimeType": "text/csv", "buffer": CSV})
    dialog = page.get_by_role("dialog")
    dialog.wait_for()
    return dialog


# ── Automated WCAG scans ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(PAGES))
def test_page_has_no_wcag_violations(page, name):
    """A11Y-01 every page passes axe-core WCAG 2.1 A/AA rules."""
    _open(page, name)
    _assert_no_violations(_axe(page), f"the {name} page")


def test_migrated_files_second_page_has_no_violations(page):
    """A11Y-02 the paginated Migrated files table passes after paging."""
    _open(page, "home")
    page.get_by_role("button", name="Next page").click()
    _assert_no_violations(_axe(page), "Migrated files page 2")


def test_preview_dialog_has_no_violations(page):
    """A11Y-03 the CSV preview / header-mapping dialog passes axe."""
    _open_preview_dialog(page)
    _assert_no_violations(_axe(page, context='[role="dialog"]'), "the preview dialog")


def test_te_mode_dialog_has_no_violations(page):
    """A11Y-04 the dialog in T&E-table mode (table picker) passes axe."""
    dialog = _open_preview_dialog(page)
    dialog.get_by_role("button", name="T&E table").click()
    _assert_no_violations(_axe(page, context='[role="dialog"]'), "the T&E-mode dialog")


def test_upload_report_has_no_violations(page):
    """A11Y-05 the upload report shown after an import passes axe."""
    dialog = _open_preview_dialog(page)
    dialog.get_by_role("button", name="Confirm & import").click()
    page.get_by_text("Imported", exact=True).first.wait_for()
    _assert_no_violations(_axe(page), "the upload report")


def test_table_preview_dialog_has_no_violations(page):
    """A11Y-06 the imported-table preview dialog passes axe."""
    _open(page, "home")
    page.get_by_role("button", name="Preview").first.click()
    page.get_by_role("dialog").get_by_text("Alice Nguyen").wait_for()
    _assert_no_violations(_axe(page, context='[role="dialog"]'), "the table preview dialog")


# ── Semantics ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(PAGES))
def test_document_language_and_title(page, name):
    """A11Y-07 every page declares lang and has a non-empty <title> (WCAG 3.1.1, 2.4.2)."""
    _open(page, name)
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.title().strip()


@pytest.mark.parametrize("name", ["home", "import history"])
def test_single_h1_and_no_skipped_heading_levels(page, name):
    """A11Y-08 one h1 per page and heading levels never skip (WCAG 1.3.1)."""
    _open(page, name)
    levels = page.eval_on_selector_all(
        "h1,h2,h3,h4,h5,h6", "els => els.map(e => Number(e.tagName[1]))")
    assert levels.count(1) == 1, levels
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels


@pytest.mark.parametrize("name", ["home", "import history"])
def test_every_button_and_link_has_an_accessible_name(page, name):
    """A11Y-09 icon-only controls still expose a name to screen readers (WCAG 4.1.2)."""
    _open(page, name)
    unnamed = page.evaluate("""() => [...document.querySelectorAll('button, a[href], [role=button]')]
        .filter(el => el.offsetParent !== null)
        .filter(el => !(el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')
                        || el.getAttribute('title') || el.textContent.trim()))
        .map(el => el.outerHTML.slice(0, 120))""")
    assert unnamed == [], unnamed


def test_migrated_files_table_has_column_headers(page):
    """A11Y-10 the data table exposes named column headers to assistive tech (WCAG 1.3.1).

    Read from Chromium's own accessibility tree (CDP) — that is what screen
    readers consume; Playwright's role heuristics report these <th> as cells.
    """
    _open(page, "home")
    cdp = page.context.new_cdp_session(page)
    nodes = cdp.send("Accessibility.getFullAXTree")["nodes"]
    headers = [n.get("name", {}).get("value", "") for n in nodes
               if n.get("role", {}).get("value") == "columnheader"]
    assert {"File", "Table", "Cols", "Rows", "Uploaded"} <= set(headers), headers


# ── Keyboard ─────────────────────────────────────────────────────────────────

def test_choose_files_is_reachable_by_keyboard(page):
    """A11Y-11 Tab reaches the Choose files button and focus is visible (WCAG 2.1.1, 2.4.7)."""
    _open(page, "home")
    for _ in range(15):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.textContent.trim()") == "Choose files":
            break
    else:
        pytest.fail("Choose files was not reached within 15 Tab presses")
    outline = page.evaluate("""() => { const s = getComputedStyle(document.activeElement);
        return s.outlineStyle !== 'none' || s.boxShadow !== 'none'; }""")
    assert outline, "focused button has no visible focus indicator"


def test_dialog_traps_focus_and_escape_closes(page):
    """A11Y-12 focus stays inside the open dialog and Escape dismisses it (WCAG 2.1.2)."""
    dialog = _open_preview_dialog(page)
    for _ in range(25):
        page.keyboard.press("Tab")
        inside = page.evaluate("!!document.activeElement.closest('[role=dialog]')")
        assert inside, "focus escaped the modal dialog"
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")


def test_pagination_is_operable_by_keyboard(page):
    """A11Y-13 the table pager works with Enter on a focused button."""
    _open(page, "home")
    page.get_by_role("button", name="Next page").focus()
    page.keyboard.press("Enter")
    page.locator("table").get_by_text("customers_51.csv").wait_for()


# ── Reflow / zoom ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["home", "import history"])
def test_reflows_at_320_css_pixels(browser, frontend_url, name):
    """A11Y-14 at 320px wide (400% zoom equivalent) the page does not scroll
    horizontally (WCAG 1.4.10 Reflow). Data tables may scroll inside their own
    container, which WCAG permits."""
    from tests.accessibility.conftest import _mock_api

    ctx = browser.new_context(base_url=frontend_url, viewport={"width": 320, "height": 640})
    ctx.route("**/api/**", _mock_api)
    pg = ctx.new_page()
    try:
        _open(pg, name)
        overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"page is {overflow}px wider than the 320px viewport"
    finally:
        ctx.close()
