"""scripts/check_oidc.py, the real-IdP check (#113), run against a local TLS identity provider.

Each stage can fail on its own and says why, and neither the ID token nor the session token is ever printed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

import jwt

from api import oidc
from api.config import settings
from tests.oidc_stub import LocalIdp, new_key

_AUD = "te-migration"
_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "check_oidc.py"


def _script():
    spec = importlib.util.spec_from_file_location("check_oidc", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module      # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


def _token(key, kid, **overrides) -> str:
    now = int(time.time())
    claims = {"aud": _AUD, "iat": now, "exp": now + 300, "sub": "abc", "preferred_username": "alice"}
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": kid})


class _ApiStub:
    """A plain-http stand-in for the API's POST /api/auth/oidc."""

    def __init__(self, status: int = 200):
        outer = self
        self.seen: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                outer.seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"token": "SESSION-SECRET-TOKEN", "username": "alice", "tenant": "acme", "role": "reviewer",
                                   "expiresAt": "2026-11-10T00:00:00+00:00"} if status == 200 else {"detail": "no"}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class _Base(unittest.TestCase):
    def setUp(self):
        self.script = _script()
        self._orig = (settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL, settings.OIDC_USERNAME_CLAIM)
        oidc._jwks.cache_clear()
        self.key = new_key()
        self.idp = LocalIdp({"k1": self.key})
        self.addCleanup(self.idp.close)
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL = self.idp.issuer, _AUD, self.idp.jwks_url
        settings.OIDC_USERNAME_CLAIM = "preferred_username"
        self.trust = self.idp.trust()
        self.trust.__enter__()

    def tearDown(self):
        self.trust.__exit__(None, None, None)
        settings.OIDC_ISSUER, settings.OIDC_AUDIENCE, settings.OIDC_JWKS_URL, settings.OIDC_USERNAME_CLAIM = self._orig
        oidc._jwks.cache_clear()

    def token(self, **overrides) -> str:
        overrides.setdefault("iss", self.idp.issuer)
        return _token(self.key, "k1", **overrides)

    def by_step(self, results):
        return {r.step: r for r in results}


class EveryStageCanPass(_Base):
    def test_a_good_token_passes_every_stage(self):
        results = self.script.run_checks(self.token())
        self.assertEqual([(r.step, r.status) for r in results],
                         [("config", "ok"), ("discovery", "ok"), ("keys", "ok"), ("token", "ok")], results)
        self.assertIn("1 signing key(s): k1", results[2].detail)
        self.assertIn("preferred_username = 'alice'", results[3].detail)

    def test_the_sign_in_stage_reports_the_role_and_never_the_session_token(self):
        api = _ApiStub()
        self.addCleanup(api.close)
        results = self.script.run_checks(self.token(), api.url, "acme")
        self.assertEqual(results[-1].status, "ok", results[-1])
        self.assertIn("role 'reviewer'", results[-1].detail)
        self.assertNotIn("SESSION-SECRET-TOKEN", results[-1].detail)
        self.assertEqual(api.seen[0]["tenant"], "acme")


