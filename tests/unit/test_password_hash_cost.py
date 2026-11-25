"""#294 (OIT-009, BR-36, SECURITY_REVIEW_PACK F4): scrypt cost, and upgrading old hashes at sign-in.

Passwords were hashed with scrypt N=2^14 (16 MiB), below current guidance (OWASP: N=2^17, r=8, p=1). The stored hash
carries its own parameters, so the cost can rise without breaking anyone: a user whose hash is weaker is upgraded the
next time they sign in with the right password. Asserted here, with no database (``login`` gets a fake cursor):

  * new hashes use N=2^17, and verify (``hashlib.scrypt`` refuses 128 MiB unless ``maxmem`` is raised, and
    ``verify_password`` reports any such refusal as "wrong password", so a missing ``maxmem`` locks everyone out);
  * an old N=2^14 hash still verifies, and ``needs_rehash`` is true for it only (not for a current or a stronger one,
    nor for anything malformed);
  * a stored hash that asks for more memory than the cap is refused at once, not computed;
  * a successful sign-in with an old hash stores a new hash, and the update only applies if the stored hash is still
    the one that was checked (so a password changed in between is not undone);
  * a sign-in with a current hash, a wrong password, an inactive user or a locked account stores nothing;
  * no new timing oracle: an unknown user, a known user with a current hash and a known user with an OLD hash all end a
    failed sign-in having paid for one current-cost hash, and the dummy hash has the current cost;
  * at most ``MAX_CONCURRENT_HASHES`` hashes are computed at once, so a burst of sign-ins cannot hold 128 MiB each.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import threading
import time

import pytest

from api.services import accounts

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

PW = "correct horse battery staple"
CURRENT = (2**17, 8, 1)
LEGACY_N = 2**14


def legacy_hash(password: str = PW, n: int = LEGACY_N, r: int = 8, p: int = 1) -> str:
    """A hash as the code wrote it before #294 (made with hashlib directly, so it does not depend on the code under test)."""
    salt = bytes(range(16))
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def params(stored: str) -> tuple[int, int, int]:
    algo, n, r, p, *_ = stored.split("$")
    assert algo == "scrypt"
    return int(n), int(r), int(p)


# -- the cost, and what still verifies --------------------------------------------------------------------------------


def test_new_hashes_use_the_current_cost():
    stored = accounts.hash_password(PW)
    assert stored.startswith("scrypt$131072$8$1$"), stored
    assert params(stored) == CURRENT


def test_a_new_hash_verifies_and_a_wrong_password_does_not():
    stored = accounts.hash_password(PW)
    assert accounts.verify_password(PW, stored) is True
    assert accounts.verify_password(PW + "x", stored) is False


def test_an_old_hash_still_verifies():
    assert accounts.verify_password(PW, legacy_hash()) is True
    assert accounts.verify_password("not it", legacy_hash()) is False


def test_the_dummy_hash_has_the_current_cost():
    """An unknown user is checked against it, so it must cost what a real check costs."""
    assert params(accounts._DUMMY_HASH) == CURRENT


def test_a_stored_hash_asking_for_too_much_memory_is_refused_at_once():
    stored = legacy_hash(n=2**14).replace("scrypt$16384$", f"scrypt${2**26}$")
    started = time.monotonic()
    assert accounts.verify_password(PW, stored) is False
    assert time.monotonic() - started < 1.0, "it must be refused, not computed"


# -- needs_rehash -----------------------------------------------------------------------------------------------------


def test_needs_rehash_is_true_for_a_weaker_hash():
    assert accounts.needs_rehash(legacy_hash()) is True
    assert accounts.needs_rehash(legacy_hash(n=2**16)) is True
    assert accounts.needs_rehash(legacy_hash(r=4)) is True


def test_needs_rehash_is_false_for_a_current_or_stronger_hash_and_for_junk():
    assert accounts.needs_rehash(accounts.hash_password(PW)) is False
    assert accounts.needs_rehash(f"scrypt${2**18}$8$1$aa$bb") is False, "never downgrade a stronger hash"
    for junk in ("", "plain", "md5$1$2$3$aa$bb", "scrypt$x$8$1$aa$bb", "scrypt$1$2$3$4"):
        assert accounts.needs_rehash(junk) is False, junk


# -- login, with a fake cursor ----------------------------------------------------------------------------------------


class FakeCursor:
    """Answers the queries ``accounts.login`` runs and records every statement and its parameters."""

    def __init__(self, row):
        self.row = row
        self.statements: list[tuple[str, object]] = []
        self.rowcount = 1

    def execute(self, query, params=None):
        self.statements.append((repr(query), params))
        self.last = repr(query)

    def fetchone(self):
        if "RETURNING expires_at" in self.last:
            return (dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc),)
        if "RETURNING failed_logins" in self.last:
            return (1,)
        return self.row

    def password_updates(self):
        return [(sql, params) for sql, params in self.statements if "password_hash = %s" in sql and "UPDATE" in sql]


