"""OIDC sign-in against a deployment-controlled IdP (#95, BR-36).

Tokens are signed with a locally generated RSA key whose JWKS is served from
a file:// URL, so nothing reaches the network.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api import oidc
from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts

_ISS, _AUD, _KID = "https://idp.example.test/realms/te", "te-migration", "test-key-1"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


_SIGNER, _OTHER = _key(), _key()


class _Oidc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig = (settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_SIGNER.public_key()))
        jwk.update({"kid": _KID, "use": "sig", "alg": "RS256"})
        cls._dir = tempfile.TemporaryDirectory()
        jwks = Path(cls._dir.name) / "jwks.json"
        jwks.write_text(json.dumps({"keys": [jwk]}))
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE = _ISS, _AUD
        settings.OIDC_JWKS_URL = jwks.as_uri()
        oidc._jwks.cache_clear()

    @classmethod
    def tearDownClass(cls):
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = cls._orig
        oidc._jwks.cache_clear()
        cls._dir.cleanup()

    @staticmethod
    def token(username="alice", key=None, kid=_KID, alg="RS256", **overrides) -> str:
        now = int(time.time())
        claims = {"iss": _ISS, "aud": _AUD, "iat": now, "exp": now + 300,
                  "sub": "abc", "preferred_username": username}
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key or _SIGNER, algorithm=alg, headers={"kid": kid})


@pytest.mark.unit
class TokenVerification(_Oidc):
    def test_valid_token_yields_the_username(self):
        self.assertEqual(oidc.username_from(self.token()), "alice")

    def test_rejected_tokens(self):
        now = int(time.time())
        cases = {
            "expired": self.token(exp=now - 10, iat=now - 400),
            "wrong issuer": self.token(iss="https://evil.example/realms/te"),
            "wrong audience": self.token(aud="some-other-app"),
            "signed by another key": self.token(key=_OTHER),
            "unknown key id": self.token(kid="not-published"),
            "no expiry": self.token(exp=None),
            "no username claim": self.token(username=None),
            "unsigned (alg none)": jwt.encode(
                {"iss": _ISS, "aud": _AUD, "exp": now + 300, "iat": now, "preferred_username": "alice"},
                None, algorithm="none", headers={"kid": _KID}),
            "garbage": "not.a.token",
        }
        for name, tok in cases.items():
            self.assertIsNone(oidc.username_from(tok), name)


@pytest.mark.integration
class OidcSignIn(_Oidc):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        super().tearDownClass()

    def setUp(self):
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.tenant, self.other, self.user = f"oi_{tag}", f"ox_{tag}", f"oidc_{tag}"
        with Conn() as conn:
            with conn.cursor() as cur:
                tid = accounts.create_tenant(cur, self.tenant, "OIDC tenant")
                accounts.create_tenant(cur, self.other, "Other")
                self.user_id = accounts.create_user(cur, self.user, uuid.uuid4().hex)
                accounts.add_membership(cur, self.user_id, tid, "reviewer")
            conn.commit()

    def _post(self, tenant, tok):
        return self.client.post("/api/auth/oidc", json={"tenant": tenant, "idToken": tok})

    def test_valid_token_for_a_member_gets_a_session(self):
        res = self._post(self.tenant, self.token(self.user))
        self.assertEqual(res.status_code, 200, res.text)
        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {res.json()['token']}"})
        self.assertEqual((me.json()["username"], me.json()["role"]), (self.user, "reviewer"))

    def test_valid_token_but_no_membership_or_account_is_401(self):
        self.assertEqual(self._post(self.other, self.token(self.user)).status_code, 401)
        self.assertEqual(self._post(self.tenant, self.token("nobody_" + uuid.uuid4().hex)).status_code, 401)

    def test_invalid_token_is_401(self):
        self.assertEqual(self._post(self.tenant, self.token(self.user, key=_OTHER)).status_code, 401)

    def test_inactive_user_is_401(self):
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f'UPDATE "{settings.CONTROL_SCHEMA}".users SET is_active = false WHERE id = %s',
                            (self.user_id,))
            conn.commit()
        self.assertEqual(self._post(self.tenant, self.token(self.user)).status_code, 401)

    def test_route_is_404_when_oidc_is_not_configured(self):
        issuer, settings.OIDC_ISSUER = settings.OIDC_ISSUER, ""
        try:
            self.assertEqual(self._post(self.tenant, self.token(self.user)).status_code, 404)
        finally:
            settings.OIDC_ISSUER = issuer


@pytest.mark.unit
class ConfigFailsClosed(unittest.TestCase):
    def setUp(self):
        self._orig = (settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL)

    def tearDown(self):
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = self._orig

    def test_off_by_default_and_complete_config_passes(self):
        settings.OIDC_ISSUER = ""
        oidc.check_config()
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = _ISS, _AUD, "https://idp/jwks"
        oidc.check_config()

    def test_missing_audience_or_insecure_jwks_url_refuses_to_start(self):
        for aud, url in (("", "https://idp/jwks"), (_AUD, "http://idp/jwks"), (_AUD, "")):
            settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = _ISS, aud, url
            with self.assertRaises(RuntimeError, msg=(aud, url)):
                oidc.check_config()
