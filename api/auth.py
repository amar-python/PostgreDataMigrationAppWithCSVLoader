"""Authentication and authorisation dependencies.

Data routers depend on ``tenant_scope`` (directly or through ``allow``). It is
deliberately NOT applied at app level so ``/api/health`` stays reachable for
uptime probes (BUG-035).

#298 (OIT-013): there is no shared API key any more. A request needs a signed-in
session (``Authorization: Bearer <token>``), or gets 401. The only exception is
local development and tests, by explicit opt-in: ``API_ALLOW_ANONYMOUS=1`` with
``API_ENV=dev`` (see ``api/config.py``). Fail-closed: anything else, including
the default ``API_ENV=dev`` on its own, requires a session.
"""

from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Depends, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from api.config import settings
from api.db import Conn
from api.services.accounts import session_for
from api.services.audit import acting_as
from api.tenancy import tenant

ANONYMOUS_ACTOR = "anonymous"


def anonymous_allowed() -> bool:
    """True only when local dev has opted in to unauthenticated data access (#298)."""
    return settings.API_ALLOW_ANONYMOUS and settings.API_ENV == "dev"


def bearer_token(authorization: str = Header(default="")) -> str:
    """The token from an ``Authorization: Bearer <token>`` header, or 401."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in required")
    return token.strip()


def require_session(token: str = Depends(bearer_token)) -> dict[str, Any]:
    """The caller's live session (user, tenant, role), or 401 (M2a, #92).

    Data routers use ``tenant_scope``, which also routes to the tenant's schema.
    """
    return _live_session(token)


def _live_session(token: str) -> dict[str, Any]:
    with Conn() as conn, conn.cursor() as cur:
        session = session_for(cur, token)
        if session is not None:
            conn.commit()  # session_for records the use (#296); nothing else was written, and a close would roll it back
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid; sign in again")
    return session


async def tenant_scope(authorization: str = Header(default="")) -> AsyncIterator[dict[str, Any] | None]:
    """Route the request to one tenant's schema (M2b, #93).

    With ``Authorization: Bearer <token>`` the request runs in the signed-in
    tenant's schema, as the tenant's own database role (#297), and yields its session.
    Without one it gets 401 "Sign in required" (#298), unless local dev opted in to
    anonymous access; then it keeps the deployment's default schemas, yields ``None``
    and audits as ``anonymous``. Any ``X-API-Key`` header is ignored: it grants nothing.

    Async on purpose: the schema is a context variable, and only an async
    dependency sets it in the context the endpoint's worker thread copies.
    """
    if not authorization:
        if not anonymous_allowed():
            raise HTTPException(status_code=401, detail="Sign in required")
        with acting_as(ANONYMOUS_ACTOR):
            yield None
        return
    session = await run_in_threadpool(_live_session, bearer_token(authorization))
    with tenant(session["tenant"]), acting_as(session["username"]):
        yield session


# M2c (#94): which roles may perform each action. docs/ROLES.md shows the same
# table, and tests/system/test_roles.py checks that the two agree.
PERMISSIONS: dict[str, frozenset[str]] = {
    "preview": frozenset({"uploader", "tenant_admin"}),
    "upload": frozenset({"uploader", "tenant_admin"}),
    "list_files": frozenset({"uploader", "reviewer", "tenant_admin", "auditor"}),
    "read_rows": frozenset({"uploader", "reviewer", "tenant_admin", "auditor"}),
    "list_te": frozenset({"uploader", "reviewer", "tenant_admin", "auditor"}),
    "delete_file": frozenset({"tenant_admin"}),
    "read_audit": frozenset({"tenant_admin", "auditor"}),
    "reset_password": frozenset({"tenant_admin"}),
    "review_rows": frozenset({"reviewer", "tenant_admin"}),
    "submit_import": frozenset({"uploader", "tenant_admin"}),
    "approve_import": frozenset({"reviewer", "tenant_admin"}),
    "run_import": frozenset({"uploader", "reviewer", "tenant_admin"}),
}


def allow(action: str) -> Callable[..., None]:
    """Route dependency: 403 unless the signed-in role may perform ``action``.

    Requests without a session exist only under the local-dev anonymous opt-in
    (#298); they are not role-checked.
    """
    roles = PERMISSIONS[action]

    def check(session: dict[str, Any] | None = Depends(tenant_scope)) -> None:
        if session is not None and session["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{session['role']}' may not {action.replace('_', ' ')}")

    return check
