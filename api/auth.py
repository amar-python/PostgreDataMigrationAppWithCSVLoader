"""API key authentication dependency, applied globally in api/main.py."""

import secrets

from fastapi import Header, HTTPException

from api.config import settings


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.API_KEY:
        # No key configured — only acceptable for local dev (see config.py comment).
        return
    if not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")
