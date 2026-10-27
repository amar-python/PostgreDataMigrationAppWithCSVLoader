"""Sign-in with local accounts (M2a, #92, BR-36).

Sessions are bearer tokens: ``Authorization: Bearer <token>``. Login failures
all return the same 401 so a caller cannot probe for valid usernames or tenants.
The global rate limiter's write budget applies to login attempts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import PERMISSIONS, bearer_token, require_session
from api.db import Conn
from api import oidc
from api.services import accounts
from api.services.audit import write_audit
from api.tenancy import schema_for, scoped

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    tenant: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(req: LoginRequest) -> dict:
    with Conn() as conn:
        with conn.cursor() as cur:
            session = accounts.login(cur, req.tenant, req.username, req.password)
        conn.commit()
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid tenant, username or password")
    return session


class OidcLoginRequest(BaseModel):
    tenant: str = Field(min_length=1, max_length=64)
    idToken: str = Field(min_length=1, max_length=16384)


@router.post("/oidc")
def oidc_login(req: OidcLoginRequest) -> dict:
    """Exchange an IdP ID token for a session (#95). 404 when OIDC isn't configured."""
    if not oidc.enabled():
        raise HTTPException(status_code=404, detail="OIDC sign-in is not configured")
    username = oidc.username_from(req.idToken)
    session = None
    if username:
        with Conn() as conn:
            with conn.cursor() as cur:
                session = accounts.login_trusted(cur, req.tenant, username)
            conn.commit()
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid token, or no access to that tenant")
    return session


@router.post("/logout")
def logout(token: str = Depends(bearer_token)) -> dict:
    with Conn() as conn:
        with conn.cursor() as cur:
            accounts.revoke(cur, token)
        conn.commit()
    return {"status": "ok"}


@router.get("/me")
def me(session: dict = Depends(require_session)) -> dict:
    return session


_NewPassword = Field(min_length=accounts.MIN_PASSWORD, max_length=1024)


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=1024)
    newPassword: str = _NewPassword


@router.post("/password")
def change_password(req: ChangePasswordRequest, token: str = Depends(bearer_token),
                    session: dict = Depends(require_session)) -> dict:
    """Change your own password (#117). This session stays signed in; all others end.

    A wrong current password is 400, not 401, so the browser keeps the session,
    and it counts towards the lockout like a failed sign-in.
    """
    with Conn() as conn:
        with conn.cursor() as cur:
            ok = accounts.change_password(cur, session["userId"], token,
                                          req.currentPassword, req.newPassword)
        conn.commit()
    if not ok:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return {"status": "ok"}


class ResetPasswordRequest(BaseModel):
    newPassword: str = _NewPassword


@router.post("/users/{username}/password")
def reset_password(username: str, req: ResetPasswordRequest,
                   session: dict = Depends(require_session)) -> dict:
    """A tenant admin sets a member's password, unlocking the account and ending
    its sessions (#117). Audited in the tenant's audit log."""
    if session["role"] not in PERMISSIONS["reset_password"]:
        raise HTTPException(status_code=403, detail=f"Role '{session['role']}' may not reset password")
    with Conn() as conn:
        with conn.cursor() as cur:
            result = accounts.reset_password(cur, session["tenantId"], username, req.newPassword)
            if result == "ok":
                # ponytail: audit_log has file columns only; target in file_name and actor
                # in mode until M3's audit_events (#107) adds actor and object.
                with scoped(schema_for(session["tenant"])):
                    write_audit(cur, "password_reset", None, username, None, f"by {session['username']}")
        conn.commit()
    if result == "missing":
        raise HTTPException(status_code=404, detail="No such user in this tenant")
    if result == "shared":
        raise HTTPException(status_code=409, detail="This user is also in another tenant. "
                            "An operator must reset it with scripts/reset_password.py")
    return {"status": "ok"}
