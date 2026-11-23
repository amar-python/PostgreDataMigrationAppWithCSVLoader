"""#290 (OIT-005, BR-53): a request body over the limit is refused before anything parses it.

Every size check (``MAX_UPLOAD_BYTES``) used to run on the parsed JSON, so an authenticated caller could make the
API buffer a body of any size before the check ran. ``BodyLimitMiddleware`` now refuses it first:

  * a ``Content-Length`` over the cap is answered 413 without reading a byte of the body;
  * a body with no ``Content-Length`` (chunked) or a wrong one is counted as it streams, and reading stops, with a
    413, as soon as the cap is passed: the whole body is never buffered;
  * the handler behind it is not entered for a refused request;
  * the cap is just under twice ``MAX_UPLOAD_BYTES``: JSON escaping can nearly double a text file (a fully quoted CSV is
    about 1.7 times its size), base64 adds a third, so a body of 2 x the limit is refused while any file within the
    limit still gets through to the route's own, exact check.

The middleware is driven directly at the ASGI level, so what it read and what the handler saw can be asserted, and
then through the real app, where the CORS headers and the route's own answer matter. No database is needed.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api.bodylimit import BodyLimitMiddleware, max_body_bytes
from api.config import settings
from api.main import app

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

MAX_UPLOAD = 1000            # patched in, so the tests send kilobytes, not hundreds of megabytes
CAP = 2 * MAX_UPLOAD - 1     # the largest body let through


@pytest.fixture(autouse=True)
def small_limit(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", MAX_UPLOAD)


class Run:
    """The outcome of one request driven through the middleware."""

    def __init__(self):
        self.entered = False        # the handler behind the middleware was called
        self.handler_read = 0       # bytes the handler got to read
        self.chunks_taken = 0       # chunks pulled from the client
        self.sent: list[dict] = []  # everything the middleware sent to the client

    @property
    def status(self) -> int | None:
        starts = [m for m in self.sent if m["type"] == "http.response.start"]
        return starts[0]["status"] if starts else None

    @property
    def responses(self) -> int:
        return sum(1 for m in self.sent if m["type"] == "http.response.start")

    @property
    def body(self) -> dict:
        data = b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body")
        return json.loads(data) if data else {}


def drive(chunks: list[bytes], *, content_length: int | None = None, scope_type: str = "http",
          raw_content_length: bytes | None = None) -> Run:
    run = Run()
    queue = list(chunks)

    async def inner(scope, receive, send):
        run.entered = True
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                raise RuntimeError("client went away")   # what a real handler does when told the client left
            run.handler_read += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"read": %d}' % run.handler_read})

    async def receive():
        run.chunks_taken += 1
        body = queue.pop(0) if queue else b""
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    async def send(message):
        run.sent.append(message)

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    if raw_content_length is not None:
        headers.append((b"content-length", raw_content_length))
    scope = {"type": scope_type, "method": "POST", "path": "/api/csv/upload", "headers": headers}
    asyncio.run(BodyLimitMiddleware(inner)(scope, receive, send))
    return run


def chunks_of(total: int, size: int = 400) -> list[bytes]:
    return [b"x" * min(size, total - i) for i in range(0, total, size)]


# -- the cap ---------------------------------------------------------------------------------------------------------

def test_the_cap_is_just_under_twice_the_file_limit():
    assert max_body_bytes() == CAP
    assert 2 * MAX_UPLOAD > max_body_bytes() >= MAX_UPLOAD * 4 // 3, \
        "a body of 2 x the limit is refused, but base64 of a full-size file must fit"


# -- Content-Length --------------------------------------------------------------------------------------------------

def test_a_declared_length_over_the_cap_is_refused_without_reading_the_body():
    run = drive(chunks_of(2 * MAX_UPLOAD), content_length=2 * MAX_UPLOAD)
    assert run.status == 413 and run.body == {"detail": "Request body too large"}, run.sent
    assert run.chunks_taken == 0, "not a byte of the body may be read"
    assert not run.entered, "the handler must not be entered"


def test_a_declared_length_at_the_cap_is_let_through():
    run = drive(chunks_of(CAP), content_length=CAP)
    assert run.status == 200 and run.handler_read == CAP and run.entered


# -- no Content-Length, or a wrong one ------------------------------------------------------------------------------

def test_a_chunked_body_over_the_cap_is_refused_and_reading_stops():
    chunks = chunks_of(10 * MAX_UPLOAD)           # 25 chunks, no Content-Length
    run = drive(chunks)
    assert run.status == 413 and run.body == {"detail": "Request body too large"}, run.sent
    assert run.chunks_taken < len(chunks), "the whole body must not be pulled in"
    assert run.chunks_taken <= CAP // 400 + 2, f"reading should stop right after the cap: {run.chunks_taken} chunks"
    assert run.handler_read <= CAP, "the handler must never be handed more than the cap"
    assert run.responses == 1, "one answer only: the handler's own late response is dropped"


def test_a_chunked_body_just_under_the_cap_is_let_through():
    run = drive(chunks_of(CAP))
    assert run.status == 200 and run.handler_read == CAP


def test_a_body_larger_than_its_declared_length_is_still_caught():
    run = drive(chunks_of(10 * MAX_UPLOAD), content_length=10)
    assert run.status == 413 and run.handler_read <= CAP


@pytest.mark.parametrize("raw", [b"abc", b"", b"-5", b"1e9"])
def test_an_unusable_content_length_is_ignored_and_the_body_is_counted(raw):
    over = drive(chunks_of(10 * MAX_UPLOAD), raw_content_length=raw)
    under = drive(chunks_of(300), raw_content_length=raw)
    assert (over.status, under.status) == (413, 200)


# -- what it leaves alone --------------------------------------------------------------------------------------------

def test_a_request_without_a_body_passes_through():
    run = drive([])
    assert run.status == 200 and run.handler_read == 0


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_only_http_requests_are_limited(scope_type):
    run = Run()
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(BodyLimitMiddleware(inner)({"type": scope_type, "headers": []}, None, None))
    assert seen == [scope_type], run.sent


# -- through the real app --------------------------------------------------------------------------------------------

def test_the_real_app_refuses_an_oversize_body_with_the_cors_headers_a_browser_needs():
    client = TestClient(app)
    res = client.post("/api/csv/upload", content=b"x" * (2 * MAX_UPLOAD),
                      headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"})
    assert res.status_code == 413 and res.json() == {"detail": "Request body too large"}, res.text
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173", \
        "without CORS headers the browser cannot read the 413"


def test_the_real_app_hands_a_body_within_the_cap_to_the_route():
    client = TestClient(app)
    res = client.post("/api/csv/upload", content=b"{}", headers={"Content-Type": "application/json"})
    assert res.status_code != 413, res.text      # it reached the route, which rejects the empty request itself
