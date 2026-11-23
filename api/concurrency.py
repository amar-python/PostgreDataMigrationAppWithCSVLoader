"""Bound the imports running at once on this API instance (#307, OIT-022, BR-58, M0 decision 1).

An upload, a stage and an import each hold a database connection for their whole load, and the pool has only
``_MAXCONN`` (8; sign-in and every other request borrow one too). Left alone, a few slow imports starve everyone else,
who then wait out ``POOL_GETCONN_TIMEOUT`` and get "Server busy". This caps how many run together
(``MAX_CONCURRENT_IMPORTS``, default 4); the next one is refused at once with 503 and ``Retry-After``, which the clients
already show as a message, rather than queued behind a pool it cannot get a connection from.

The count is per API process. A second process or instance has its own, so the limit is per instance (as the decision
says); if the API ever runs several workers, size the limit and the pool for the sum.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from fastapi import HTTPException

from api.config import settings

RETRY_AFTER_SECONDS = 5

_lock = threading.Lock()
_active = 0


def active_imports() -> int:
    """How many imports are running now."""
    return _active


def import_slot() -> Iterator[None]:
    """FastAPI dependency: hold one import slot for the request, or answer 503 when they are all taken.

    Attach it after the authentication and permission dependencies, so a request that would be refused anyway never
    takes a slot, and an unauthenticated caller cannot tell whether the server is busy. The slot is released when the
    request ends, whether it succeeds or fails.
    """
    global _active
    limit = settings.MAX_CONCURRENT_IMPORTS
    counted = limit > 0
    if counted:
        with _lock:
            if _active >= limit:
                raise HTTPException(
                    status_code=503,
                    detail=(f"Too many imports are running on this server (the limit is {limit}). "
                            f"Try again in {RETRY_AFTER_SECONDS} seconds."),
                    headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
                )
            _active += 1
    try:
        yield
    finally:
        if counted:
            with _lock:
                _active -= 1
