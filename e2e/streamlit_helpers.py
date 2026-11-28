"""Helpers the Streamlit browser tests share (history, upload, ...): waiting for Streamlit to settle, picking from
its select boxes, opening a page of the app, and reading a download.

Streamlit re-runs the script after each action and builds the page as it goes, so a click on a control that is about
to be rebuilt is lost. Every helper here waits for the run to end first, and tries again if the page changed under it.
"""

from __future__ import annotations

import re

from conftest import shell_sign_in
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect


def idle(page) -> None:
    """Wait until the run has finished (Streamlit's "Running" indicator is gone)."""
    expect(page.locator('[data-testid="stStatusWidget"]')).to_have_count(0)


def choose_option(page, combobox: str, option: "re.Pattern | str") -> None:
    """Open a Streamlit select box and pick an option, trying again if the page rebuilt the box under the click."""
    for attempt in range(3):
        idle(page)
        page.get_by_role("combobox", name=combobox).click()
        choice = page.get_by_role("option", name=option)
        try:
            choice.wait_for(timeout=4000)
            choice.click()
            return
        except PlaywrightTimeoutError:
            if attempt == 2:
                raise
            page.keyboard.press("Escape")


def open_page(page, stack, who: str, link: str, heading: str) -> None:
    """Sign in and go to a page of the app by its link in the sidebar."""
    shell_sign_in(page, stack, who)
    page.locator('[data-testid="stSidebar"]').get_by_role("link", name=link).click()
    page.get_by_role("heading", name=heading, exact=True).wait_for()
    idle(page)


def click_and_download(page, button, timeout: int = 20_000) -> bytes:
    """Click a download button and return the bytes of the file the browser saved."""
    with page.expect_download(timeout=timeout) as taken:
        button.click()
    with open(taken.value.path(), "rb") as saved:
        return saved.read()
