"""OIDC: the https:// JWKS fetch path (#113, the part testable without the real IdP).

#95 was tested with a file:// JWKS only, so PyJWT's PyJWKClient (the https:// path a
deployment uses) was never run. Here the IdP is a local TLS server with a throwaway
self-signed certificate, so the real fetch, the TLS check and key rotation all run.

What this cannot show is a sign-in against the deployment's own Keycloak or Entra ID:
#113 stays open for that one manual run.
"""

from __future__ import annotations

import datetime
import http.server
import ipaddress
import json
import os
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from api import oidc
from api.config import settings

_ISS, _AUD = "https://idp.example.test/realms/te", "te-migration"


def _rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private_key, kid: str) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


def _self_signed(directory: Path) -> tuple[Path, Path]:
    key = _rsa()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return cert_path, key_path


@pytest.mark.unit
class HttpsJwksFetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cert, key = _self_signed(Path(cls._dir.name))
        cls.keys = {"key-1": _rsa()}
        cls.hits = []

        outer = cls

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                body = json.dumps({"keys": [_jwk(k, kid) for kid, k in outer.keys.items()]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # keep test output quiet
                pass

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        cls.server.socket = ctx.wrap_socket(cls.server.socket, server_side=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

        cls._env = {k: os.environ.get(k) for k in ("SSL_CERT_FILE", "NO_PROXY", "no_proxy")}
        os.environ["SSL_CERT_FILE"] = str(cert)  # trust the throwaway certificate, and only it
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        cls._orig = (settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL)
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE = _ISS, _AUD
        settings.OIDC_JWKS_URL = f"https://127.0.0.1:{cls.server.server_port}/jwks"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = cls._orig
        for k, v in cls._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        oidc._jwks.cache_clear()
        cls._dir.cleanup()

    def setUp(self):
        oidc._jwks.cache_clear()
        self.hits.clear()

    @staticmethod
    def _token(key, kid: str, username: str = "alice") -> str:
        now = int(time.time())
        claims = {"iss": _ISS, "aud": _AUD, "iat": now, "exp": now + 300, "sub": "s", "preferred_username": username}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})

    def test_a_token_signed_by_a_key_fetched_over_https_is_accepted(self):
        self.assertEqual(oidc.username_from(self._token(self.keys["key-1"], "key-1")), "alice")
        self.assertEqual(self.hits, ["/jwks"], "the key must come from the https endpoint")

    def test_a_token_signed_by_an_unpublished_key_is_rejected(self):
        self.assertIsNone(oidc.username_from(self._token(_rsa(), "key-1")))

    def _rotate_to_a_new_key(self, cooldown: float, username: str):
        self.assertEqual(oidc.username_from(self._token(self.keys["key-1"], "key-1")), "alice")
        oidc._jwks(settings.OIDC_JWKS_URL).cooldown_duration = cooldown
        self.keys["key-2"] = _rsa()  # published at the IdP after the first fetch
        try:
            return oidc.username_from(self._token(self.keys["key-2"], "key-2", username))
        finally:
            self.keys.pop("key-2", None)

    def test_a_rotated_key_is_picked_up_without_a_restart(self):
        # Past PyJWT's refresh cooldown, an unknown key id triggers a re-fetch.
        self.assertEqual(self._rotate_to_a_new_key(cooldown=0, username="bob"), "bob")
        self.assertEqual(self.hits, ["/jwks", "/jwks"])

    def test_unknown_key_ids_cannot_make_the_api_hammer_the_idp(self):
        # Inside the cooldown (PyJWT's default is 30 s) an unknown key id is refused, not re-fetched:
        # a stream of forged tokens must not become a stream of requests to the IdP.
        self.assertIsNone(self._rotate_to_a_new_key(cooldown=30, username="bob"))
        self.assertEqual(self.hits, ["/jwks"])

    def test_a_certificate_that_is_not_trusted_is_refused(self):
        with tempfile.TemporaryDirectory() as other:
            stranger, _ = _self_signed(Path(other))  # trusted instead of the server's own certificate
            trusted = os.environ["SSL_CERT_FILE"]
            os.environ["SSL_CERT_FILE"] = str(stranger)
            try:
                oidc._jwks.cache_clear()
                self.assertIsNone(oidc.username_from(self._token(self.keys["key-1"], "key-1")),
                                  "a JWKS endpoint whose certificate isn't trusted must not yield a session")
            finally:
                os.environ["SSL_CERT_FILE"] = trusted
