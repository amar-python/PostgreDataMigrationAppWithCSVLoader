"""#287 (OIT-002, BR-51): a T&E upload must never drop a dynamic dataset's table.

Reproduction R2 of the 2026-11-20 review: upload some bytes as a dynamic dataset, then upload the same
bytes in T&E mode. The T&E path matched the earlier registry row by content hash, dropped the dataset's
``csv_*`` table and deleted its registry row, and returned 200, with ``API_ALLOW_DESTRUCTIVE`` off. With
no session (the shared-key path) not even delete permission was checked.

Asserted here for both callers, with the flag off: the dataset's table, rows and registry row survive,
and the T&E upload changes nothing (no T&E rows land, no T&E registry row). Needs a live PostgreSQL with
the dev schema deployed, as in CI.
"""

from __future__ import annotations

import unittest
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app
from tests.system.test_issue_regressions import UploadPaths


class _SameBytesBothModes:
    """Shared steps; subclasses say who the caller is through ``headers``."""

    client: TestClient
    headers: dict
    schema: str
    te_schema: str

    def _post(self, **body):
        return self.client.post("/api/csv/upload", headers=self.headers, json=body)

    def _files(self) -> list[dict]:
        res = self.client.get("/api/csv/files", headers=self.headers)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _table_exists(self, table: str) -> bool:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f'"{self.schema}"."{table}"',))
            return cur.fetchone()[0] is not None

    def _te_rows(self, org: str) -> int:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT count(*) FROM {}.organisations WHERE name = %s").format(sql.Identifier(self.te_schema)),
                (org,),
            )
            return cur.fetchone()[0]

    def _drop_org(self, org: str) -> None:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {}.organisations WHERE name = %s").format(sql.Identifier(self.te_schema)), (org,)
            )
            conn.commit()

    def check_te_upload_of_a_datasets_bytes_leaves_the_dataset_alone(self):
        tag = uuid.uuid4().hex[:10]
        org = f"ORG_{tag}"
        content = f"name,org_type,country\n{org},government,AU\n"
        self.addCleanup(self._drop_org, org)

        dyn = self._post(fileName=f"r2_{tag}.csv", content=content, mode="dynamic").json()
        self.assertEqual(dyn["status"], "ok", dyn)
        table = dyn["tableName"]
        self.assertTrue(self._table_exists(table))

        res = self._post(fileName=f"r2_{tag}_te.csv", content=content, mode="te", targetTable="organisations")

        self.assertTrue(self._table_exists(table), f"the dataset's table was dropped: {res.status_code} {res.text}")
        registered = [(f["mode"], f["table_name"]) for f in self._files() if tag in f["file_name"]]
        self.assertEqual(
            registered, [("dynamic", table)], "the dataset's registry row must survive and no T&E row may replace it"
        )
        self.assertEqual(self._te_rows(org), 0, "a refused T&E upload must not leave rows behind")
        self.assertIn(res.status_code, (200, 403, 409), res.text)
        if res.status_code == 200:
            body = res.json()
            self.assertEqual(body["status"], "duplicate_file", body)
            self.assertEqual(body.get("existingMode"), "dynamic", body)


@pytest.mark.integration
class SharedKeyTeUploadCannotDropADataset(_SameBytesBothModes, unittest.TestCase):
    """No session: the shared-key (or open dev) path, where the role check returned early."""

    @classmethod
    def setUpClass(cls):
        cls._orig_flag = settings.allow_destructive
        settings.allow_destructive = False
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        cls.headers = {}
        cls.schema = settings.UPLOADS_SCHEMA
        cls.te_schema = settings.TE_SCHEMA

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        settings.allow_destructive = cls._orig_flag

    def test_te_upload_of_a_datasets_bytes_leaves_the_dataset_alone(self):
        self.check_te_upload_of_a_datasets_bytes_leaves_the_dataset_alone()


@pytest.mark.integration
class SignedInTeUploadCannotDropADataset(_SameBytesBothModes, UploadPaths):
    """A signed-in tenant admin, who holds delete permission: still no drop with the flag off."""

    @classmethod
    def setUpClass(cls):
        cls._orig_flag = settings.allow_destructive
        settings.allow_destructive = False
        super().setUpClass()
        cls.role_headers = cls.headers
        cls.headers = cls.role_headers["tenant_admin"]
        from api.tenancy import schema_for

        cls.schema = cls.te_schema = schema_for(cls.slug)

    @classmethod
    def tearDownClass(cls):
        cls.headers = cls.role_headers
        super().tearDownClass()
        settings.allow_destructive = cls._orig_flag

    def test_te_upload_of_a_datasets_bytes_leaves_the_dataset_alone(self):
        self.check_te_upload_of_a_datasets_bytes_leaves_the_dataset_alone()