class EachStageNamesItsCause(_Base):
    def test_no_oidc_config(self):
        settings.OIDC_ISSUER = ""
        self.assertEqual([(r.step, r.status) for r in self.script.run_checks("x")], [("config", "fail")])

    def test_plain_http_key_url(self):
        settings.OIDC_JWKS_URL = "http://idp.example.test/jwks"
        self.assertIn("https:// or file://", self.script.run_checks("x")[0].detail)

    def test_an_issuer_that_differs_from_the_idps_own_is_a_warning_naming_both(self):
        settings.OIDC_ISSUER = self.idp.issuer + "/"          # the classic trailing slash; discovery lives at the same base
        discovery = self.by_step(self.script.run_checks(self.token()))["discovery"]
        self.assertEqual(discovery.status, "warn")
        self.assertIn("trailing slash", discovery.detail)

    def test_a_certificate_the_host_does_not_trust_says_what_to_set(self):
        with patch.dict(os.environ):                           # restored on exit
            os.environ.pop("SSL_CERT_FILE", None)               # the host doesn't know this IdP's CA
            keys = self.by_step(self.script.run_checks(self.token(), discovery=False))["keys"]
        self.assertEqual(keys.status, "fail")
        self.assertIn("SSL_CERT_FILE", keys.detail)

    def test_wrong_audience_expired_and_wrong_issuer_each_say_why(self):
        now = int(time.time())
        cases = {"OIDC_AUDIENCE": self.token(aud="another-app"), "expired": self.token(exp=now - 5, iat=now - 400),
                 "`iss` must equal": self.token(iss="https://evil.example/realms/te")}
        for expected, token in cases.items():
            result = self.by_step(self.script.run_checks(token, discovery=False))["token"]
            self.assertEqual(result.status, "fail", expected)
            self.assertIn(expected, result.detail)

    def test_a_token_signed_by_someone_else_is_rejected(self):
        forged = _token(new_key(), "k1", iss=self.idp.issuer)
        result = self.by_step(self.script.run_checks(forged, discovery=False))["token"]
        self.assertEqual(result.status, "fail")
        self.assertIn("InvalidSignatureError", result.detail)

    def test_a_missing_username_claim_names_the_setting_to_change(self):
        result = self.by_step(self.script.run_checks(self.token(preferred_username=None), discovery=False))["token"]
        self.assertEqual(result.status, "fail")
        self.assertIn("OIDC_USERNAME_CLAIM", result.detail)

    def test_something_that_isnt_a_token(self):
        result = self.by_step(self.script.run_checks("not-a-token", discovery=False))["token"]
        self.assertEqual(result.status, "fail")
        self.assertIn("well-formed", result.detail)

    def test_the_api_refusing_or_not_having_oidc_is_explained(self):
        for status, expected in ((401, "isn't a member"), (404, "OIDC_ISSUER set in its own environment")):
            api = _ApiStub(status)
            self.addCleanup(api.close)
            result = self.script.check_api(api.url, "acme", self.token())
            self.assertEqual(result.status, "fail")
            self.assertIn(str(status), result.detail)
            self.assertIn(expected, result.detail)


class CommandLine(_Base):
    def run_main(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.dict(os.environ, env or {}):
            code = self.script.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_success_prints_a_summary_and_exits_zero_without_printing_the_token(self):
        token = self.token()
        code, out, _ = self.run_main(env={"ID_TOKEN": token})
        self.assertEqual(code, 0, out)
        self.assertIn("OK: the token verifies", out)
        self.assertNotIn(token, out)
        self.assertNotIn(token.split(".")[1], out, "not even its payload")

    def test_with_the_api_it_checks_the_sign_in_and_hides_the_session_token(self):
        api = _ApiStub()
        self.addCleanup(api.close)
        code, out, _ = self.run_main("--api", api.url, "--tenant", "acme", env={"ID_TOKEN": self.token()})
        self.assertEqual(code, 0, out)
        self.assertIn("sign-in works end to end", out)
        self.assertNotIn("SESSION-SECRET-TOKEN", out)

    def test_failure_exits_one_and_lists_the_failed_stages(self):
        code, out, _ = self.run_main(env={"ID_TOKEN": self.token(aud="another-app")})
        self.assertEqual(code, 1)
        self.assertIn("FAILED: token", out)

    def test_no_token_is_exit_two_and_the_token_is_not_a_command_line_argument(self):
        code, _, err = self.run_main(env={"ID_TOKEN": ""})
        self.assertEqual(code, 2)
        self.assertIn("ID_TOKEN", err)
        with self.assertRaises(SystemExit):
            self.run_main("--token", "abc")                      # no such option: a token on the command line is refused

    def test_token_from_a_file(self):
        path = Path(os.environ.get("TMPDIR", "/tmp")) / f"idtoken_{os.getpid()}.txt"
        path.write_text(self.token() + "\n")
        self.addCleanup(path.unlink)
        code, out, _ = self.run_main("--token-file", str(path), env={"ID_TOKEN": ""})
        self.assertEqual(code, 0, out)

    def test_api_and_tenant_go_together(self):
        with self.assertRaises(SystemExit):
            self.run_main("--api", "http://localhost:8000", env={"ID_TOKEN": "x"})
