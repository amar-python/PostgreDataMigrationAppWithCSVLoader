"""The Streamlit app's one way of calling the API. No Streamlit imports, so it is easy to test.

Every failure is an ApiError whose text is fit to show a person: the API's own message where it
gives one, and a plain sentence when the API cannot be reached.
"""

from __future__ import annotations

import os

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 30


class ApiError(Exception):
    """The API answered with an error (or did not answer). str(e) is the message to show."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Unauthorized(ApiError):
    """HTTP 401: the session is not valid (any more), or the sign-in details were wrong."""


class Unreachable(ApiError):
    """The API did not answer at all."""

    def __init__(self):
        super().__init__(0, f"Can't reach the API at {API_URL}. Is it running?")


class TimedOut(ApiError):
    """The API did not answer in time. The work may still be going on there."""

    def __init__(self, timeout: float):
        super().__init__(0, f"The server didn't answer within {timeout:.0f} s. "
                            "It may still be working: check Import history before trying again.")


def _detail(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) and detail else (response.reason or f"HTTP {response.status_code}")


def request(method: str, path: str, token: str | None = None, timeout: float = TIMEOUT_SECONDS, **kwargs):
    """Call the API and return its JSON, or raise Unauthorized, TimedOut, Unreachable or ApiError."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = requests.request(method, API_URL + path, headers=headers, timeout=timeout, **kwargs)
    except requests.Timeout:
        raise TimedOut(timeout) from None
    except requests.RequestException:
        raise Unreachable() from None
    if response.ok:
        return response.json()
    error = Unauthorized if response.status_code == 401 else ApiError
    raise error(response.status_code, _detail(response))
