"""Each import's row counts are persisted on its registry row (BR-34, part).

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")


@pytest.mark.integration
class ImportCountsArePersisted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def _registry_entry(self, file_id: str) -> dict:
        files = self.client.get("/api/csv/files").json()
        return next(f for f in files if f["id"] == file_id)

    def _assert_persisted_matches_response(self, res: dict) -> dict:
        entry = self._registry_entry(res["fileId"])
        self.assertEqual(
            (entry["total_rows"], entry["row_count"], entry["duplicate_rows_skipped"], entry["failed_rows"]),
            (res["totalRows"], res["insertedRows"], res["duplicateRowsSkipped"], res["failedRows"]),
        )
        return entry

    def test_dynamic_import_persists_all_four_counts(self):
        # 5 data rows: 2 valid distinct, 1 in-file duplicate, 2 that fail the int8 cast.
        content = f"n,t\n1,{self.tag}\n2,{self.tag}\n1,{self.tag}\nx,{self.tag}\ny,{self.tag}\n"
        res = self.client.post("/api/csv/upload", json={
            "fileName": f"counts_{self.tag}.csv", "content": content, "types": ["int8", "text"],
        }).json()
        self.assertEqual(res["status"], "ok", res)
        entry = self._assert_persisted_matches_response(res)
        self.assertEqual((entry["total_rows"], entry["row_count"], entry["duplicate_rows_skipped"],
                          entry["failed_rows"]), (5, 2, 1, 2))

    def test_te_import_persists_counts(self):
        content = (f"name,org_type,country\nCNT_{self.tag}_1,government,AU\n"
                   f"CNT_{self.tag}_2,government,AU\n")
        res = self.client.post("/api/csv/upload", json={
            "fileName": f"counts_te_{self.tag}.csv", "content": content,
            "mode": "te", "targetTable": "organisations",
        }).json()
        self.assertEqual(res["status"], "ok", res)
        entry = self._assert_persisted_matches_response(res)
        self.assertEqual((entry["total_rows"], entry["row_count"], entry["failed_rows"]), (2, 2, 0))