def user_row(stored: str, *, active: bool = True, role: str | None = "uploader", locked: bool = False):
    """(user id, password hash, is_active, tenant id, role, locked) as login's SELECT returns it."""
    return (7, stored, active, 3, role, locked)


@pytest.fixture
def scrypt_costs(monkeypatch):
    """Records the N of every scrypt computed, passing each through to the real one."""
    seen: list[int] = []
    real = hashlib.scrypt

    def recording(password, *, salt, n, r, p, **kw):
        seen.append(n)
        return real(password, salt=salt, n=n, r=r, p=p, **kw)

    monkeypatch.setattr(hashlib, "scrypt", recording)
    return seen


def test_signing_in_with_an_old_hash_stores_a_new_one(scrypt_costs):
    old = legacy_hash()
    cur = FakeCursor(user_row(old))
    session = accounts.login(cur, "acme", "alice", PW)
    assert session and session["username"] == "alice"
    updates = cur.password_updates()
    assert len(updates) == 1, "exactly one upgrade"
    _, (new_hash, user_id, checked_hash) = updates[0]
    assert params(new_hash) == CURRENT and user_id == 7
    assert accounts.verify_password(PW, new_hash) is True, "the stored hash must still accept the password"
    assert checked_hash == old, "the update must be conditional on the hash that was checked"


def test_the_upgrade_only_applies_if_the_stored_hash_is_still_the_one_checked(scrypt_costs):
    cur = FakeCursor(user_row(legacy_hash()))
    accounts.login(cur, "acme", "alice", PW)
    sql, _ = cur.password_updates()[0]
    assert "password_hash = %s" in sql and sql.count("password_hash") >= 2, (
        "UPDATE ... WHERE id = %s AND password_hash = %s, so a password changed meanwhile is not undone: " + sql
    )


def test_signing_in_with_a_current_hash_stores_nothing(scrypt_costs):
    cur = FakeCursor(user_row(accounts.hash_password(PW)))
    assert accounts.login(cur, "acme", "alice", PW)
    assert cur.password_updates() == []


@pytest.mark.parametrize(
    "case, row_kw, password",
    [
        ("wrong password", {}, "not the password"),
        ("inactive user", {"active": False}, PW),
        ("not a member", {"role": None}, PW),
        ("locked account", {"locked": True}, PW),
    ],
)
def test_a_refused_sign_in_never_upgrades_a_hash(scrypt_costs, case, row_kw, password):
    cur = FakeCursor(user_row(legacy_hash(), **row_kw))
    assert accounts.login(cur, "acme", "alice", password) is None, case
    assert cur.password_updates() == [], case


# -- no new timing oracle ---------------------------------------------------------------------------------------------


def failed_sign_in_costs(scrypt_costs, row) -> list[int]:
    scrypt_costs.clear()
    assert accounts.login(FakeCursor(row), "acme", "alice", "wrong password entirely") is None
    return list(scrypt_costs)


def test_a_failed_sign_in_pays_one_current_cost_hash_whoever_the_user_is(scrypt_costs):
    unknown = failed_sign_in_costs(scrypt_costs, None)
    current_user = failed_sign_in_costs(scrypt_costs, user_row(accounts.hash_password(PW)))
    old_user = failed_sign_in_costs(scrypt_costs, user_row(legacy_hash()))
    assert unknown == [CURRENT[0]], unknown
    assert current_user == [CURRENT[0]], current_user
    assert CURRENT[0] in old_user, (
        "a user whose hash is old must not fail faster than an unknown one (that tells an attacker the name exists): "
        f"{old_user}"
    )


# -- bounded memory ---------------------------------------------------------------------------------------------------


def test_no_more_than_the_limit_of_hashes_run_at_once(monkeypatch):
    active = peak = 0
    lock = threading.Lock()

    def slow(password, *, salt, n, r, p, **kw):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return bytes(64)

    monkeypatch.setattr(hashlib, "scrypt", slow)
    workers = [threading.Thread(target=accounts.hash_password, args=(PW,)) for _ in range(10)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert 1 <= peak <= accounts.MAX_CONCURRENT_HASHES, f"{peak} at once; the limit is {accounts.MAX_CONCURRENT_HASHES}"
    assert accounts.MAX_CONCURRENT_HASHES * 128 <= 512, "keep the worst case well under a 1 GiB container"
