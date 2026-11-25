"""Request-body size limit, applied before anything parses the body (#290, OIT-005, BR-53).

Every size check on an upload (``MAX_UPLOAD_BYTES``) runs on the parsed JSON, so before this an authenticated caller
could make the API read and buffer a body of any size before a check ran. ``BodyLimitMiddleware`` is pure ASGI and
sits in front of the routes:

* a ``Content-Length`` over the cap is answered 413 at once, without reading any of the body;
* a body with no ``Content-Length`` (chunked) or a wrong one is counted as it arrives. When the cap is passed the
  middleware answers 413 and tells the handler the client has gone, so reading stops there and the rest is never
  buffered;
* the handler is not entered for a refused ``Content-Length``, and gets nothing past the cap otherwise.

The cap is just under twice ``MAX_UPLOAD_BYTES``. A text file travels inside JSON, which escapes quotes and line
breaks (a fully quoted CSV is about 1.7 times its size), and base64 adds a third, so a tighter cap would refuse files
that are within the file limit. The routes keep their own exact checks on the decoded file as a second line of defence.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.config import settings

_REFUSAL = b'{"detail":"Request body too large"}'


def max_body_bytes() -> int:
    """The largest request body let through: just under twice the file limit (a body of 2 x the limit is refused)."""
    return 2 * settings.MAX_UPLOAD_BYTES - 1


def _declared_length(scope: Scope) -> int | None:
    """The request's ``Content-Length``, or None if it has none or it is not a usable number."""
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                length = int(value)
            except ValueError:
                return None
            return length if length >= 0 else None
    return None


async def _refuse(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_REFUSAL)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _REFUSAL})


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = max_body_bytes()
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await _refuse(send)
            return

        seen = 0
        refused = False
        started = False  # the app has begun its own response, so a 413 can no longer be sent

        async def limited_receive() -> Message:
            nonlocal seen, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit and not started:
                    refused = True
                    await _refuse(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if refused:
                return  # the handler's own, late answer to a request we already refused
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not refused:
                raise
            # The handler stopped when told the client had gone; the 413 is already sent.
