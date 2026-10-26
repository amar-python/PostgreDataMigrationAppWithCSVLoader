"""OIDC ID-token verification against a deployment-controlled IdP (#95, BR-36).

The frontend completes the IdP's authorization-code flow and posts the ID
token to /api/auth/oidc. Here the token's signature (from the IdP's JWKS),
issuer, audience and expiry are checked; a valid token names a local user,
who then gets an ordinary session for the tenant they chose.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import jwt

from api.config import settings

ALGORITHMS = ["RS256", "ES256"]


def enabled() -> bool:
    return bool(settings.OIDC_ISSUER)


def check_config() -> None:
    """Fail closed at startup on a half-configured IdP (called from api/main.py)."""
    if not enabled():
        return
    if not settings.OIDC_AUDIENCE:
        raise RuntimeError("OIDC_ISSUER is set but OIDC_AUDIENCE is empty; set it to this app's client id.")
    if not settings.OIDC_JWKS_URL.startswith(("https://", "file://")):
        raise RuntimeError("OIDC_JWKS_URL must be https:// or file:// when OIDC_ISSUER is set.")


@lru_cache(maxsize=4)
def _jwks(url: str):
    """Key source for ``url``: https:// is fetched (and re-fetched on an unknown
    key id, for IdP key rotation); file:// is a JWKS file published inside an
    enclave. Plain http:// is refused, since keys fetched over it could be swapped.
    """
    if url.startswith("https://"):
        return jwt.PyJWKClient(url, cache_keys=True)
    if url.startswith("file://"):
        return jwt.PyJWKSet.from_json(Path(url2pathname(urlparse(url).path)).read_text(encoding="utf-8"))
    raise ValueError(f"OIDC_JWKS_URL must be https:// or file://, got {url!r}")


def _signing_key(id_token: str):
    source = _jwks(settings.OIDC_JWKS_URL)
    if isinstance(source, jwt.PyJWKClient):
        return source.get_signing_key_from_jwt(id_token).key
    kid = jwt.get_unverified_header(id_token).get("kid")
    try:
        return source[kid].key
    except KeyError:
        raise jwt.InvalidTokenError(f"unknown key id {kid!r}") from None


def username_from(id_token: str) -> str | None:
    """The verified token's username claim, or None if anything about it is wrong."""
    try:
        key = _signing_key(id_token)
        claims = jwt.decode(id_token, key, algorithms=ALGORITHMS, audience=settings.OIDC_AUDIENCE,
                            issuer=settings.OIDC_ISSUER, options={"require": ["exp", "iat", "iss", "aud"]})
    except jwt.PyJWTError:
        return None
    username = claims.get(settings.OIDC_USERNAME_CLAIM)
    return username if isinstance(username, str) and username else None
