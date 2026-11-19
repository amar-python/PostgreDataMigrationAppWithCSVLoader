"""The Streamlit app's one way of calling the API. No Streamlit imports, so it is easy to test.

Every failure is an ApiError whose text is fit to show a person: the API's own message where it
gives one, and a plain sentence when the API cannot be reached or does not answer in time.
"""

from __future__ import annotations

import os

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 30  # for reads; a call that does real work (an import) passes its own, longer, `timeout`


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
    """The API took the request but had not answered when the wait ran out. It may well be still working on it:
    saying "can't reach the API" here would be untrue, and would invite a second import of the same file."""

    def __init__(self, seconds: float):
        super().__init__(0, f"The server did not answer within {seconds:g} seconds. It may still be working on "
                            "this, and it can't be stopped from here. Look in Import history before trying again.")


def _detail(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) and detail else (response.reason or f"HTTP {response.status_code}")


def _send(method: str, path: str, token: str | None, timeout: float | None, **kwargs) -> requests.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    wait = TIMEOUT_SECONDS if timeout is None else timeout
    try:
        response = requests.request(method, API_URL + path, headers=headers, timeout=wait, **kwargs)
    except requests.ConnectTimeout:  # never connected: the same as not being there
        raise Unreachable() from None
    except requests.Timeout:  # connected, sent, and no answer yet
        raise TimedOut(wait) from None
    except requests.RequestException:
        raise Unreachable() from None
    if response.ok:
        return response
    error = Unauthorized if response.status_code == 401 else ApiError
    raise error(response.status_code, _detail(response))


def request(method: str, path: str, token: str | None = None, timeout: float | None = None, **kwargs):
    """Call the API and return its JSON, or raise Unauthorized, Unreachable, TimedOut or ApiError."""
    return _send(method, path, token, timeout, **kwargs).json()


def download(method: str, path: str, token: str | None = None, timeout: float | None = None, **kwargs):
    """Call the API and return (the body as bytes, the response headers), for a file such as a CSV report."""
    response = _send(method, path, token, timeout, **kwargs)
    return response.content, response.headers
