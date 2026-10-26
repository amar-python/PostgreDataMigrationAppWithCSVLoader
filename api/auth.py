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

from fastapi import Depends, Header, HTTPException

from api.config import settings
from api.db import Conn
from api.services.accounts import session_for


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

    Not yet applied to the data routers; tenant routing (#93) and the role
    matrix (#94) switch them over.
    """
    with Conn() as conn, conn.cursor() as cur:
        session = session_for(cur, token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid; sign in again")
    return session
