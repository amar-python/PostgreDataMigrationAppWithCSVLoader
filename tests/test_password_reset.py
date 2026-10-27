"""Password change, admin reset and break-glass reset for local accounts (#117).

Integration tests over a live PostgreSQL; they fail, never skip, without one.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.services import accounts
from api.tenancy import migrate_tenant, schema_for
from tests.test_accounts import _PW, _Accounts

_NEW = "a brand new passphrase"
_ROOT = Path(__file__).resolve().parent.parent


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
class ChangeOwnPassword(_Accounts):
    def _change(self, token: str, current=_PW, new=_NEW):
        return self.client.post("/api/auth/password", headers=_bearer(token),
                                json={"currentPassword": current, "newPassword": new})

    def test_new_password_works_old_does_not_and_other_sessions_end(self):
        mine, other = self._login().json()["token"], self._login().json()["token"]
        self.assertEqual(self._change(mine).status_code, 200)
        self.assertEqual(self._login().status_code, 401, "old password must stop working")
        self.assertEqual(self._login(password=_NEW).status_code, 200)
        self.assertEqual(self._me(mine).status_code, 200, "this session stays signed in")
        self.assertEqual(self._me(other).status_code, 401, "other sessions must end")

    def test_wrong_current_password_is_400_changes_nothing_and_counts_as_a_failure(self):
        token = self._login().json()["token"]
        res = self._change(token, current="wrong")
        self.assertEqual((res.status_code, res.json()["detail"]), (400, "Current password is incorrect"))
        self.assertEqual(self._me(token).status_code, 200)
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT failed_logins FROM {}.users WHERE id = %s").format(
                sql.Identifier(settings.CONTROL_SCHEMA)), (self.user_id,))
            self.assertEqual(cur.fetchone()[0], 1)
        self.assertEqual(self._login().status_code, 200, "password unchanged")

    def test_short_new_password_is_rejected(self):
        token = self._login().json()["token"]
        self.assertEqual(self._change(token, new="x" * (accounts.MIN_PASSWORD - 1)).status_code, 422)
        self.assertEqual(self._login().status_code, 200)

    def test_needs_a_session(self):
        res = self.client.post("/api/auth/password", json={"currentPassword": _PW, "newPassword": _NEW})
        self.assertEqual(res.status_code, 401)


@pytest.mark.integration
class AdminReset(_Accounts):
    def setUp(self):
        super().setUp()
        self.admin = f"admin_{uuid.uuid4().hex[:8]}"
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT id FROM {}.tenants WHERE slug = %s").format(
                    sql.Identifier(settings.CONTROL_SCHEMA)), (self.tenant,))
                self.tenant_id = cur.fetchone()[0]
                accounts.add_membership(cur, accounts.create_user(cur, self.admin, _PW),
                                        self.tenant_id, "tenant_admin")
            conn.commit()
        migrate_tenant(self.tenant)  # real tenants always have their schema (audit_log lives there)
        self.admin_token = self._login(username=self.admin).json()["token"]

    def tearDown(self):
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_for(self.tenant))))
            conn.commit()

    def _reset(self, username: str, token: str | None = None):
        return self.client.post(f"/api/auth/users/{username}/password",
                                headers=_bearer(token or self.admin_token), json={"newPassword": _NEW})

    def test_admin_reset_sets_password_unlocks_and_ends_the_users_sessions(self):
        user_token = self._login().json()["token"]
        self._exec("UPDATE {c}.users SET locked_until = now() + interval '1 hour' WHERE id = %s", self.user_id)
        self.assertEqual(self._reset(self.user).status_code, 200)
        self.assertEqual(self._me(user_token).status_code, 401, "the user's sessions must end")
        self.assertEqual(self._login().status_code, 401, "old password must stop working")
        self.assertEqual(self._login(password=_NEW).status_code, 200, "new password works and lock is cleared")

    def test_reset_is_written_to_the_tenants_audit_log(self):
        self.assertEqual(self._reset(self.user).status_code, 200)
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT action, file_name, mode FROM {}.audit_log").format(
                sql.Identifier(schema_for(self.tenant))))
            self.assertEqual(cur.fetchall(), [("password_reset", self.user, f"by {self.admin}")])

    def test_non_admin_cannot_reset(self):
        user_token = self._login().json()["token"]
        self.assertEqual(self._reset(self.admin, token=user_token).status_code, 403)
        self.assertEqual(self._login(username=self.admin).status_code, 200, "admin password unchanged")

    def test_admin_cannot_reset_a_user_in_another_tenant(self):
        outsider = f"out_{uuid.uuid4().hex[:8]}"
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT id FROM {}.tenants WHERE slug = %s").format(
                    sql.Identifier(settings.CONTROL_SCHEMA)), (self.other,))
                tid = cur.fetchone()[0]
                accounts.add_membership(cur, accounts.create_user(cur, outsider, _PW), tid, "uploader")
            conn.commit()
        self.assertEqual(self._reset(outsider).status_code, 404)
        self.assertEqual(self._login(tenant=self.other, username=outsider).status_code, 200)

    def test_user_who_is_also_in_another_tenant_is_refused(self):
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT id FROM {}.tenants WHERE slug = %s").format(
                    sql.Identifier(settings.CONTROL_SCHEMA)), (self.other,))
                accounts.add_membership(cur, self.user_id, cur.fetchone()[0], "uploader")
            conn.commit()
        self.assertEqual(self._reset(self.user).status_code, 409)
        self.assertEqual(self._login().status_code, 200, "password unchanged")


@pytest.mark.integration
class BreakGlassReset(_Accounts):
    def _run(self, username: str, password: str = _NEW) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "scripts/reset_password.py", "--username", username],
                              cwd=_ROOT, env={**os.environ, "TE_NEW_PASSWORD": password},
                              capture_output=True, text=True, timeout=60)

    def test_resets_password_clears_lockout_and_ends_sessions(self):
        token = self._login().json()["token"]
        self._exec("UPDATE {c}.users SET locked_until = now() + interval '1 hour' WHERE id = %s", self.user_id)
        res = self._run(self.user)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._me(token).status_code, 401)
        self.assertEqual(self._login().status_code, 401)
        self.assertEqual(self._login(password=_NEW).status_code, 200)

    def test_unknown_user_and_short_password_fail_without_changes(self):
        self.assertEqual(self._run("nobody_" + uuid.uuid4().hex).returncode, 1)
        self.assertEqual(self._run(self.user, password="short").returncode, 2)
        self.assertEqual(self._login().status_code, 200)
