"""A local identity provider for tests: a real TLS server publishing a JWKS (#113, BR-36).

``LocalIdp`` serves ``https://localhost:<port>/jwks`` with a throwaway self-signed certificate, so the
API's ``https://`` key fetch (PyJWT's PyJWKClient) runs for real without leaving the machine. Trust the
certificate with ``trust()``, which points ``SSL_CERT_FILE`` at it. Keys can be swapped while it runs, to
rehearse an IdP rotating its signing keys. ``blackhole()`` is a port that accepts a connection and never
answers, for an IdP that hangs.
"""

from __future__ import annotations

import contextlib
import datetime
import ipaddress
import json
import os
import socket
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(private_key, kid: str) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


def _self_signed(directory: Path) -> tuple[Path, Path]:
    key = new_key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "idp.pem", directory / "idp.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return cert_path, key_path


class LocalIdp:
    def __init__(self, keys: dict[str, object] | None = None):
        self.keys = dict(keys or {})          # kid -> private key; what /jwks publishes
        self.requests: list[str] = []
        self._dir = tempfile.TemporaryDirectory()
        self.cert_path, key_path = _self_signed(Path(self._dir.name))
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's name
                outer.requests.append(self.path)
                if self.path == "/.well-known/openid-configuration":
                    body = json.dumps({"issuer": outer.issuer, "jwks_uri": outer.jwks_url}).encode()
                elif self.path == "/jwks":
                    body = json.dumps({"keys": [jwk_for(k, kid) for kid, k in outer.keys.items()]}).encode()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert_path, key_path)
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self.port = self._server.server_address[1]
        self.jwks_url = f"https://localhost:{self.port}/jwks"
        self.issuer = f"https://localhost:{self.port}"   # discovery is at <issuer>/.well-known/openid-configuration
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def trust(self):
        """Make the default TLS context (what PyJWKClient uses) accept this server's certificate."""
        return patch.dict(os.environ, {"SSL_CERT_FILE": str(self.cert_path)})

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._dir.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@contextlib.contextmanager
def blackhole():
    """A loopback port that accepts connections and never answers. Yields its https URL."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept():
        listener.settimeout(0.2)
        while not stop.is_set():
            with contextlib.suppress(OSError):
                held.append(listener.accept()[0])

    threading.Thread(target=accept, daemon=True).start()
    try:
        yield f"https://localhost:{listener.getsockname()[1]}/jwks"
    finally:
        stop.set()
        time.sleep(0.25)
        for conn in held:
            conn.close()
        listener.close()


def closed_port_url() -> str:
    """An https URL on a loopback port nothing is listening on."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return f"https://localhost:{port}/jwks"
