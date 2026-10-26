"""Local accounts and sign-in sessions (M2a, #92, BR-36).

Unit tests for password hashing; integration tests for /api/auth over a live
PostgreSQL (they fail, never skip, without one).
"""

from __future__ import annotations

import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")
_PW = "correct horse battery staple"


@pytest.mark.unit
class Passwords(unittest.TestCase):
    def test_round_trip(self):
        self.assertTrue(accounts.verify_password(_PW, accounts.hash_password(_PW)))

    def test_wrong_password_fails(self):
        self.assertFalse(accounts.verify_password("nope", accounts.hash_password(_PW)))

    def test_same_password_hashes_differently(self):
        self.assertNotEqual(accounts.hash_password(_PW), accounts.hash_password(_PW))

    def test_malformed_hash_fails_closed(self):
        for bad in ("", "plain", "md5$1$2$3$aa$bb", "scrypt$x$8$1$aa$bb"):
            self.assertFalse(accounts.verify_password(_PW, bad), bad)


@pytest.mark.integration
class SignIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.tenant, self.other, self.user = f"t_{tag}", f"o_{tag}", f"user_{tag}"
        with Conn() as conn:
            with conn.cursor() as cur:
                tid = accounts.create_tenant(cur, self.tenant, "Test tenant")
                accounts.create_tenant(cur, self.other, "Other tenant")
                self.user_id = accounts.create_user(cur, self.user, _PW)
                accounts.add_membership(cur, self.user_id, tid, "uploader")
            conn.commit()

    def _exec(self, query: str, *params) -> None:
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL(query).format(c=sql.Identifier(settings.CONTROL_SCHEMA)), params)
            conn.commit()

    def _login(self, tenant=None, username=None, password=_PW):
        return self.client.post("/api/auth/login", json={
            "tenant": tenant or self.tenant, "username": username or self.user, "password": password})

    def _me(self, token: str):
        return self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    def test_login_returns_a_session_for_the_tenant_and_role(self):
        res = self._login()
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual((body["tenant"], body["username"], body["role"]), (self.tenant, self.user, "uploader"))
        me = self._me(body["token"]).json()
        self.assertEqual((me["tenant"], me["username"], me["role"]), (self.tenant, self.user, "uploader"))

    def test_every_login_failure_is_the_same_401(self):
        cases = {
            "wrong password": self._login(password="wrong"),
            "unknown user": self._login(username="nobody_" + uuid.uuid4().hex),
            "not a member of that tenant": self._login(tenant=self.other),
            "unknown tenant": self._login(tenant="no_such_tenant"),
        }
        for name, res in cases.items():
            self.assertEqual((res.status_code, res.json()["detail"]),
                             (401, "Invalid tenant, username or password"), name)

    def test_inactive_user_cannot_sign_in_and_loses_live_sessions(self):
        token = self._login().json()["token"]
        self._exec("UPDATE {c}.users SET is_active = false WHERE id = %s", self.user_id)
        self.assertEqual(self._login().status_code, 401)
        self.assertEqual(self._me(token).status_code, 401)

    def test_logout_revokes_the_session(self):
        token = self._login().json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(self._me(token).status_code, 401)

    def test_expired_session_is_rejected(self):
        token = self._login().json()["token"]
        self._exec("UPDATE {c}.sessions SET expires_at = now() - interval '1 second' WHERE user_id = %s",
                   self.user_id)
        self.assertEqual(self._me(token).status_code, 401)

    def test_removing_the_membership_ends_the_session(self):
        token = self._login().json()["token"]
        self._exec("DELETE FROM {c}.memberships WHERE user_id = %s", self.user_id)
        self.assertEqual(self._me(token).status_code, 401)

    def test_missing_or_malformed_token_is_401(self):
        for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"},
                        {"Authorization": "Bearer not-a-real-token"}):
            self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401, headers)

    def test_tokens_are_stored_only_as_hashes(self):
        token = self._login().json()["token"]
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT token_hash FROM {c}.sessions WHERE user_id = %s").format(
                c=sql.Identifier(settings.CONTROL_SCHEMA)), (self.user_id,))
            stored = [r[0] for r in cur.fetchall()]
        self.assertEqual(len(stored), 1)
        self.assertNotIn(token, stored)
