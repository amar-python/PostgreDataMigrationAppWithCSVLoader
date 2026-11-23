"""#294 (OIT-009, BR-36): an old, weaker password hash is upgraded when its owner signs in.

Integration tests over a live PostgreSQL (they fail, never skip, without one); the logic itself is covered without a
database in ``tests/unit/test_password_hash_cost.py``. Here the real API and the real SQL are used:

  * a user whose stored hash is the old N=2^14 one still signs in, and afterwards the stored hash is the current one;
  * the upgraded hash accepts the same password, and signing in again does not change it;
  * a wrong password leaves the old hash alone;
  * the upgrade is conditional on the hash that was checked, so a password changed in between is not undone.
"""
from __future__ import annotations

import hashlib

import pytest
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.services import accounts
from tests.system.test_accounts import _PW, _Accounts


def old_hash(password: str, n: int = 2**14) -> str:
    salt = bytes(range(16))
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=8, p=1, maxmem=256 * 1024 * 1024)
    return f"scrypt${n}$8$1${salt.hex()}${dk.hex()}"


@pytest.mark.integration
class HashUpgradeAtSignIn(_Accounts):
    def _stored(self) -> str:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT password_hash FROM {c}.users WHERE id = %s")
                        .format(c=sql.Identifier(settings.CONTROL_SCHEMA)), (self.user_id,))
            return cur.fetchone()[0]

    def _store(self, value: str) -> None:
        self._exec("UPDATE {c}.users SET password_hash = %s WHERE id = %s", value, self.user_id)

    def test_a_user_with_an_old_hash_signs_in_and_is_upgraded(self):
        legacy = old_hash(_PW)
        self._store(legacy)
        res = self._login()
        self.assertEqual(res.status_code, 200, res.text)
        upgraded = self._stored()
        self.assertNotEqual(upgraded, legacy)
        self.assertTrue(upgraded.startswith("scrypt$131072$8$1$"), upgraded)
        self.assertTrue(accounts.verify_password(_PW, upgraded))
        self.assertFalse(accounts.needs_rehash(upgraded))

    def test_signing_in_again_leaves_the_upgraded_hash_alone(self):
        self._store(old_hash(_PW))
        self.assertEqual(self._login().status_code, 200)
        once = self._stored()
        self.assertEqual(self._login().status_code, 200)
        self.assertEqual(self._stored(), once)

    def test_a_wrong_password_leaves_the_old_hash_alone(self):
        legacy = old_hash(_PW)
        self._store(legacy)
        self.assertEqual(self._login(password="not the password").status_code, 401)
        self.assertEqual(self._stored(), legacy)

    def test_a_password_changed_meanwhile_is_not_undone_by_the_upgrade(self):
        legacy = old_hash(_PW)
        changed = accounts.hash_password("a different passphrase")
        self._store(changed)             # changed after the sign-in read `legacy`
        with Conn() as conn:
            with conn.cursor() as cur:
                self.assertFalse(accounts._upgrade_hash(cur, self.user_id, legacy, _PW))
            conn.commit()
        self.assertEqual(self._stored(), changed)
        self.assertTrue(accounts.verify_password("a different passphrase", self._stored()))
        self.assertFalse(accounts.verify_password(_PW, self._stored()), "the old password must not come back")

    def test_the_upgrade_applies_when_the_hash_is_unchanged(self):
        legacy = old_hash(_PW)
        self._store(legacy)
        with Conn() as conn:
            with conn.cursor() as cur:
                self.assertTrue(accounts._upgrade_hash(cur, self.user_id, legacy, _PW))
            conn.commit()
        self.assertTrue(self._stored().startswith("scrypt$131072$"))
