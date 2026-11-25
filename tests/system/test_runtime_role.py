"""The API's runtime role can only read and insert the append-only tables (M3d, #107; BR-24, BR-35).

Integration: needs a live PostgreSQL and an owner that can create roles (CI's
postgres superuser). Fails (never skips) without one. Runs the real
scripts/create_app_role.py, then drives the API as that role.

#297: a signed-in tenant's requests run as the tenant's own role, which the runtime role may switch to but does
not inherit, and the runtime role has no rights of its own on any tenant's schema.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from pydantic import SecretStr

from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts
from api.tenancy import drop_tenant_role, migrate_tenant, role_for, schema_for

_ROOT = Path(__file__).resolve().parents[2]


def _owner():
    return psycopg2.connect(
        host=settings.PG_HOST,
        port=settings.PG_PORT,
        user=settings.PG_USER,
        password=settings.PG_PASSWORD.get_secret_value(),
        dbname=settings.PG_DATABASE,
    )


@pytest.mark.integration
class RuntimeRole(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.role = f"te_app_test_{uuid.uuid4().hex[:8]}"
        cls.tmp = tempfile.TemporaryDirectory()
        env_file = Path(cls.tmp.name) / "app-db.env"
        # RV-S3 (#173): --env is mandatory. The role and credential file are
        # still overridden here so each run gets a unique, disposable role.
        run = subprocess.run(
            [
                sys.executable,
                "scripts/create_app_role.py",
                "--env",
                "test",
                "--role",
                cls.role,
                "--env-file",
                str(env_file),
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr
        cls.script_stdout = run.stdout
        values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        cls.env_mode = env_file.stat().st_mode & 0o777
        cls._orig = (settings.APP_DB_USER, settings.APP_DB_PASSWORD, settings.allow_destructive)
        settings.APP_DB_USER, settings.APP_DB_PASSWORD = values["APP_DB_USER"], SecretStr(values["APP_DB_PASSWORD"])
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        settings.APP_DB_USER, settings.APP_DB_PASSWORD, settings.allow_destructive = cls._orig
        with _owner() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP OWNED BY {r}; DROP ROLE {r}").format(r=sql.Identifier(cls.role)))
        cls.tmp.cleanup()

    def _as_runtime(self):
        return psycopg2.connect(
            host=settings.PG_HOST,
            port=settings.PG_PORT,
            user=settings.APP_DB_USER,
            password=settings.APP_DB_PASSWORD.get_secret_value(),
            dbname=settings.PG_DATABASE,
        )

    def test_script_keeps_the_password_out_of_its_output(self):
        self.assertIn(self.role, self.script_stdout)
        self.assertNotIn(settings.APP_DB_PASSWORD.get_secret_value(), self.script_stdout)
        if os.name == "posix":
            self.assertEqual(self.env_mode, 0o600)

    def test_the_api_works_as_the_runtime_role(self):
        name = f"role_{uuid.uuid4().hex[:8]}.csv"
        up = self.client.post("/api/csv/upload", json={"fileName": name, "content": f"v\n{name}\n"}).json()
        self.assertEqual(up["status"], "ok", up)
        self.assertIsNotNone(up["uploadId"], "the original must be stored by the runtime role")
        over = self.client.post(
            "/api/csv/upload", json={"fileName": name, "content": f"v\nnew_{name}\n", "overwrite": True}
        ).json()
        self.assertEqual(over["status"], "ok", over)
        # P15 (docs/test-cases/M4-review.md): review changes work through the runtime role.
        decided = self.client.put(
            f"/api/csv/uploads/{up['uploadId']}/rows/1/decision",
            json={"decision": "exclude", "reason": "runtime role case"},
        )
        self.assertEqual(decided.status_code, 200, decided.text)
        edited = self.client.put(
            f"/api/csv/uploads/{up['uploadId']}/rows/1/cells/v",
            json={"value": "changed", "reason": "runtime role case"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.client.delete(f"/api/csv/files/{over['fileId']}").status_code, 200)
        self.assertTrue(self.client.get("/api/audit/verify").json()["intact"])
        with Conn() as conn, conn.cursor() as cur:  # the API's own request pool
            cur.execute("SELECT current_user")
            self.assertEqual(cur.fetchone()[0], self.role)

    def test_the_staged_import_works_as_the_runtime_role(self):
        # M6: the import creates a table and a TEMP staging table, and COPYs into it, all as this role.
        name = f"staged_{uuid.uuid4().hex[:8]}.csv"
        up = self.client.post("/api/csv/uploads", json={"fileName": name, "content": f"v\n{name}\n"}).json()["uploadId"]
        for action, body in (("submit", None), ("approval", {"decision": "approve"})):
            res = self.client.post(f"/api/csv/uploads/{up}/{action}", json=body)
            self.assertEqual(res.status_code, 200, res.text)
        res = self.client.post(f"/api/csv/uploads/{up}/import", headers={"Idempotency-Key": "role-test"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["reconciliation"]["imported"], 1)
        self.assertEqual(self.client.delete(f"/api/csv/files/{res.json()['fileId']}").status_code, 200)

    def test_runtime_role_cannot_change_or_unprotect_append_only_tables(self):
        schema = settings.UPLOADS_SCHEMA
        tables = (
            "audit_log",
            "uploads",
            "upload_blobs",
            "source_rows",
            "row_decisions",
            "cell_edits",
            "row_flags",
            "submissions",
            "approvals",
            "imports",
        )
        statements = [f"{verb} {{}}.{table}" for table in tables for verb in ("DELETE FROM", "TRUNCATE")]
        statements += [
            "UPDATE {}.audit_log SET actor = 'x'",
            "UPDATE {}.uploads SET status = 'failed'",
            "UPDATE {}.row_decisions SET reason = 'x'",
            "UPDATE {}.cell_edits SET new_value = 'x'",  # N15
            "ALTER TABLE {}.audit_log DISABLE TRIGGER audit_no_change",
        ]
        conn = self._as_runtime()
        try:
            for statement in statements:
                with self.subTest(statement=statement), conn.cursor() as cur:
                    with self.assertRaises(psycopg2.errors.InsufficientPrivilege) as caught:
                        cur.execute(sql.SQL(statement).format(sql.Identifier(schema)))
                    # Refused by privilege, not by the trigger: the owner's triggers are a second layer.
                    self.assertNotIn("append-only", str(caught.exception))
                    conn.rollback()
            with conn.cursor() as cur:  # inserting into the audit log still works
                cur.execute(
                    sql.SQL("INSERT INTO {}.audit_log (action, actor) VALUES ('upload', 'role-test')").format(
                        sql.Identifier(schema)
                    )
                )
            conn.rollback()
        finally:
            conn.close()

    def test_a_signed_in_tenant_works_through_its_own_role(self):
        """#297: upload, review, history, audit and a staged import for a signed-in tenant, as the runtime role."""
        slug, pw = f"rt_{uuid.uuid4().hex[:8]}", "correct horse battery staple"
        with Conn() as conn, conn.cursor() as cur:
            tid = accounts.create_tenant(cur, slug, "Runtime role tenant")
            accounts.add_membership(cur, accounts.create_user(cur, f"{slug}_u", pw), tid, "tenant_admin")
            accounts.set_self_approval(cur, slug, True)  # one user here; also checks the session carries the flag
            conn.commit()
        try:
            migrate_tenant(slug)
            login = self.client.post("/api/auth/login", json={"tenant": slug, "username": f"{slug}_u", "password": pw})
            self.assertEqual(login.status_code, 200, login.text)
            h = {"Authorization": f"Bearer {login.json()['token']}"}
            name = f"rt_{uuid.uuid4().hex[:8]}.csv"
            up = self.client.post("/api/csv/upload", headers=h, json={"fileName": name, "content": f"v\n{name}\n"})
            self.assertEqual(up.json()["status"], "ok", up.text)
            uid = up.json()["uploadId"]
            for res in (
                self.client.put(
                    f"/api/csv/uploads/{uid}/rows/1/decision",
                    headers=h,
                    json={"decision": "exclude", "reason": "runtime role case"},
                ),
                self.client.get(f"/api/csv/uploads/{uid}/rows/1/history", headers=h),
                self.client.get(f"/api/csv/tables/{up.json()['tableName']}/rows", headers=h),
                self.client.get("/api/csv/uploads", headers=h),
            ):
                self.assertEqual(res.status_code, 200, res.text)
            self.assertIn(name, [f["file_name"] for f in self.client.get("/api/csv/files", headers=h).json()])
            log = self.client.get("/api/audit/log?limit=50", headers=h).json()["entries"]
            self.assertIn(name, [e["fileName"] for e in log])
            self.assertTrue(self.client.get("/api/audit/verify", headers=h).json()["intact"])
            staged = self.client.post(
                "/api/csv/uploads", headers=h, json={"fileName": "s_" + name, "content": "v\nstaged\n"}
            ).json()["uploadId"]
            for action, body in (("submit", None), ("approval", {"decision": "approve"})):
                res = self.client.post(f"/api/csv/uploads/{staged}/{action}", headers=h, json=body)
                self.assertEqual(res.status_code, 200, res.text)
            res = self.client.post(f"/api/csv/uploads/{staged}/import", headers={**h, "Idempotency-Key": "rt"})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()["reconciliation"]["imported"], 1)

            conn = self._as_runtime()
            try:
                with conn.cursor() as cur:
                    with self.assertRaises(psycopg2.errors.InsufficientPrivilege):  # no rights without SET ROLE
                        cur.execute(sql.SQL("SELECT * FROM {}.csv_files").format(sql.Identifier(schema_for(slug))))
                    conn.rollback()
                    cur.execute(
                        "SELECT m.inherit_option, m.set_option FROM pg_auth_members m "
                        "WHERE m.roleid = to_regrole(%s) AND m.member = to_regrole(%s)",
                        (role_for(slug), self.role),
                    )
                    self.assertEqual(cur.fetchone(), (False, True), "member WITH INHERIT FALSE, SET TRUE")
                    cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role_for(slug))))
                    cur.execute(sql.SQL("SELECT count(*) FROM {}.csv_files").format(sql.Identifier(schema_for(slug))))
                    self.assertGreaterEqual(cur.fetchone()[0], 2)
            finally:
                conn.close()
        finally:
            with _owner() as conn, conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(slug))))
                cur.execute(
                    sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(sql.Identifier(settings.CONTROL_SCHEMA)),
                    (slug,),
                )
                cur.execute(
                    sql.SQL("DELETE FROM {}.users WHERE username = %s").format(sql.Identifier(settings.CONTROL_SCHEMA)),
                    (f"{slug}_u",),
                )
                drop_tenant_role(cur, slug)
