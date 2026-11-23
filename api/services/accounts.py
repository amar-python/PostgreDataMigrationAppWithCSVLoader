"""Local accounts and sign-in sessions (M2a, #92, BR-36).

Passwords use stdlib scrypt, so air-gapped installs need no extra package.
Session tokens are random, returned once, and stored only as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from typing import NamedTuple

from psycopg2 import sql

from api.config import settings

ROLES = ("uploader", "reviewer", "tenant_admin", "auditor")
MIN_PASSWORD = 12
# scrypt cost (#294): OWASP's minimum for r=8, p=1 is N=2^17, which needs 128 * N * r = 128 MiB and about half a second
# on one core. A stored hash carries its own parameters, so older, weaker hashes still verify and are upgraded at sign-in.
_N, _R, _P = 2**17, 8, 1
# hashlib.scrypt refuses to run above ``maxmem`` (default 32 MiB, so the current cost would raise ValueError, which
# verify_password reports as a wrong password). The cap leaves headroom over 128 MiB and also stops a stored hash that
# asks for far more from being computed.
_MAXMEM = 256 * 1024 * 1024
# At most this many hashes at once: 128 MiB each, and the API's smallest container has 1 GiB. A burst of sign-ins queues.
MAX_CONCURRENT_HASHES = 2
_HASH_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _HASH_SLOTS:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = _scrypt(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, want = stored.split("$")
        if algo != "scrypt":
            return False
        dk = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), want)


def needs_rehash(stored: str) -> bool:
    """True if ``stored`` is a scrypt hash made with a weaker cost than the current one (#294).

    A stronger hash is left alone (never downgraded), and so is anything that is not a well-formed scrypt hash.
    """
    try:
        algo, n, r, p, _salt, _want = stored.split("$")
        return algo == "scrypt" and (int(n) < _N or int(r) < _R or int(p) < _P)
    except (ValueError, TypeError):
        return False


# Checked when the username is unknown, so a miss costs the same time as a hit.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _q(query: str) -> sql.Composed:
    return sql.SQL(query).format(c=sql.Identifier(settings.CONTROL_SCHEMA))


class Existing(NamedTuple):
    tenant: bool  # a tenant with this slug exists
    user: bool    # a user with this username exists; usernames are unique across all tenants
    member: bool  # that user is already a member of that tenant


def existing(cur, slug: str, username: str) -> Existing:
    """What already exists for a tenant slug and a username.

    Lets a caller refuse to create a duplicate with a clear message, instead of failing on
    the database's unique key after the person has already typed a password.
    """
    cur.execute(_q(
        "SELECT EXISTS (SELECT 1 FROM {c}.tenants WHERE slug = %s), "
        "EXISTS (SELECT 1 FROM {c}.users WHERE username = %s), "
        "EXISTS (SELECT 1 FROM {c}.users u "
        "JOIN {c}.memberships m ON m.user_id = u.id "
        "JOIN {c}.tenants t ON t.id = m.tenant_id "
        "WHERE t.slug = %s AND u.username = %s)"), (slug, username, slug, username))
    return Existing(*cur.fetchone())


def tenant_id(cur, slug: str) -> int | None:
    """The id of the tenant with this slug, or None if there is none."""
    cur.execute(_q("SELECT id FROM {c}.tenants WHERE slug = %s"), (slug,))
    row = cur.fetchone()
    return row[0] if row else None


def create_tenant(cur, slug: str, name: str) -> int:
    cur.execute(_q("INSERT INTO {c}.tenants (slug, name) VALUES (%s, %s) RETURNING id"), (slug, name))
    return cur.fetchone()[0]


def set_self_approval(cur, slug: str, allowed: bool) -> None:
    """Let a tenant's members approve data they uploaded or submitted themselves (decision 5, M6).

    Off by default. For a tenant with one user, who couldn't otherwise approve anything. The caller commits.
    """
    cur.execute(_q("UPDATE {c}.tenants SET allow_self_approval = %s WHERE slug = %s"), (allowed, slug))
    if cur.rowcount != 1:
        raise ValueError(f"No tenant {slug!r}")


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
    stored = row[1] if row else _DUMMY_HASH
    ok = verify_password(password, stored)
    if row and not ok:
        _record_failure(cur, row[0])
        if needs_rehash(stored):
            # An old hash is cheaper to check than the dummy, so a known name would fail faster than an unknown one.
            verify_password(password, _DUMMY_HASH)
    if not (row and ok and row[2] and row[4]) or row[5]:
        return None
    if needs_rehash(stored):
        _upgrade_hash(cur, row[0], stored, password)
    cur.execute(_q("UPDATE {c}.users SET failed_logins = 0, first_failed_at = NULL, "
                   "locked_until = NULL WHERE id = %s"), (row[0],))
    return _new_session(cur, row[0], row[3], username, tenant_slug, row[4])


def _upgrade_hash(cur, user_id: int, old_hash: str, password: str) -> bool:
    """Store a hash of ``password`` at the current cost, if the stored hash is still ``old_hash`` (#294).

    The condition keeps a password changed between the check and this update from being undone. Returns whether a row
    was changed. The caller commits.
    """
    cur.execute(_q("UPDATE {c}.users SET password_hash = %s WHERE id = %s AND password_hash = %s"),
                (hash_password(password), user_id, old_hash))
    return cur.rowcount == 1


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
    """The live session for a token, with its user, tenant and role, else None.

    Live means not revoked, not past its expiry, and (when ``SESSION_IDLE_MINUTES`` is above 0) used within that many
    minutes (#296). A hit records the use; the caller commits, or the record is lost.
    """
    idle = settings.SESSION_IDLE_MINUTES
    cur.execute(_q(
        "SELECT u.id, u.username, t.id, t.slug, m.role, s.expires_at "
        "FROM {c}.sessions s "
        "JOIN {c}.users u ON u.id = s.user_id AND u.is_active "
        "JOIN {c}.tenants t ON t.id = s.tenant_id "
        "JOIN {c}.memberships m ON m.user_id = u.id AND m.tenant_id = t.id "
        "WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now() "
        "AND (%s <= 0 OR s.last_seen_at > now() - make_interval(mins => %s))"),
        (_token_hash(token), idle, idle))
    row = cur.fetchone()
    if not row:
        return None
    _touch(cur, _token_hash(token))
    return {"userId": row[0], "username": row[1], "tenantId": row[2], "tenant": row[3],
            "role": row[4], "expiresAt": row[5].isoformat()}


def _touch(cur, token_hash: str) -> None:
    """Record that a session was just used, writing at most about once a minute (#296).

    Every request would otherwise write. The gap stays well inside the idle limit, so an active session never
    looks idle because the write was skipped.
    """
    idle = settings.SESSION_IDLE_MINUTES
    gap = max(1, min(60, idle * 15)) if idle > 0 else 60   # seconds: a quarter of the idle limit, at most a minute
    cur.execute(_q("UPDATE {c}.sessions SET last_seen_at = now() "
                   "WHERE token_hash = %s AND last_seen_at < now() - make_interval(secs => %s)"),
                (token_hash, gap))


def purge_sessions(cur) -> int:
    """Delete the rows of sessions that ended more than ``SESSION_PURGE_GRACE_DAYS`` ago; return how many (#296).

    Ended means expired, revoked, or (when the idle limit is on) idle for longer than the limit. A live session, one
    that ended recently, and every user and membership are left alone. The caller commits.
    """
    cur.execute(_q(
        "DELETE FROM {c}.sessions WHERE "
        "expires_at < now() - make_interval(days => %(grace)s) "
        "OR revoked_at < now() - make_interval(days => %(grace)s) "
        "OR (%(idle)s > 0 AND last_seen_at < now() - make_interval(days => %(grace)s) "
        "                                       - make_interval(mins => %(idle)s))"),
        {"grace": settings.SESSION_PURGE_GRACE_DAYS, "idle": settings.SESSION_IDLE_MINUTES})
    return cur.rowcount


def revoke(cur, token: str) -> None:
    cur.execute(_q("UPDATE {c}.sessions SET revoked_at = now() "
                   "WHERE token_hash = %s AND revoked_at IS NULL"), (_token_hash(token),))


def _set_password(cur, user_id: int, password: str, keep_token: str | None = None) -> None:
    """New hash, lockout cleared, and every session revoked except ``keep_token`` (#117)."""
    cur.execute(_q("UPDATE {c}.users SET password_hash = %s, failed_logins = 0, "
                   "first_failed_at = NULL, locked_until = NULL WHERE id = %s"),
                (hash_password(password), user_id))
    cur.execute(_q("UPDATE {c}.sessions SET revoked_at = now() WHERE user_id = %s "
                   "AND revoked_at IS NULL AND token_hash IS DISTINCT FROM %s"),
                (user_id, _token_hash(keep_token) if keep_token else None))


def change_password(cur, user_id: int, token: str, current: str, new: str) -> bool:
    """A signed-in user changes their own password; other sessions end. False if
    ``current`` is wrong, which counts towards the lockout (#102)."""
    cur.execute(_q("SELECT password_hash FROM {c}.users WHERE id = %s"), (user_id,))
    row = cur.fetchone()
    if not (row and verify_password(current, row[0])):
        if row:
            _record_failure(cur, user_id)
        return False
    _set_password(cur, user_id, new, keep_token=token)
    return True


def reset_password(cur, tenant_id: int, username: str, new: str) -> str:
    """An admin sets a member's password; it also unlocks the account and ends all
    of its sessions. Returns "ok", "missing" (not a member of ``tenant_id``) or
    "shared": a user who is also in another tenant is refused, because the
    password is global and one tenant's admin must not take over the others."""
    cur.execute(_q("SELECT u.id, EXISTS (SELECT 1 FROM {c}.memberships o "
                   "WHERE o.user_id = u.id AND o.tenant_id <> %s) "
                   "FROM {c}.users u JOIN {c}.memberships m "
                   "ON m.user_id = u.id AND m.tenant_id = %s WHERE u.username = %s"),
                (tenant_id, tenant_id, username))
    row = cur.fetchone()
    if not row:
        return "missing"
    if row[1]:
        return "shared"
    _set_password(cur, row[0], new)
    return "ok"


def set_password(cur, username: str, new: str) -> bool:
    """Break-glass reset by username, for an operator with database access (#117)."""
    cur.execute(_q("SELECT id FROM {c}.users WHERE username = %s"), (username,))
    row = cur.fetchone()
    if row:
        _set_password(cur, row[0], new)
    return bool(row)
