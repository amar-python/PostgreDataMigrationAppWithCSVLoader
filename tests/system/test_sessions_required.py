"""#298 (OIT-013, SECURITY_REVIEW_PACK F8, BR-36): the shared API key is retired; data needs a session.

Before: a request with no ``Authorization`` header fell back to the shared ``X-API-Key``. It reached the
deployment's default schemas with no tenant, no role check and full delete rights, and audited only as
``api_key``. With ``API_ENV`` left at its default of ``dev`` and no key set, it needed nothing at all.

After:
  * every data route answers 401 "Sign in required" without a session;
  * ``API_ENV=dev`` alone does not open anything: anonymous access needs ``API_ALLOW_ANONYMOUS`` as well;
  * an ``X-API-Key`` header grants nothing, even one equal to an old ``API_KEY`` still in the environment;
  * a signed-in uploader gets 403 on delete and on replacing a prior load;
  * the audit log names the signed-in user, never ``api_key``.

The suite runs with the anonymous opt-in on (tests/conftest.py); every test here switches it off.
The 401 tests need no database. The session tests need PostgreSQL and fail, never skip, without it.
"""

from __future__ import annotations

import os
import re
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth import ANONYMOUS_ACTOR, anonymous_allowed
from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts
from api.tenancy import migrate_tenant, schema_for

_PW = "correct horse battery staple"
# Reachable without a session by design: uptime probes, sign-in, and the dev-only API docs.
_PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/login"), ("POST", "/api/auth/oidc")}


def _data_routes() -> list[tuple[str, str]]:
    """Every (method, path) the API serves under /api/, except the public ones, with path parameters filled."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if path.startswith("/api/") and (method.upper(), path) not in _PUBLIC:
                out.append((method.upper(), re.sub(r"\{[^}]+\}", "1", path)))
    return out


class _NoAnonymous:
    """Switch off the suite's anonymous opt-in for the duration of a test."""

    def setUp(self):
        self._saved = (settings.API_ALLOW_ANONYMOUS, settings.API_ENV)
        settings.API_ALLOW_ANONYMOUS = False
        settings.API_ENV = "dev"

    def tearDown(self):
        settings.API_ALLOW_ANONYMOUS, settings.API_ENV = self._saved


