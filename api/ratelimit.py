"""Dependency-free per-client sliding-window rate limiting (O-03).

Why hand-rolled rather than slowapi
-----------------------------------
The API runs as a single Container App instance behind an environment boundary
(``external_enabled = false``), so a shared Redis-backed limiter would add a
dependency and a network hop for no extra protection. This module needs no
third-party package, which also keeps the air-gapped install path simple.

If the deployment ever scales past one instance, replace this with a
Redis-backed limiter: per-instance counters stop being a global limit.

Algorithm
---------
A sliding window per (client, scope). Each request appends ``now`` to a deque
and drops entries older than ``window_seconds``; the request is refused when the
deque is already at ``max_requests``. Memory is bounded by evicting idle client
buckets once ``_MAX_TRACKED_CLIENTS`` is exceeded, so a spray of spoofed IPs
cannot grow the table without limit.

Mutating routes get a tighter budget than reads because an upload costs far more
server work than a ``SELECT``.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from api.config import settings

# Hard cap on distinct client buckets held in memory.
_MAX_TRACKED_CLIENTS = 4096


class SlidingWindowLimiter:
    """Thread-safe sliding-window counter keyed by (client, scope)."""

    def __init__(self) -> None:
        self._buckets: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, client: str, scope: str, max_requests: int,
              window_seconds: float, now: float | None = None) -> tuple[bool, float]:
        """Record a hit and report whether it is allowed.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is 0
        when allowed. A non-positive ``max_requests`` disables the limit.
        """
        if max_requests <= 0:
            return True, 0.0
        stamp = time.monotonic() if now is None else now
        cutoff = stamp - window_seconds
        key = (client, scope)
        with self._lock:
            hits = self._buckets.get(key)
            if hits is None:
                hits = deque()
                self._buckets[key] = hits
            self._buckets.move_to_end(key)
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= max_requests:
                # Oldest hit in the window decides when a slot frees up.
                retry_after = max(0.0, hits[0] + window_seconds - stamp)
                return False, retry_after
            hits.append(stamp)
            # Evict least-recently-used idle buckets to bound memory.
            while len(self._buckets) > _MAX_TRACKED_CLIENTS:
                self._buckets.popitem(last=False)
            return True, 0.0

    def reset(self) -> None:
        """Drop all state. Used by tests to isolate cases."""
        with self._lock:
            self._buckets.clear()


limiter = SlidingWindowLimiter()

# Never rate-limited: uptime probes must not be throttled, and the OpenAPI docs
# are static. /api/health is already unauthenticated by design (BUG-035).
_EXEMPT_PATHS = frozenset({"/api/health", "/openapi.json", "/docs", "/redoc"})


def _client_id(request: Request) -> str:
    """Identify the caller.

    Prefers the API key (a deployed caller's stable identity) over the socket
    address, because several callers can share one NAT address. Falls back to
    the peer IP. ``X-Forwarded-For`` is deliberately ignored: it is
    client-controlled, so trusting it would let anyone bypass the limit by
    varying the header.
    """
    api_key = request.headers.get("x-api-key")
    if api_key:
        return f"key:{api_key[:8]}"
    client = request.client
    return f"ip:{client.host}" if client and client.host else "ip:unknown"


async def rate_limit_middleware(request: Request, call_next):
    """Apply the read or write budget, then hand off to the route."""
    if request.url.path in _EXEMPT_PATHS:
        return await call_next(request)

    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        scope, budget = "write", settings.RATE_LIMIT_WRITES_PER_MINUTE
    else:
        scope, budget = "read", settings.RATE_LIMIT_READS_PER_MINUTE

    allowed, retry_after = limiter.check(
        _client_id(request), scope, budget, 60.0
    )
    if not allowed:
        # Integer seconds, minimum 1 — Retry-After: 0 tells a client to retry
        # instantly, which would defeat the limit.
        seconds = max(1, int(retry_after + 0.999))
        return JSONResponse(
            status_code=429,
            content={
                "detail": (
                    f"Rate limit exceeded for {scope} requests "
                    f"({budget}/minute). Retry in {seconds}s."
                )
            },
            headers={"Retry-After": str(seconds)},
        )
    return await call_next(request)
