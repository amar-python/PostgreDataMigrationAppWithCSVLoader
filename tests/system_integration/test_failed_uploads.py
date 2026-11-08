"""An upload where every row fails is a failed upload, not a migrated file (#123).

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


@pytest.mark.integration
class EveryRowFailed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.name = f"allfail_{self.tag}.csv"

    def _upload(self, content: str, types: list[str], overwrite: bool = False) -> dict:
        return self.client.post("/api/csv/upload", json={
            "fileName": self.name, "content": content, "types": types, "overwrite": overwrite}).json()

    def _registered(self) -> list[dict]:
        return [f for f in self.client.get("/api/csv/files").json() if f["file_name"] == self.name]

    def _table_exists(self, table: str) -> bool:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (sql.Identifier(settings.UPLOADS_SCHEMA, table).as_string(cur),))
            return cur.fetchone()[0] is not None

    def test_every_row_failing_is_an_error_and_saves_nothing(self):
        # The #123 file: dates like "27 Oct 26" sent as timestamptz, which the API rejects.
        content = f"Date,Ref\n27 Oct 26,{self.tag}a\n28 Oct 26,{self.tag}b\n"
        res = self._upload(content, ["timestamptz", "text"])
        self.assertEqual(res["status"], "error", res)
        self.assertIn("None of the 2 rows could be imported", res["message"])
        self.assertIn('row 1, column "date"', res["message"])
        self.assertEqual((res["totalRows"], res["failedRows"], len(res["rowErrors"])), (2, 2, 2))
        self.assertEqual(self._registered(), [], "a file with no imported rows must not be listed as migrated")

    def test_failed_overwrite_keeps_the_previous_upload(self):
        good = self._upload(f"n\n1\n2\n{self.tag}\n", ["text"])
        self.assertEqual(good["status"], "ok", good)
        res = self._upload(f"n\nx{self.tag}\ny{self.tag}\n", ["int8"], overwrite=True)
        self.assertEqual(res["status"], "error", res)
        files = self._registered()
        self.assertEqual([(f["table_name"], f["row_count"]) for f in files], [(good["tableName"], 3)])
        self.assertTrue(self._table_exists(good["tableName"]), "the previous table must survive")

    def test_partly_failed_upload_still_imports_and_reports_the_failures(self):
        res = self._upload(f"n,t\n1,{self.tag}\nx,{self.tag}\n", ["int8", "text"])
        self.assertEqual((res["status"], res["insertedRows"], res["failedRows"]), ("ok", 1, 1), res)
        [entry] = self._registered()
        self.assertEqual((entry["row_count"], entry["total_rows"], entry["failed_rows"]), (1, 2, 1))
