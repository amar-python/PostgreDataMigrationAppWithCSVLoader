"""Standing cross-tenant negative tests (M2b, #93, BR-36; ADR-0003).

Two tenants, each with a tenant admin (the most privileged role). Nothing one tenant does may be visible to
or changeable by the other, or by a request that has no session.
Integration: needs a live PostgreSQL. Fails (never skips) without one.
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
from api.tenancy import migrate_tenant, schema_for

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")
_PW = "correct horse battery staple"


@pytest.mark.integration
class CrossTenantIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # DELETE is off by default (API_ALLOW_DESTRUCTIVE); enable it so the
        # cross-tenant delete attempt reaches the tenant check.
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.slugs = {"a": f"iso_a_{tag}", "b": f"iso_b_{tag}"}
        with Conn() as conn:
            with conn.cursor() as cur:
                for key, slug in cls.slugs.items():
                    tid = accounts.create_tenant(cur, slug, f"Tenant {key}")
                    uid = accounts.create_user(cur, f"{slug}_user", _PW)
                    accounts.add_membership(cur, uid, tid, "tenant_admin")  # full rights: isolation must still hold
            conn.commit()
        for slug in cls.slugs.values():
            migrate_tenant(slug)
        cls.headers = {}
        for key, slug in cls.slugs.items():
            res = cls.client.post("/api/auth/login", json={
                "tenant": slug, "username": f"{slug}_user", "password": _PW})
            assert res.status_code == 200, res.text
            cls.headers[key] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        with Conn() as conn:
            with conn.cursor() as cur:
                for slug in cls.slugs.values():
                    cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(slug))))
                    cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(
                        sql.Identifier(settings.CONTROL_SCHEMA)), (slug,))
                    cur.execute(sql.SQL("DELETE FROM {}.users WHERE username = %s").format(
                        sql.Identifier(settings.CONTROL_SCHEMA)), (f"{slug}_user",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def _upload(self, who: str, name: str, content: str) -> dict:
        res = self.client.post("/api/csv/upload", headers=self.headers[who],
                               json={"fileName": name, "content": content})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _files(self, who: str | None) -> list[dict]:
        res = self.client.get("/api/csv/files", headers=self.headers.get(who, {}))
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _fresh(self) -> tuple[str, str]:
        tag = uuid.uuid4().hex[:10]
        return f"iso_{tag}.csv", f"k,v\n1,{tag}\n2,{tag}\n"

    def test_upload_lands_in_the_tenants_own_schema(self):
        name, content = self._fresh()
        res = self._upload("a", name, content)
        self.assertEqual(res["status"], "ok", res)
        with Conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
                        (res["tableName"],))
            self.assertEqual([r[0] for r in cur.fetchall()], [schema_for(self.slugs["a"])])

    def test_other_tenant_cannot_list_read_or_delete(self):
        name, content = self._fresh()
        res = self._upload("a", name, content)
        table, file_id = res["tableName"], res["fileId"]
        self.assertIn(name, [f["file_name"] for f in self._files("a")])
        self.assertNotIn(name, [f["file_name"] for f in self._files("b")])
        read = self.client.get(f"/api/csv/tables/{table}/rows", headers=self.headers["b"])
        self.assertEqual(read.status_code, 404, read.text)
        delete = self.client.delete(f"/api/csv/files/{file_id}", headers=self.headers["b"])
        self.assertEqual(delete.status_code, 404, delete.text)
        self.assertIn(name, [f["file_name"] for f in self._files("a")], "A's file must survive B's delete")
        rows = self.client.get(f"/api/csv/tables/{table}/rows", headers=self.headers["a"])
        self.assertEqual(rows.status_code, 200, rows.text)

    def test_requests_without_a_session_see_no_tenant_data(self):
        name, content = self._fresh()
        res = self._upload("a", name, content)
        self.assertNotIn(name, [f["file_name"] for f in self._files(None)])
        read = self.client.get(f"/api/csv/tables/{res['tableName']}/rows")
        self.assertEqual(read.status_code, 404, read.text)

    def test_duplicate_detection_is_per_tenant(self):
        name, content = self._fresh()
        self.assertEqual(self._upload("a", name, content)["status"], "ok")
        self.assertEqual(self._upload("a", "again_" + name, content)["status"], "duplicate_file")
        self.assertEqual(self._upload("b", name, content)["status"], "ok",
                         "the same file in another tenant is not a duplicate")

    def test_audit_log_is_per_tenant(self):
        name, content = self._fresh()
        self._upload("a", name, content)

        def names(who):
            res = self.client.get("/api/audit/log?limit=200", headers=self.headers.get(who, {}))
            self.assertEqual(res.status_code, 200, res.text)
            return [e["fileName"] for e in res.json()["entries"]]

        self.assertIn(name, names("a"))
        self.assertNotIn(name, names("b"))
        self.assertNotIn(name, names(None))

    def test_te_mode_is_refused_for_tenants_until_99(self):
        res = self.client.post("/api/csv/upload", headers=self.headers["a"], json={
            "fileName": "t.csv", "content": "name,org_type,country\nX,government,AU\n",
            "mode": "te", "targetTable": "organisations"})
        self.assertEqual(res.status_code, 409, res.text)

    def test_invalid_session_is_401_not_a_fallback_to_default(self):
        res = self.client.get("/api/csv/files", headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(res.status_code, 401, res.text)

    def test_tenant_schema_is_at_head_with_its_own_registry(self):
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT version_num FROM {}.alembic_version").format(
                sql.Identifier(schema_for(self.slugs["b"]))))
            self.assertEqual(cur.fetchone()[0], "0004")
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                        (schema_for(self.slugs["b"]),))
            self.assertTrue({"csv_files", "audit_log"} <= {r[0] for r in cur.fetchall()})

    def test_concurrent_requests_never_see_another_tenants_schema(self):
        from concurrent.futures import ThreadPoolExecutor

        marks = {}
        for who in ("a", "b"):
            name, content = self._fresh()
            self._upload(who, name, content)
            marks[who] = name

        def visible(who):
            return who, {f["file_name"] for f in self._files(who)} & set(marks.values())

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(visible, ["a", "b", None] * 20))
        for who, seen in results:
            self.assertEqual(seen, {marks[who]} if who else set(), who)
