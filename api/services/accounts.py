"""Local accounts and sign-in sessions (M2a, #92, BR-36).

Passwords use stdlib scrypt, so air-gapped installs need no extra package.
Session tokens are random, returned once, and stored only as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from psycopg2 import sql

from api.config import settings

ROLES = ("uploader", "reviewer", "tenant_admin", "auditor")
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, want = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), want)


# Checked when the username is unknown, so a miss costs the same time as a hit.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _q(query: str) -> sql.Composed:
    return sql.SQL(query).format(c=sql.Identifier(settings.CONTROL_SCHEMA))


def create_tenant(cur, slug: str, name: str) -> int:
    cur.execute(_q("INSERT INTO {c}.tenants (slug, name) VALUES (%s, %s) RETURNING id"), (slug, name))
    return cur.fetchone()[0]


def create_user(cur, username: str, password: str) -> int:
    cur.execute(_q("INSERT INTO {c}.users (username, password_hash) VALUES (%s, %s) RETURNING id"),
                (username, hash_password(password)))
    return cur.fetchone()[0]


def add_membership(cur, user_id: int, tenant_id: int, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; expected one of {ROLES}")
    cur.execute(_q("INSERT INTO {c}.memberships (user_id, tenant_id, role) VALUES (%s, %s, %s)"),
                (user_id, tenant_id, role))


def login(cur, tenant_slug: str, username: str, password: str) -> dict | None:
    """Return a new session for an active member of the tenant, else None.

    The caller commits, including on failure so failed attempts are counted.
    Wrong tenant, unknown user, wrong password, inactive user and locked
    account (#102) all return None, so a caller cannot tell which one failed.
    """
    cur.execute(_q(
        "SELECT u.id, u.password_hash, u.is_active, t.id, m.role, "
        "COALESCE(u.locked_until > now(), false) "
        "FROM {c}.users u "
        "LEFT JOIN {c}.tenants t ON t.slug = %s "
        "LEFT JOIN {c}.memberships m ON m.user_id = u.id AND m.tenant_id = t.id "
        "WHERE u.username = %s"), (tenant_slug, username))
    row = cur.fetchone()
    ok = verify_password(password, row[1] if row else _DUMMY_HASH)
    if row and not ok:
        _record_failure(cur, row[0])
    if not (row and ok and row[2] and row[4]) or row[5]:
        return None
    cur.execute(_q("UPDATE {c}.users SET failed_logins = 0, first_failed_at = NULL, "
                   "locked_until = NULL WHERE id = %s"), (row[0],))
    return _new_session(cur, row[0], row[3], username, tenant_slug, row[4])


def login_trusted(cur, tenant_slug: str, username: str) -> dict | None:
    """Session for a user whose identity an IdP has already proven (OIDC, #95).

    Authorisation stays local: the user must already exist, be active and be a
    member of the tenant. Nobody is created from IdP claims.
    """
    cur.execute(_q(
        "SELECT u.id, t.id, m.role FROM {c}.users u "
        "JOIN {c}.tenants t ON t.slug = %s "
        "JOIN {c}.memberships m ON m.user_id = u.id AND m.tenant_id = t.id "
        "WHERE u.username = %s AND u.is_active"), (tenant_slug, username))
    row = cur.fetchone()
    return _new_session(cur, row[0], row[1], username, tenant_slug, row[2]) if row else None


def _new_session(cur, user_id: int, tenant_id: int, username: str, tenant_slug: str, role: str) -> dict:
    token = secrets.token_urlsafe(32)
    cur.execute(_q(
        "INSERT INTO {c}.sessions (token_hash, user_id, tenant_id, expires_at) "
        "VALUES (%s, %s, %s, now() + make_interval(hours => %s)) RETURNING expires_at"),
        (_token_hash(token), user_id, tenant_id, settings.SESSION_TTL_HOURS))
    expires_at = cur.fetchone()[0]
    return {"token": token, "expiresAt": expires_at.isoformat(), "username": username,
            "tenant": tenant_slug, "role": role}


def _record_failure(cur, user_id: int) -> None:
    """Count a wrong password; lock the account once the window's limit is reached (#102)."""
    cur.execute(_q(
        "UPDATE {c}.users SET "
        "failed_logins = CASE WHEN first_failed_at > now() - make_interval(mins => %(m)s) "
        "                     THEN failed_logins + 1 ELSE 1 END, "
        "first_failed_at = CASE WHEN first_failed_at > now() - make_interval(mins => %(m)s) "
        "                       THEN first_failed_at ELSE now() END "
        "WHERE id = %(id)s RETURNING failed_logins"),
        {"m": settings.LOGIN_LOCKOUT_MINUTES, "id": user_id})
    if cur.fetchone()[0] >= settings.LOGIN_MAX_FAILURES:
        cur.execute(_q("UPDATE {c}.users SET locked_until = now() + make_interval(mins => %s) "
                       "WHERE id = %s"), (settings.LOGIN_LOCKOUT_MINUTES, user_id))


def session_for(cur, token: str) -> dict | None:
    """The live session for a token, with its user, tenant and role, else None."""
    cur.execute(_q(
        "SELECT u.id, u.username, t.id, t.slug, m.role, s.expires_at "
        "FROM {c}.sessions s "
        "JOIN {c}.users u ON u.id = s.user_id AND u.is_active "
        "JOIN {c}.tenants t ON t.id = s.tenant_id "
        "JOIN {c}.memberships m ON m.user_id = u.id AND m.tenant_id = t.id "
        "WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now()"),
        (_token_hash(token),))
    row = cur.fetchone()
    if not row:
        return None
    return {"userId": row[0], "username": row[1], "tenantId": row[2], "tenant": row[3],
            "role": row[4], "expiresAt": row[5].isoformat()}


def revoke(cur, token: str) -> None:
    cur.execute(_q("UPDATE {c}.sessions SET revoked_at = now() "
                   "WHERE token_hash = %s AND revoked_at IS NULL"), (_token_hash(token),))
