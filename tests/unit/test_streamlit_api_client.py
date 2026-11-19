"""The Streamlit app's one way of calling the API (streamlit_app/api_client.py), with `requests` faked.

The line that matters most: a request that was sent and not answered in time (an import still running) must
not be reported as "can't reach the API". That wording would send a person to re-upload a file the server is
still importing.
"""
import pytest
import requests

from tests.unit import streamlit_harness  # noqa: F401  (puts streamlit_app on the path)

import api_client  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class Reply:
    def __init__(self, status=200, body=None, content=b"", headers=None, reason="OK"):
        self.status_code, self._body, self.content = status, body, content
        self.headers, self.reason = headers or {}, reason
        self.ok = status < 400

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


@pytest.fixture
def sent(monkeypatch):
    calls = []
    outcome = {"reply": Reply(body={"ok": True}), "raises": None}

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if outcome["raises"]:
            raise outcome["raises"]
        return outcome["reply"]

    monkeypatch.setattr(requests, "request", fake)
    return calls, outcome


def test_a_request_carries_the_token_and_the_default_wait(sent):
    calls, _ = sent

    assert api_client.request("GET", "/api/x", token="tok", params={"a": 1}) == {"ok": True}

    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", api_client.API_URL + "/api/x")
    assert kwargs["headers"] == {"Authorization": "Bearer tok"} and kwargs["timeout"] == api_client.TIMEOUT_SECONDS
    assert kwargs["params"] == {"a": 1}


def test_a_call_that_does_real_work_can_ask_for_a_longer_wait(sent):
    calls, _ = sent

    api_client.request("POST", "/api/csv/upload", token="t", timeout=600, json={})

    assert calls[0][2]["timeout"] == 600


def test_a_request_without_a_token_sends_no_authorization_header(sent):
    calls, _ = sent

    api_client.request("POST", "/api/auth/login", json={})

    assert calls[0][2]["headers"] == {}


def test_a_download_gives_the_bytes_and_the_headers(sent):
    _, outcome = sent
    outcome["reply"] = Reply(content=b"a,b\n1,2\n", headers={"X-Total-Count": "1"})

    body, headers = api_client.download("GET", "/api/audit/events", token="t", params={"format": "csv"})

    assert body == b"a,b\n1,2\n" and headers["X-Total-Count"] == "1"


def test_a_401_is_unauthorized_in_both_ways_of_calling(sent):
    _, outcome = sent
    outcome["reply"] = Reply(401, {"detail": "Not signed in"}, reason="Unauthorized")

    with pytest.raises(api_client.Unauthorized, match="Not signed in"):
        api_client.request("GET", "/x", token="t")
    with pytest.raises(api_client.Unauthorized):
        api_client.download("GET", "/x", token="t")


@pytest.mark.parametrize("reply, message", [
    (Reply(413, {"detail": "File too large"}, reason="Payload Too Large"), "File too large"),
    (Reply(500, None, reason="Internal Server Error"), "Internal Server Error"),
    (Reply(422, {"detail": ["not", "a", "string"]}, reason="Unprocessable"), "Unprocessable"),
    (Reply(502, {"detail": ""}, reason=""), "HTTP 502"),
])
def test_an_error_says_what_the_api_said_or_a_plain_fallback(sent, reply, message):
    _, outcome = sent
    outcome["reply"] = reply

    with pytest.raises(api_client.ApiError) as caught:
        api_client.request("GET", "/x")

    assert str(caught.value) == message and caught.value.status == reply.status_code
    assert not isinstance(caught.value, api_client.Unauthorized)


def test_an_api_that_is_not_there_is_unreachable(sent):
    _, outcome = sent
    outcome["raises"] = requests.ConnectionError("refused")

    with pytest.raises(api_client.Unreachable, match="Can't reach the API"):
        api_client.request("GET", "/x")


def test_never_connecting_in_time_is_unreachable_too(sent):
    _, outcome = sent
    outcome["raises"] = requests.ConnectTimeout("no route")

    with pytest.raises(api_client.Unreachable):
        api_client.request("GET", "/x")


def test_no_answer_in_time_is_not_reported_as_unreachable(sent):
    """The request got there; the server may still be importing. Say so, and say what to check first."""
    _, outcome = sent
    outcome["raises"] = requests.ReadTimeout("slow")

    with pytest.raises(api_client.TimedOut) as caught:
        api_client.request("POST", "/api/csv/upload", timeout=600)

    text = str(caught.value)
    assert not isinstance(caught.value, api_client.Unreachable) and "Can't reach" not in text
    assert "600 seconds" in text and "still be working" in text and "Import history" in text


def test_a_download_that_times_out_is_timed_out_too(sent):
    _, outcome = sent
    outcome["raises"] = requests.ReadTimeout("slow")

    with pytest.raises(api_client.TimedOut):
        api_client.download("GET", "/x", timeout=5)
