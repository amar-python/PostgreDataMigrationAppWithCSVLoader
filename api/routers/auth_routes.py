"""Sign-in with local accounts (M2a, #92, BR-36).

Sessions are bearer tokens: ``Authorization: Bearer <token>``. Login failures
all return the same 401 so a caller cannot probe for valid usernames or tenants.
The global rate limiter's write budget applies to login attempts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import bearer_token, require_session
from api.db import Conn
from api.services import accounts

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
