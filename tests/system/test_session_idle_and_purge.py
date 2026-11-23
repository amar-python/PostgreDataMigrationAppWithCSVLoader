"""#296 (OIT-011, BR-36, SECURITY_REVIEW_PACK F6): sessions get an idle timeout, and old rows are purged.

Sessions had a fixed 12-hour life, no idle limit, and expired or revoked rows were never deleted (a stolen token stayed
useful for the full 12 hours; the table only grew). Integration tests over a live PostgreSQL (they fail, never skip,
without one):

  * a session that has been idle longer than ``SESSION_IDLE_MINUTES`` is refused (401), on ``/api/auth/me`` and on a
    tenant data route; an active one is not; ``0`` turns the check off; the absolute expiry is unchanged;
  * every authenticated request refreshes ``last_seen_at``, but writes at most about once a minute, and the refresh is
    really committed (the auth dependency never committed anything before);
  * ``purge_sessions`` deletes rows that expired, were revoked, or went idle, once they are older than the grace
    period, and nothing else: live sessions and recently ended ones stay, and so do users;
  * ``scripts/purge_sessions.py`` does the same from the command line, and the API purges once at start-up without a
    purge failure ever stopping it from starting.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts
from api.tenancy import migrate_tenant
from tests.system.test_accounts import _PW, _Accounts

ROOT = Path(__file__).resolve().parents[2]
UNAUTHORISED = "Session expired or invalid; sign in again"


class _Sessions(_Accounts):
    def _fetch(self, query: str, *params):
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL(query).format(c=sql.Identifier(settings.CONTROL_SCHEMA)), params)
            return cur.fetchall()

    def _token(self) -> str:
        res = self._login()
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["token"]

    def _set(self, token: str, **ages) -> None:
        """Move columns of one session into the past: ``last_seen_at=timedelta`` style, given as SQL intervals."""
        for column, interval in ages.items():
            self._exec(f"UPDATE {{c}}.sessions SET {column} = now() - %s::interval WHERE token_hash = %s",
                       interval, accounts._token_hash(token))

    def _gone(self, token: str) -> bool:
        return not self._fetch("SELECT 1 FROM {c}.sessions WHERE token_hash = %s", accounts._token_hash(token))

    def _files(self, token: str):
        return self.client.get("/api/csv/files", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.integration
class IdleTimeout(_Sessions):
    def test_the_default_is_thirty_minutes(self):
        self.assertIsNone(os.environ.get("SESSION_IDLE_MINUTES"), "this check is about the shipped default")
        self.assertEqual(settings.SESSION_IDLE_MINUTES, 30)

    def test_a_session_idle_past_the_limit_is_refused(self):
        token = self._token()
        self._set(token, last_seen_at="31 minutes")
        res = self._me(token)
        self.assertEqual((res.status_code, res.json()["detail"]), (401, UNAUTHORISED))

    def test_a_session_idle_past_the_limit_is_refused_on_a_data_route_too(self):
        migrate_tenant(self.tenant)    # real tenants always have their schema; the data route reads from it
        token = self._token()
        self.assertEqual(self._files(token).status_code, 200, "an active session reaches the route")
        self._set(token, last_seen_at="31 minutes")
        self.assertEqual(self._files(token).status_code, 401)

    def test_an_active_session_stays_valid(self):
        token = self._token()
        self._set(token, last_seen_at="29 minutes")
        self.assertEqual(self._me(token).status_code, 200)

    def test_the_limit_follows_the_setting(self):
        token = self._token()
        with mock.patch.object(settings, "SESSION_IDLE_MINUTES", 5):
            self._set(token, last_seen_at="4 minutes")
            self.assertEqual(self._me(token).status_code, 200)
            self._set(token, last_seen_at="6 minutes")
            self.assertEqual(self._me(token).status_code, 401)

    def test_zero_turns_the_idle_check_off(self):
        token = self._token()
        self._set(token, last_seen_at="3 days")
        with mock.patch.object(settings, "SESSION_IDLE_MINUTES", 0):
            self.assertEqual(self._me(token).status_code, 200)

    def test_the_absolute_expiry_still_applies_to_an_active_session(self):
        token = self._token()
        self._exec("UPDATE {c}.sessions SET expires_at = now() - interval '1 second' WHERE token_hash = %s",
                   accounts._token_hash(token))
        self.assertEqual(self._me(token).status_code, 401)

    def test_activity_refreshes_last_seen_and_it_is_committed(self):
        token = self._token()
        self._set(token, last_seen_at="10 minutes")
        self.assertEqual(self._me(token).status_code, 200)
        (age,), = self._fetch("SELECT extract(epoch FROM now() - last_seen_at) FROM {c}.sessions WHERE token_hash = %s",
                              accounts._token_hash(token))   # a different connection: only a commit shows
        self.assertLess(age, 60, f"last_seen_at was not refreshed (still {age:.0f} s old)")

    def test_a_request_inside_the_throttle_does_not_write(self):
        token = self._token()
        self._set(token, last_seen_at="10 seconds")
        before = self._fetch("SELECT last_seen_at FROM {c}.sessions WHERE token_hash = %s", accounts._token_hash(token))
        self.assertEqual(self._me(token).status_code, 200)
        after = self._fetch("SELECT last_seen_at FROM {c}.sessions WHERE token_hash = %s", accounts._token_hash(token))
        self.assertEqual(before, after, "at most one write a minute per session")

    def test_the_expiry_shown_to_the_client_does_not_move(self):
        res = self._login().json()
        token, shown = res["token"], res["expiresAt"]
        self._set(token, last_seen_at="10 minutes")
        self.assertEqual(self._me(token).json()["expiresAt"], shown)


@pytest.mark.integration
class Purge(_Sessions):
    def _purge(self) -> int:
        with Conn() as conn:
            with conn.cursor() as cur:
                removed = accounts.purge_sessions(cur)
            conn.commit()
        return removed

    def _kinds(self) -> dict[str, str]:
        """One session of each kind, for the same user: name -> token."""
        kinds = {name: self._token() for name in (
            "live", "expired_long_ago", "expired_recently", "revoked_long_ago", "revoked_recently",
            "idle_long_ago", "idle_recently")}
        self._set(kinds["expired_long_ago"], expires_at="2 days")
        self._set(kinds["expired_recently"], expires_at="1 hour")
        self._set(kinds["revoked_long_ago"], revoked_at="2 days")
        self._set(kinds["revoked_recently"], revoked_at="1 hour")
        self._set(kinds["idle_long_ago"], last_seen_at="2 days 31 minutes")
        self._set(kinds["idle_recently"], last_seen_at="31 minutes")
        return kinds

    def test_it_deletes_what_ended_before_the_grace_period_and_nothing_else(self):
        kinds = self._kinds()
        self.assertGreaterEqual(self._purge(), 3)
        for name in ("expired_long_ago", "revoked_long_ago", "idle_long_ago"):
            self.assertTrue(self._gone(kinds[name]), f"{name} should have been purged")
        for name in ("live", "expired_recently", "revoked_recently", "idle_recently"):
            self.assertFalse(self._gone(kinds[name]), f"{name} must survive")
        self.assertEqual(self._me(kinds["live"]).status_code, 200, "the live session still works")

    def test_the_grace_period_follows_the_setting(self):
        kinds = self._kinds()
        with mock.patch.object(settings, "SESSION_PURGE_GRACE_DAYS", 0):
            self._purge()
        for name in ("expired_long_ago", "expired_recently", "revoked_long_ago", "revoked_recently",
                     "idle_long_ago", "idle_recently"):
            self.assertTrue(self._gone(kinds[name]), f"{name} should have been purged with no grace")
        self.assertFalse(self._gone(kinds["live"]))

    def test_an_idle_session_is_not_purged_when_the_idle_limit_is_off(self):
        token = self._token()
        self._set(token, last_seen_at="30 days")
        with mock.patch.object(settings, "SESSION_IDLE_MINUTES", 0):
            self._purge()
        self.assertFalse(self._gone(token), "without an idle limit it has not expired")

    def test_it_deletes_no_users_or_memberships(self):
        users = self._fetch("SELECT count(*) FROM {c}.users")
        members = self._fetch("SELECT count(*) FROM {c}.memberships")
        self._kinds()
        self._purge()
        self.assertEqual(self._fetch("SELECT count(*) FROM {c}.users"), users)
        self.assertEqual(self._fetch("SELECT count(*) FROM {c}.memberships"), members)

    def test_running_it_twice_removes_nothing_the_second_time_of_mine(self):
        kinds = self._kinds()
        self._purge()
        self._purge()
        self.assertFalse(self._gone(kinds["live"]))


@pytest.mark.integration
class PurgeScript(_Sessions):
    def test_the_script_purges_and_reports(self):
        old, live = self._token(), self._token()
        self._set(old, expires_at="3 days")
        done = subprocess.run([sys.executable, "scripts/purge_sessions.py"], cwd=ROOT, env={**os.environ},
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"Purged \d+ session")
        self.assertTrue(self._gone(old))
        self.assertFalse(self._gone(live))


@pytest.mark.integration
class StartUp(unittest.TestCase):
    """The API purges once when it starts, and never fails to start because of it."""

    def _make_expired_session(self) -> str:
        tag = os.urandom(6).hex()
        with Conn() as conn:
            with conn.cursor() as cur:
                tid = accounts.create_tenant(cur, f"su_{tag}", "Startup tenant")
                uid = accounts.create_user(cur, f"su_user_{tag}", _PW)
                accounts.add_membership(cur, uid, tid, "uploader")
                cur.execute(sql.SQL("INSERT INTO {c}.sessions (token_hash, user_id, tenant_id, expires_at) "
                                    "VALUES (%s, %s, %s, now() - interval '5 days')")
                            .format(c=sql.Identifier(settings.CONTROL_SCHEMA)), (f"th_{tag}", uid, tid))
            conn.commit()
        return f"th_{tag}"

    def _exists(self, token_hash: str) -> bool:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT 1 FROM {c}.sessions WHERE token_hash = %s")
                        .format(c=sql.Identifier(settings.CONTROL_SCHEMA)), (token_hash,))
            return cur.fetchone() is not None

    def test_start_up_removes_old_sessions(self):
        with TestClient(app):          # the pool is open only while a client is; leaving it closes the pool
            token_hash = self._make_expired_session()
            self.assertTrue(self._exists(token_hash))
        with TestClient(app):          # starting again purges
            self.assertFalse(self._exists(token_hash), "the API did not purge on start-up")

    def test_a_purge_failure_does_not_stop_start_up(self):
        with mock.patch.object(accounts, "purge_sessions", side_effect=RuntimeError("purge broke")):
            with self.assertLogs("api.main", level=logging.WARNING) as logged:
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertTrue(any("purge" in line.lower() for line in logged.output), logged.output)
