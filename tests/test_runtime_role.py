"""The API's runtime role can only read and insert the append-only tables (M3d, #107; BR-24, BR-35).

Integration: needs a live PostgreSQL and an owner that can create roles (CI's
postgres superuser). Fails (never skips) without one. Runs the real
scripts/create_app_role.py, then drives the API as that role.
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

from api.config import settings
from api.db import Conn
from api.main import app

_ROOT = Path(__file__).resolve().parent.parent


def _owner():
    return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                            password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)


@pytest.mark.integration
class RuntimeRole(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.role = f"te_app_test_{uuid.uuid4().hex[:8]}"
        cls.tmp = tempfile.TemporaryDirectory()
        env_file = Path(cls.tmp.name) / "app-db.env"
        run = subprocess.run([sys.executable, "scripts/create_app_role.py", "--role", cls.role,
                              "--env-file", str(env_file)], cwd=_ROOT, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        cls.script_stdout = run.stdout
        values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        cls.env_mode = env_file.stat().st_mode & 0o777
        cls._orig = (settings.APP_DB_USER, settings.APP_DB_PASSWORD, settings.allow_destructive)
        settings.APP_DB_USER, settings.APP_DB_PASSWORD = values["APP_DB_USER"], values["APP_DB_PASSWORD"]
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
        return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.APP_DB_USER,
                                password=settings.APP_DB_PASSWORD, dbname=settings.PG_DATABASE)

    def test_script_keeps_the_password_out_of_its_output(self):
        self.assertIn(self.role, self.script_stdout)
        self.assertNotIn(settings.APP_DB_PASSWORD, self.script_stdout)
        if os.name == "posix":
            self.assertEqual(self.env_mode, 0o600)

    def test_the_api_works_as_the_runtime_role(self):
        name = f"role_{uuid.uuid4().hex[:8]}.csv"
        up = self.client.post("/api/csv/upload", json={"fileName": name, "content": f"v\n{name}\n"}).json()
        self.assertEqual(up["status"], "ok", up)
        self.assertIsNotNone(up["uploadId"], "the original must be stored by the runtime role")
        over = self.client.post("/api/csv/upload", json={
            "fileName": name, "content": f"v\nnew_{name}\n", "overwrite": True}).json()
        self.assertEqual(over["status"], "ok", over)
        # P15 (docs/test-cases/M4-review.md): review changes work through the runtime role.
        decided = self.client.put(f"/api/csv/uploads/{up['uploadId']}/rows/1/decision",
                                  json={"decision": "exclude", "reason": "runtime role case"})
        self.assertEqual(decided.status_code, 200, decided.text)
        edited = self.client.put(f"/api/csv/uploads/{up['uploadId']}/rows/1/cells/v",
                                 json={"value": "changed", "reason": "runtime role case"})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.client.delete(f"/api/csv/files/{over['fileId']}").status_code, 200)
        self.assertTrue(self.client.get("/api/audit/verify").json()["intact"])
        with Conn() as conn, conn.cursor() as cur:   # the API's own request pool
            cur.execute("SELECT current_user")
            self.assertEqual(cur.fetchone()[0], self.role)

    def test_runtime_role_cannot_change_or_unprotect_append_only_tables(self):
        schema = settings.UPLOADS_SCHEMA
        tables = ("audit_log", "uploads", "upload_blobs", "source_rows", "row_decisions", "cell_edits")
        statements = [f"{verb} {{}}.{table}" for table in tables for verb in ("DELETE FROM", "TRUNCATE")]
        statements += ["UPDATE {}.audit_log SET actor = 'x'", "UPDATE {}.uploads SET status = 'failed'",
                       "UPDATE {}.row_decisions SET reason = 'x'", "UPDATE {}.cell_edits SET new_value = 'x'",  # N15
                       "ALTER TABLE {}.audit_log DISABLE TRIGGER audit_no_change"]
        conn = self._as_runtime()
        try:
            for statement in statements:
                with self.subTest(statement=statement), conn.cursor() as cur:
                    with self.assertRaises(psycopg2.errors.InsufficientPrivilege) as caught:
                        cur.execute(sql.SQL(statement).format(sql.Identifier(schema)))
                    # Refused by privilege, not by the trigger: the owner's triggers are a second layer.
                    self.assertNotIn("append-only", str(caught.exception))
                    conn.rollback()
            with conn.cursor() as cur:   # inserting into the audit log still works
                cur.execute(sql.SQL("INSERT INTO {}.audit_log (action, actor) VALUES ('upload', 'role-test')")
                            .format(sql.Identifier(schema)))
            conn.rollback()
        finally:
            conn.close()
