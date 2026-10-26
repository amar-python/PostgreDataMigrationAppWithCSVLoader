"""API key authentication dependency.

Applied per-router — see the ``dependencies=[Depends(require_api_key)]`` argument
in ``api/routers/{csv,te,audit}_routes.py``. It is deliberately NOT applied at app
level so ``/api/health`` stays reachable for uptime probes without the shared
secret (BUG-035).

Fail-closed behaviour: an empty ``settings.API_KEY`` leaves these routers open.
That is tolerated only when ``API_ENV`` is ``dev``; any other value makes a
missing key a startup failure in ``api/main.py`` lifespan (O-03), so this
function can never silently wave traffic through in a deployed environment.
"""

import secrets
from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from api.config import settings
from api.db import Conn
from api.services.accounts import session_for
from api.tenancy import schema_for, scoped


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.API_KEY:
        # No key configured — only acceptable for local dev (see config.py comment).
        return
    if not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


def bearer_token(authorization: str = Header(default="")) -> str:
    """The token from an ``Authorization: Bearer <token>`` header, or 401."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in required")
    return token.strip()


def require_session(token: str = Depends(bearer_token)) -> dict:
    """The caller's live session (user, tenant, role), or 401 (M2a, #92).

    Data routers use ``tenant_scope``, which also routes to the tenant's schema.
    """
    return _live_session(token)


def _live_session(token: str) -> dict:
    with Conn() as conn, conn.cursor() as cur:
        session = session_for(cur, token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid; sign in again")
    return session


async def tenant_scope(authorization: str = Header(default=""),
                       x_api_key: str = Header(default="")) -> AsyncIterator[dict | None]:
    """Route the request to one tenant's schema (M2b, #93).

    With ``Authorization: Bearer <token>`` the request runs in the signed-in
    tenant's schema and yields its session. Without one, the shared API key
    applies and the request keeps the deployment's default schemas.

    Async on purpose: the schema is a context variable, and only an async
    dependency sets it in the context the endpoint's worker thread copies.
    """
    if not authorization:
        require_api_key(x_api_key)
        yield None
        return
    session = await run_in_threadpool(_live_session, bearer_token(authorization))
    with scoped(schema_for(session["tenant"])):
        yield session
