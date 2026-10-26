"""Role-based authorisation matrix (M2c, #94, BR-36).

The unit test keeps docs/ROLES.md and api/auth.PERMISSIONS in step. The
integration test tries every role against every protected route.
"""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth import PERMISSIONS
from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts
from api.services.accounts import ROLES
from api.tenancy import migrate_tenant, schema_for

_PW = "correct horse battery staple"
_DOC = Path(__file__).resolve().parent.parent / "docs" / "ROLES.md"
# action -> (method, path); {table} and {id} are filled per run.
_ROUTES = {
    "preview": ("POST", "/api/csv/preview"),
    "upload": ("POST", "/api/csv/upload"),
    "list_files": ("GET", "/api/csv/files"),
    "read_rows": ("GET", "/api/csv/tables/{table}/rows"),
    "list_te": ("GET", "/api/te/tables"),
    "delete_file": ("DELETE", "/api/csv/files/{id}"),
    "read_audit": ("GET", "/api/audit/log"),
}


def _doc_matrix() -> dict[str, frozenset[str]]:
    rows = [ln for ln in _DOC.read_text(encoding="utf-8").splitlines() if ln.startswith("| ")]
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    out = {}
    for ln in rows[1:]:   # the |---| separator does not start with "| "
        cells = [c.strip() for c in ln.strip("|").split("|")]
        out[cells[0]] = frozenset(r for r, c in zip(header[2:], cells[2:]) if c == "✓")
    return out


@pytest.mark.unit
class MatrixIsDocumented(unittest.TestCase):
    def test_docs_table_matches_the_enforced_permissions(self):
        self.assertEqual(_doc_matrix(), PERMISSIONS)

    def test_every_action_has_a_route_and_only_known_roles(self):
        self.assertEqual(set(PERMISSIONS), set(_ROUTES))
        for action, roles in PERMISSIONS.items():
            self.assertTrue(roles <= set(ROLES), action)


@pytest.mark.integration
class RoleMatrixOverTheApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        cls.slug = f"roles_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.headers = {}
        with Conn() as conn:
            with conn.cursor() as cur:
                tid = accounts.create_tenant(cur, cls.slug, "Roles test")
                for role in ROLES:
                    uid = accounts.create_user(cur, f"{cls.slug}_{role}", _PW)
                    accounts.add_membership(cur, uid, tid, role)
            conn.commit()
        migrate_tenant(cls.slug)
        for role in ROLES:
            res = cls.client.post("/api/auth/login", json={
                "tenant": cls.slug, "username": f"{cls.slug}_{role}", "password": _PW})
            assert res.status_code == 200, res.text
            cls.headers[role] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(cls.slug))))
                cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(
                    sql.Identifier(settings.CONTROL_SCHEMA)), (cls.slug,))
                cur.execute(sql.SQL("DELETE FROM {}.users WHERE username LIKE %s").format(
                    sql.Identifier(settings.CONTROL_SCHEMA)), (f"{cls.slug}_%",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def _file(self) -> tuple[str, str]:
        tag = uuid.uuid4().hex[:10]
        res = self.client.post("/api/csv/upload", headers=self.headers["tenant_admin"],
                               json={"fileName": f"r_{tag}.csv", "content": f"k\n{tag}\n"}).json()
        assert res["status"] == "ok", res
        return res["tableName"], res["fileId"]

    def _call(self, role: str, action: str) -> int:
        method, path = _ROUTES[action]
        table, file_id = self._file()
        body = None
        if action in ("preview", "upload"):
            tag = uuid.uuid4().hex[:10]
            body = {"fileName": f"p_{tag}.csv", "content": f"k\n{tag}\n"}
        res = self.client.request(method, path.format(table=table, id=file_id),
                                  headers=self.headers[role], json=body)
        return res.status_code

    def test_every_role_against_every_route(self):
        for action, allowed in PERMISSIONS.items():
            for role in ROLES:
                with self.subTest(action=action, role=role):
                    code = self._call(role, action)
                    if role in allowed:
                        self.assertNotIn(code, (401, 403), f"{role} should be allowed to {action}")
                        self.assertLess(code, 500)
                    else:
                        self.assertEqual(code, 403, f"{role} must be refused {action}")

    def test_no_session_requests_are_not_role_checked(self):
        self.assertEqual(self.client.get("/api/audit/log").status_code, 200)