@pytest.mark.unit
@pytest.mark.security
class NoSessionNoData(_NoAnonymous, unittest.TestCase):
    # A handler that runs (it needs the database, absent here) must show up as a wrong status, not an exception.
    # The loops below collect every mismatch and assert once, so none can be lost in a subTest.
    client = TestClient(app, raise_server_exceptions=False)

    def test_the_route_list_is_not_empty(self):
        # Guards the test below against passing vacuously if the OpenAPI schema stopped listing the routers.
        self.assertGreater(len(_data_routes()), 20, _data_routes())

    def test_every_data_route_needs_a_session(self):
        wrong = [
            (method, path, res.status_code)
            for method, path in _data_routes()
            if (res := self.client.request(method, path, json={})).status_code != 401
        ]
        self.assertEqual(wrong, [], "these answered without a session")

    def test_api_env_dev_alone_is_not_anonymous(self):
        """The default API_ENV is dev; before #298 that plus an unset key left everything open."""
        self.assertFalse(anonymous_allowed())
        res = self.client.get("/api/csv/files")
        self.assertEqual((res.status_code, res.json()["detail"]), (401, "Sign in required"))

    def test_the_opt_in_outside_dev_grants_nothing(self):
        settings.API_ALLOW_ANONYMOUS = True
        seen = {}
        for env in ("prod", "staging", "test"):
            settings.API_ENV = env
            seen[env] = (anonymous_allowed(), self.client.get("/api/csv/files").status_code)
        self.assertEqual(seen, {env: (False, 401) for env in ("prod", "staging", "test")})

    def test_an_x_api_key_header_grants_nothing(self):
        old = os.environ.get("API_KEY")
        os.environ["API_KEY"] = "a-leftover-shared-key"
        try:
            keys = ("a-leftover-shared-key", "anything", "")
            seen = {key: self.client.get("/api/csv/files", headers={"X-API-Key": key}).status_code for key in keys}
            self.assertEqual(seen, dict.fromkeys(keys, 401))
        finally:
            if old is None:
                os.environ.pop("API_KEY", None)
            else:
                os.environ["API_KEY"] = old

    def test_the_shared_key_setting_is_gone(self):
        self.assertFalse(hasattr(settings, "API_KEY"))

    def test_cors_no_longer_offers_the_key_header(self):
        res = self.client.options(
            "/api/csv/files",
            headers={
                "Origin": settings.CORS_ORIGINS[0],
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
        self.assertNotIn("x-api-key", res.headers.get("access-control-allow-headers", "").lower())


@pytest.mark.integration  # not also `security`: the free-tier job selects that marker and has no database
class SignedInCallersAreScopedAndNamed(_NoAnonymous, unittest.TestCase):
    """With sessions only, deletes are role-checked and the audit log names the user."""

    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API (is PostgreSQL up, is PGPASSWORD set?): {exc}") from None
        cls.slug = f"s298_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.headers = {}
        with Conn() as conn:
            with conn.cursor() as cur:
                tid = accounts.create_tenant(cur, cls.slug, "Sessions required test")
                for role in ("uploader", "tenant_admin"):
                    uid = accounts.create_user(cur, f"{cls.slug}_{role}", _PW)
                    accounts.add_membership(cur, uid, tid, role)
            conn.commit()
        migrate_tenant(cls.slug)
        for role in ("uploader", "tenant_admin"):
            res = cls.client.post(
                "/api/auth/login", json={"tenant": cls.slug, "username": f"{cls.slug}_{role}", "password": _PW}
            )
            assert res.status_code == 200, res.text
            cls.headers[role] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(cls.slug))))
                cur.execute(
                    sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(sql.Identifier(settings.CONTROL_SCHEMA)),
                    (cls.slug,),
                )
                cur.execute(
                    sql.SQL("DELETE FROM {}.users WHERE username LIKE %s").format(
                        sql.Identifier(settings.CONTROL_SCHEMA)
                    ),
                    (f"{cls.slug}_%",),
                )
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def _upload(self, role: str, **body) -> dict:
        res = self.client.post("/api/csv/upload", headers=self.headers[role], json=body)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["status"], "ok", res.text)
        return res.json()

    def _audit(self) -> list[dict]:
        res = self.client.get("/api/audit/log", headers=self.headers["tenant_admin"], params={"limit": 200})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["entries"]

    def test_an_uploader_may_not_delete(self):
        tag = uuid.uuid4().hex[:10]
        up = self._upload("tenant_admin", fileName=f"d_{tag}.csv", content=f"k\n{tag}\n")
        res = self.client.delete(f"/api/csv/files/{up['fileId']}", headers=self.headers["uploader"])
        self.assertEqual(res.status_code, 403, res.text)
        files = self.client.get("/api/csv/files", headers=self.headers["tenant_admin"]).json()
        self.assertIn(str(up["fileId"]), {str(f["id"]) for f in files}, "the file must remain")

    def test_an_uploader_may_not_replace_a_prior_load(self):
        tag = uuid.uuid4().hex[:10]
        name = f"te_{tag}.csv"
        self._upload(
            "tenant_admin",
            fileName=name,
            mode="te",
            targetTable="organisations",
            content=f"name,org_type,country\nORG_A_{tag},government,AU\n",
        )
        again = self.client.post(
            "/api/csv/upload",
            headers=self.headers["uploader"],
            json={
                "fileName": name,
                "mode": "te",
                "targetTable": "organisations",
                "content": f"name,org_type,country\nORG_B_{tag},government,AU\n",
            },
        )
        self.assertEqual(again.status_code, 403, again.text)

    def test_the_audit_log_names_the_signed_in_user(self):
        tag = uuid.uuid4().hex[:10]
        name = f"a_{tag}.csv"
        up = self._upload("uploader", fileName=name, content=f"k\n{tag}\n")
        deleted = self.client.delete(f"/api/csv/files/{up['fileId']}", headers=self.headers["tenant_admin"])
        self.assertEqual(deleted.status_code, 200, deleted.text)
        actors = {e["action"]: e["actor"] for e in self._audit() if e.get("fileName") == name}
        self.assertEqual(actors, {"upload": f"{self.slug}_uploader", "delete": f"{self.slug}_tenant_admin"})
        self.assertNotIn("api_key", actors.values())
        self.assertNotIn(ANONYMOUS_ACTOR, actors.values())
