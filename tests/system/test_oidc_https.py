"""OIDC key fetch over https:// (#113, BR-36).

#95's tests used a local RSA key and a file:// JWKS, so the https:// path (PyJWT's PyJWKClient) ran in no
test. These run it for real against a local TLS server (tests/oidc_stub.py): a trusted certificate,
key rotation, an untrusted certificate, an IdP that is down and one that hangs. They don't replace one
sign-in against the deployment's real IdP (docs/OIDC_REAL_IDP_CHECK.md), which proves its certificate,
issuer, audience and claims.
"""

from __future__ import annotations

import os
import time
import unittest
import uuid
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from api import oidc
from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts
from tests.oidc_stub import LocalIdp, blackhole, closed_port_url, new_key

_ISS, _AUD = "https://idp.example.test/realms/te", "te-migration"


def _token(key, kid, username="alice", **overrides) -> str:
    now = int(time.time())
    claims = {"iss": _ISS, "aud": _AUD, "iat": now, "exp": now + 300, "sub": "abc", "preferred_username": username}
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": kid})


class _Https(unittest.TestCase):
    def setUp(self):
        self._orig = (settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL)
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE = _ISS, _AUD
        oidc._jwks.cache_clear()

    def tearDown(self):
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = self._orig
        oidc._jwks.cache_clear()


class KeyFetchOverHttps(_Https):
    def test_a_token_is_verified_with_keys_fetched_over_https(self):
        key = new_key()
        with LocalIdp({"k1": key}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            oidc.check_config()
            self.assertEqual(oidc.username_from(_token(key, "k1")), "alice")
            self.assertEqual(idp.requests, ["/jwks"], "the key set was fetched once, over TLS")

    def test_the_key_set_is_cached_between_sign_ins(self):
        key = new_key()
        with LocalIdp({"k1": key}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            for _ in range(3):
                self.assertEqual(oidc.username_from(_token(key, "k1")), "alice")
            self.assertEqual(len(idp.requests), 1)

    def test_a_forged_token_is_refused_even_when_it_names_a_published_key(self):
        with LocalIdp({"k1": new_key()}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            self.assertIsNone(oidc.username_from(_token(new_key(), "k1")))

    def test_claims_are_still_checked_after_the_signature(self):
        key = new_key()
        with LocalIdp({"k1": key}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            for name, token in {"audience": _token(key, "k1", aud="another-app"),
                                "issuer": _token(key, "k1", iss="https://evil.example/realms/te"),
                                "expiry": _token(key, "k1", exp=int(time.time()) - 5, iat=int(time.time()) - 400)}.items():
                self.assertIsNone(oidc.username_from(token), name)

    def test_a_rotated_signing_key_is_picked_up_without_a_restart_after_the_cooldown(self):
        old, new = new_key(), new_key()
        with LocalIdp({"old": old}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            self.assertEqual(oidc.username_from(_token(old, "old")), "alice")
            client = oidc._jwks(idp.jwks_url)
            client.cooldown_duration = 0.5                         # PyJWT's default is 30 s; shortened to keep the test quick
            idp.keys = {"old": old, "new": new}                    # the IdP rotates
            self.assertIsNone(oidc.username_from(_token(new, "new")), "refused inside the cooldown after the last fetch")
            self.assertEqual(len(idp.requests), 1, "...and that didn't cost the IdP a request")
            time.sleep(0.6)
            self.assertEqual(oidc.username_from(_token(new, "new")), "alice", "after the cooldown the key set is re-fetched")
            self.assertEqual(oidc.username_from(_token(old, "old")), "alice", "the old key still works during the overlap")
            self.assertEqual(len(idp.requests), 2)

    def test_random_key_ids_cannot_make_the_api_hammer_the_idp(self):
        key = new_key()
        with LocalIdp({"k1": key}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            self.assertEqual(oidc.username_from(_token(key, "k1")), "alice")
            for i in range(25):
                self.assertIsNone(oidc.username_from(_token(new_key() if i == 0 else key, f"made-up-{i}")))
            self.assertEqual(len(idp.requests), 1, "the unknown ids were refused without re-fetching")


class WhenTheIdpCannotBeTrustedOrReached(_Https):
    def test_a_certificate_the_host_does_not_trust_fails_closed(self):
        key = new_key()
        with LocalIdp({"k1": key}) as idp:                           # no idp.trust(): self-signed and unknown
            settings.OIDC_JWKS_URL = idp.jwks_url
            self.assertIsNone(oidc.username_from(_token(key, "k1")))
            self.assertEqual(idp.requests, [], "the TLS handshake failed, so no request was made")

    def test_an_idp_that_is_down_fails_closed_at_once(self):
        settings.OIDC_JWKS_URL = closed_port_url()
        started = time.monotonic()
        self.assertIsNone(oidc.username_from(_token(new_key(), "k1")))
        self.assertLess(time.monotonic() - started, 3)

    def test_an_idp_that_hangs_costs_a_sign_in_the_timeout_and_no_more(self):
        self.assertEqual(oidc.JWKS_TIMEOUT_SECONDS, 5, "PyJWT's default would be 30")
        with blackhole() as url, patch.object(oidc, "JWKS_TIMEOUT_SECONDS", 1):
            settings.OIDC_JWKS_URL = url
            started = time.monotonic()
            self.assertIsNone(oidc.username_from(_token(new_key(), "k1")))
            self.assertLess(time.monotonic() - started, 4)

    def test_plain_http_key_urls_are_refused_at_startup(self):
        settings.OIDC_JWKS_URL = "http://idp.example.test/jwks"
        with self.assertRaisesRegex(RuntimeError, "https:// or file://"):
            oidc.check_config()

    def test_verify_says_why_where_username_from_only_says_no(self):
        key = new_key()
        with LocalIdp({"k1": key}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            with self.assertRaises(jwt.InvalidAudienceError):
                oidc.verify(_token(key, "k1", aud="another-app"))
            self.assertEqual(oidc.verify(_token(key, "k1"))["preferred_username"], "alice")


class SignInThroughTheApi(_Https):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_the_idp_token_becomes_a_session_with_the_members_role(self):
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        tenant, user = f"oh_{tag}", f"oidc_https_{tag}"
        with Conn() as conn, conn.cursor() as cur:
            tid = accounts.create_tenant(cur, tenant, "OIDC https")
            accounts.add_membership(cur, accounts.create_user(cur, user, "unused unused unused"), tid, "reviewer")
            conn.commit()
        key = new_key()
        with LocalIdp({"k1": key}) as idp, idp.trust():
            settings.OIDC_JWKS_URL = idp.jwks_url
            res = self.client.post("/api/auth/oidc", json={"tenant": tenant, "idToken": _token(key, "k1", username=user)})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual((res.json()["username"], res.json()["role"], res.json()["tenant"]), (user, "reviewer", tenant))
            stranger = self.client.post("/api/auth/oidc", json={"tenant": tenant, "idToken": _token(key, "k1", username="nobody")})
            self.assertEqual(stranger.status_code, 401, "a valid token for someone who isn't a member gets nothing")
            forged = self.client.post("/api/auth/oidc", json={"tenant": tenant, "idToken": _token(new_key(), "k1", username=user)})
            self.assertEqual(forged.status_code, 401)
        with Conn() as conn, conn.cursor() as cur:
            from psycopg2 import sql
            from api.tenancy import schema_for
            control = sql.Identifier(settings.CONTROL_SCHEMA)
            cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(control), (tenant,))
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE username = %s").format(control), (user,))
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(tenant))))
            conn.commit()
